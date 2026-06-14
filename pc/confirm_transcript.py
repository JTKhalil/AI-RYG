"""监听 Claude transcript，在用户点 No/Yes 或 Ctrl+C 后补发 Hook。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

INTERRUPT_TEXT = "[Request interrupted by user for tool use]"
USER_INTERRUPT_MARKERS = (
    "[Request interrupted by user]",
    INTERRUPT_TEXT,
)
DENY_MARKERS = (
    INTERRUPT_TEXT,
    "User rejected tool use",
    "doesn't want to proceed with this tool use",
    "The tool use was rejected",
)
WATCH_POLL_SEC = 0.25
WATCH_TIMEOUT_SEC = 600.0
RECENT_TRANSCRIPT_SEC = 180.0

if sys.platform == "win32":
    _DETACHED = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW
else:
    _DETACHED = 0
    _NO_WINDOW = 0


def _encode_project_dir(cwd: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in cwd).strip("-")


def resolve_transcript_path(payload: dict | None = None) -> Path | None:
    """从 Hook payload / 状态 / 最近会话文件解析 transcript 路径。"""
    payload = payload or {}

    for key in ("transcript_path", "transcriptPath"):
        raw = payload.get(key)
        if raw:
            path = Path(str(raw))
            if path.is_file():
                return path

    session_id = payload.get("session_id") or payload.get("sessionId")
    cwd = str(payload.get("cwd") or "")

    if session_id:
        projects = Path.home() / ".claude" / "projects"
        if projects.is_dir():
            for path in projects.rglob(f"{session_id}.jsonl"):
                if path.is_file():
                    return path

    if session_id and cwd:
        candidate = (
            Path.home()
            / ".claude"
            / "projects"
            / _encode_project_dir(cwd)
            / f"{session_id}.jsonl"
        )
        if candidate.is_file():
            return candidate

    if session_id:
        projects = Path.home() / ".claude" / "projects"
        if projects.is_dir():
            for path in projects.rglob(f"{session_id}.jsonl"):
                if path.is_file():
                    return path

    try:
        from light_state import read_state

        state = read_state()
        stored = state.get("transcript_path")
        if stored:
            path = Path(str(stored))
            if path.is_file():
                return path
        session_id = session_id or state.get("session_id")
        cwd = cwd or str(state.get("cwd") or "")
        if session_id and cwd:
            candidate = (
                Path.home()
                / ".claude"
                / "projects"
                / _encode_project_dir(cwd)
                / f"{session_id}.jsonl"
            )
            if candidate.is_file():
                return candidate
        if session_id:
            projects = Path.home() / ".claude" / "projects"
            if projects.is_dir():
                for path in projects.rglob(f"{session_id}.jsonl"):
                    if path.is_file():
                        return path
    except OSError:
        pass

    return _find_recent_transcript()


def _find_recent_transcript(max_age_sec: float = RECENT_TRANSCRIPT_SEC) -> Path | None:
    projects = Path.home() / ".claude" / "projects"
    if not projects.is_dir():
        return None
    now = time.time()
    best: Path | None = None
    best_mtime = 0.0
    for path in projects.rglob("*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if now - mtime > max_age_sec:
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best = path
    return best


def _hook_command(state: str, event: str) -> list[str]:
    from app_paths import hook_exe_path

    target = hook_exe_path()
    if target.suffix.lower() == ".exe":
        return [str(target), state, "--event", event]
    return [sys.executable, str(target), state, "--event", event]


def _spawn_watch(cmd: list[str], *, log_label: str, transcript_path: str, offset: int) -> None:
    flags = _DETACHED | _NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    try:
        from datetime import datetime

        from app_paths import log_path

        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = (
            f"{datetime.now().isoformat(timespec='seconds')} "
            f"hook scheduled {log_label} offset={offset} path={transcript_path}\n"
        )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def _log_schedule_skipped(payload: dict, reason: str) -> None:
    try:
        from datetime import datetime

        from app_paths import log_path

        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        keys = ",".join(sorted(payload.keys())) or "(empty)"
        line = (
            f"{datetime.now().isoformat(timespec='seconds')} "
            f"hook transcript-watch skipped reason={reason} payload_keys={keys}\n"
        )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def schedule_transcript_watch(*, payload: dict) -> None:
    path = resolve_transcript_path(payload)
    if path is None:
        _log_schedule_skipped(payload, "no_transcript_path")
        return
    try:
        offset = path.stat().st_size
    except OSError:
        _log_schedule_skipped(payload, "stat_failed")
        return

    cmd = _hook_command("watch-transcript", "PermissionRequest")
    cmd.extend(["--transcript", str(path), "--offset", str(offset)])
    _spawn_watch(cmd, log_label="transcript-watch", transcript_path=str(path), offset=offset)


def schedule_thinking_interrupt_watch(*, payload: dict) -> None:
    """Claude Ctrl+C 不触发 Stop，监听 transcript 中的 interrupt 标记（备用）。"""
    path = resolve_transcript_path(payload)
    if path is None:
        _log_schedule_skipped(payload, "no_transcript_path")
        return
    try:
        offset = path.stat().st_size
    except OSError:
        _log_schedule_skipped(payload, "stat_failed")
        return

    cmd = _hook_command("watch-transcript", "UserPromptSubmit")
    cmd.extend(["--transcript", str(path), "--offset", str(offset), "--mode", "thinking"])
    _spawn_watch(
        cmd,
        log_label="thinking-interrupt-watch",
        transcript_path=str(path),
        offset=offset,
    )


def _invoke_hook(state: str, event: str) -> None:
    """内部补发灯态，不走 subprocess，避免被 Cursor/Claude 来源过滤拦截。"""
    try:
        from datetime import datetime

        from app_paths import log_path
        from light_ipc import send_notify
        from light_state import apply_hook
        from tray_launcher import ensure_tray_if_needed
        from unicode_safe import ipc_payload

        payload = {"hook_event_name": event}
        apply_hook(state, payload)
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = (
            f"{datetime.now().isoformat(timespec='seconds')} "
            f"hook internal {state} event={event}\n"
        )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        if not send_notify(state, ipc_payload(payload)):
            ensure_tray_if_needed()
    except OSError:
        pass


def _chunk_denies_tool(chunk: str) -> bool:
    if any(marker in chunk for marker in DENY_MARKERS):
        return True
    if "tool_result" not in chunk:
        return False
    compact = re.sub(r"\s+", "", chunk)
    if '"is_error":true' in compact:
        return True
    return False


def _chunk_allows_tool(chunk: str) -> bool:
    if _chunk_denies_tool(chunk):
        return False
    return '"type":"tool_result"' in chunk or '"type": "tool_result"' in chunk


def _chunk_user_interrupted(chunk: str) -> bool:
    for line in chunk.splitlines():
        if _line_is_user_interrupt(line):
            return True
    return False


def _line_is_user_interrupt(line: str) -> bool:
    line = line.strip()
    if not line:
        return False
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return False
    if obj.get("type") != "user":
        return False
    if obj.get("interruptedMessageId"):
        return True
    message = obj.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str) and any(marker in text for marker in USER_INTERRUPT_MARKERS):
            return True
    return False


def _line_is_tool_denied(line: str) -> bool:
    line = line.strip()
    if not line:
        return False
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return False
    if obj.get("type") != "user":
        return False
    if obj.get("toolUseResult") == "User rejected tool use":
        return True
    return _chunk_denies_tool(line)


def _parse_iso_ts(raw: str) -> float | None:
    from datetime import datetime

    if not raw:
        return None
    try:
        text = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _chunk_has_cancel(chunk: str, *, since_ts: float | None = None) -> bool:
    for line in chunk.splitlines():
        if since_ts:
            try:
                obj = json.loads(line.strip())
                ts = _parse_iso_ts(str(obj.get("timestamp") or ""))
                if ts is not None and ts < since_ts - 1.0:
                    continue
            except json.JSONDecodeError:
                pass
        if _line_is_user_interrupt(line) or _line_is_tool_denied(line):
            return True
    return False


def _candidate_transcript_paths(state: dict) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None or not path.is_file():
            return
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        paths.append(path)

    add(_resolve_from_state(state))

    session_id = state.get("session_id")
    cwd = state.get("cwd")
    if session_id:
        projects = Path.home() / ".claude" / "projects"
        if projects.is_dir():
            for path in projects.rglob(f"{session_id}.jsonl"):
                add(path)
    if session_id and cwd:
        add(
            Path.home()
            / ".claude"
            / "projects"
            / _encode_project_dir(str(cwd))
            / f"{session_id}.jsonl"
        )

    add(_find_recent_transcript(max_age_sec=RECENT_TRANSCRIPT_SEC))
    return paths


def _path_has_cancel(path: Path, offset: int, *, since_ts: float | None = None) -> bool:
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size <= offset:
        return False
    try:
        with path.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read(size - offset).decode("utf-8", errors="replace")
    except OSError:
        return False
    return _chunk_has_cancel(chunk, since_ts=since_ts)


INTERRUPT_POLL_SEC = 0.35


def _resolve_from_state(state: dict) -> Path | None:
    stored = state.get("transcript_path")
    if stored:
        path = Path(str(stored))
        if path.is_file():
            return path
    payload: dict = {}
    if state.get("session_id"):
        payload["session_id"] = state["session_id"]
    if state.get("cwd"):
        payload["cwd"] = state["cwd"]
    return resolve_transcript_path(payload)


def check_user_interrupt(state: dict) -> bool:
    """读取本轮 thinking 开始后 transcript 中的中断 / 工具拒绝。"""
    since = float(state.get("thinking_started_at") or 0)
    if since <= 0:
        return False

    stored = str(state.get("transcript_path") or "")
    stored_offset = int(state.get("thinking_watch_offset") or 0)

    for path in _candidate_transcript_paths(state):
        same_file = stored and str(path.resolve()) == str(Path(stored).resolve())
        offset = stored_offset if same_file and "thinking_watch_offset" in state else 0
        if _path_has_cancel(path, offset, since_ts=since):
            return True
    return False


def has_pending_tool_permission(state: dict) -> bool:
    """transcript 里已有 tool_use 但尚无 tool_result → 正在等权限确认，不能切绿灯。"""
    since = float(state.get("thinking_started_at") or 0)
    if since <= 0:
        return False

    pending: set[str] = set()
    resolved: set[str] = set()

    for path in _candidate_transcript_paths(state):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_iso_ts(str(obj.get("timestamp") or ""))
            if ts is not None and ts < since - 1.0:
                continue
            if obj.get("type") == "assistant":
                message = obj.get("message")
                if not isinstance(message, dict):
                    message = obj
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_id = block.get("id")
                            if tool_id:
                                pending.add(str(tool_id))
            elif obj.get("type") == "user":
                message = obj.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        tool_id = block.get("tool_use_id")
                        if tool_id:
                            resolved.add(str(tool_id))

    return bool(pending - resolved)


def is_awaiting_tool_permission(state: dict) -> bool:
    """等待工具权限：已有 tool_use 或 assistant stop_reason=tool_use。"""
    if has_pending_tool_permission(state):
        return True

    since = float(state.get("thinking_started_at") or 0)
    if since <= 0:
        return False

    for path in _candidate_transcript_paths(state):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_iso_ts(str(obj.get("timestamp") or ""))
            if ts is not None and ts < since - 1.0:
                continue
            if obj.get("type") != "assistant":
                continue
            message = obj.get("message")
            if not isinstance(message, dict):
                message = obj
            if message.get("stop_reason") == "tool_use":
                return True
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        return True
    return False


def has_assistant_activity_since(state: dict) -> bool:
    """本轮 thinking 开始后是否已有 Claude 回复（含 tool_use）。"""
    since = float(state.get("thinking_started_at") or 0)
    if since <= 0:
        return False

    for path in _candidate_transcript_paths(state):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_iso_ts(str(obj.get("timestamp") or ""))
            if ts is not None and ts < since - 1.0:
                continue
            if obj.get("type") == "assistant":
                return True
    return False


def run_transcript_watch(
    transcript_path: str,
    start_offset: int,
    *,
    watch_mode: str = "confirm",
) -> int:
    from light_state import read_state

    path = Path(transcript_path)
    if not path.exists():
        return 0

    expected_mode = "confirm" if watch_mode == "confirm" else "thinking"
    offset = start_offset
    deadline = time.time() + WATCH_TIMEOUT_SEC
    while time.time() < deadline:
        if read_state().get("mode") != expected_mode:
            return 0

        try:
            size = path.stat().st_size
        except OSError:
            time.sleep(WATCH_POLL_SEC)
            continue

        if size > offset:
            try:
                with path.open("rb") as fh:
                    fh.seek(offset)
                    chunk = fh.read(size - offset).decode("utf-8", errors="replace")
            except OSError:
                chunk = ""
            offset = size
            if watch_mode == "thinking":
                if _chunk_has_cancel(chunk):
                    _invoke_hook("done", "UserInterrupt")
                    return 0
            else:
                if _chunk_denies_tool(chunk):
                    _invoke_hook("done", "TranscriptDenied")
                    return 0
                if _chunk_allows_tool(chunk):
                    _invoke_hook("thinking", "TranscriptAllowed")
                    return 0

        time.sleep(WATCH_POLL_SEC)

    return 0
