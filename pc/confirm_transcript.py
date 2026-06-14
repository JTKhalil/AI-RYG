"""监听 Claude transcript，在用户点 No/Yes 后补发 Hook（Claude 本身常不发事件）。"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

INTERRUPT_TEXT = "[Request interrupted by user for tool use]"
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


def _log_schedule(transcript_path: str, offset: int, source: str) -> None:
    try:
        from datetime import datetime

        from app_paths import log_path

        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = (
            f"{datetime.now().isoformat(timespec='seconds')} "
            f"hook scheduled transcript-watch offset={offset} "
            f"source={source} path={transcript_path}\n"
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
    flags = _DETACHED | _NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    source = "payload" if payload.get("transcript_path") else "fallback"
    _log_schedule(str(path), offset, source)


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


def run_transcript_watch(transcript_path: str, start_offset: int) -> int:
    from light_state import read_state

    path = Path(transcript_path)
    if not path.exists():
        return 0

    offset = start_offset
    deadline = time.time() + WATCH_TIMEOUT_SEC
    while time.time() < deadline:
        if read_state().get("mode") != "confirm":
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
            if _chunk_denies_tool(chunk):
                _invoke_hook("done", "TranscriptDenied")
                return 0
            if _chunk_allows_tool(chunk):
                _invoke_hook("thinking", "TranscriptAllowed")
                return 0

        time.sleep(WATCH_POLL_SEC)

    return 0
