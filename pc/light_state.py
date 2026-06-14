"""共享状态：Hook 只写状态，守护进程独占串口并维持常亮。"""

from __future__ import annotations

import json
import msvcrt
import time

from app_paths import lock_path, state_path

NEW_TURN_EVENTS = frozenset(
    {
        "beforeSubmitPrompt",
        "UserPromptSubmit",
        "sessionStart",
        "SessionStart",
    }
)

RESUMABLE_MODES = frozenset({"thinking", "done"})
PERMISSION_PROMPT_MIN_AGE_SEC = 2.0
NOTIFICATION_IDLE_TYPES = frozenset({"idle_prompt"})
NOTIFICATION_SKIP_RESTORE = frozenset({"auth_success", "elicitation_dialog", "elicitation_complete"})
# 点 No 后才应触发的恢复事件（不用定时器，避免弹窗未操作就亮绿灯）
CONFIRM_DONE_EVENTS = frozenset(
    {
        "PermissionDenied",
        "Stop",
    }
)
# MessageDisplay 在展示权限说明时就会触发，不能用来判断「已点 No」
CONFIRM_IGNORE_EVENTS = frozenset({"MessageDisplay"})


class FileLock:
    def __init__(self, path, timeout: float = 5.0) -> None:
        self.path = path
        self.timeout = timeout
        self._fh = None

    def __enter__(self) -> FileLock:
        deadline = time.time() + self.timeout
        while True:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a+")
            try:
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except OSError:
                self._fh.close()
                if time.time() >= deadline:
                    raise TimeoutError(f"状态锁等待超时: {self.path}")
                time.sleep(0.02)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fh is not None:
            try:
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                self._fh.close()


def default_state() -> dict:
    return {"mode": "off"}


def read_state() -> dict:
    path = state_path()
    if not path.exists():
        return default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_state()
    merged = default_state()
    merged.update(data)
    return merged


def write_state(data: dict) -> None:
    from unicode_safe import sanitize_obj

    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(sanitize_obj(data), ensure_ascii=False)
    path.write_text(text, encoding="utf-8", errors="replace")


def update_state(mutator) -> dict:
    with FileLock(lock_path()):
        data = read_state()
        mutator(data)
        write_state(data)
        return data


def _is_stale_thinking(data: dict, event: str, generation_id: str | None) -> bool:
    if event in NEW_TURN_EVENTS:
        return False

    settled = data.get("settled_generation")
    if generation_id and settled and generation_id == settled:
        return True

    if data.get("mode") == "done":
        return True

    if data.get("mode") == "error" and event not in NEW_TURN_EVENTS:
        return True

    return False


def _copy_transcript_watch_fields(dst: dict, src: dict) -> None:
    for key in (
        "transcript_path",
        "thinking_watch_offset",
        "session_id",
        "cwd",
        "thinking_started_at",
        "thinking_session_status",
        "thinking_session_baseline_at",
    ):
        if key in src:
            dst[key] = src[key]


def _attach_transcript_watch_fields(state: dict, payload: dict) -> None:
    from claude_session import snapshot_session_baseline
    from confirm_transcript import resolve_transcript_path

    path = resolve_transcript_path(payload)
    if path is None:
        recent = None
        try:
            from confirm_transcript import _find_recent_transcript

            recent = _find_recent_transcript(max_age_sec=60.0)
        except OSError:
            pass
        path = recent
    if path is not None:
        state["transcript_path"] = str(path)
    session_id = payload.get("session_id") or payload.get("sessionId")
    if session_id:
        state["session_id"] = session_id
    cwd = payload.get("cwd")
    if cwd:
        state["cwd"] = cwd
    if path is not None:
        try:
            state["thinking_watch_offset"] = path.stat().st_size
        except OSError:
            state["thinking_watch_offset"] = 0
    state["thinking_started_at"] = time.time()
    snapshot_session_baseline(state)


def mark_thinking(
    *,
    event: str = "",
    generation_id: str | None = None,
    payload: dict | None = None,
) -> None:
    payload = payload or {}
    with FileLock(lock_path()):
        data = read_state()
        if data.get("mode") == "confirm":
            if event in NEW_TURN_EVENTS:
                _finish_confirm_as_done(data)
                if generation_id:
                    data["generation_id"] = generation_id
                data.pop("transcript_path", None)
                data.pop("session_id", None)
                data.pop("cwd", None)
                data.pop("thinking_watch_offset", None)
                write_state(data)
                return
            _restore_from_confirm(data)
            if generation_id:
                data["generation_id"] = generation_id
            write_state(data)
            return
        if _is_stale_thinking(data, event, generation_id):
            return
        if event in NEW_TURN_EVENTS and data.get("mode") != "confirm":
            new_state: dict = {"mode": "thinking"}
            if generation_id:
                new_state["generation_id"] = generation_id
            elif data.get("generation_id"):
                new_state["generation_id"] = data["generation_id"]
            _attach_transcript_watch_fields(new_state, payload)
            write_state(new_state)
            return
        if data.get("mode") == "thinking" and not generation_id:
            return
        if (
            data.get("mode") == "thinking"
            and generation_id
            and data.get("generation_id") == generation_id
        ):
            return
        new_state: dict = {"mode": "thinking"}
        if generation_id:
            new_state["generation_id"] = generation_id
        if event in NEW_TURN_EVENTS:
            _attach_transcript_watch_fields(new_state, payload)
        else:
            _copy_transcript_watch_fields(new_state, data)
            if not new_state.get("transcript_path"):
                _attach_transcript_watch_fields(new_state, payload)
            elif "thinking_watch_offset" not in new_state:
                from pathlib import Path

                try:
                    new_state["thinking_watch_offset"] = Path(
                        str(new_state["transcript_path"])
                    ).stat().st_size
                except OSError:
                    pass
        write_state(new_state)


def _restore_from_confirm(data: dict) -> None:
    resume = data.pop("resume_mode", "thinking")
    if resume not in RESUMABLE_MODES:
        resume = "thinking"
    data["mode"] = resume
    if resume == "done":
        done_at = data.pop("resume_done_at", None)
        if done_at is not None:
            data["done_at"] = done_at
        settled = data.pop("resume_settled_generation", None)
        if settled:
            data["settled_generation"] = settled
    else:
        data.pop("resume_done_at", None)
        data.pop("resume_settled_generation", None)
    _clear_confirm_context(data)


def mark_confirm(
    *,
    event: str = "",
    generation_id: str | None = None,
    payload: dict | None = None,
) -> None:
    payload = payload or {}
    with FileLock(lock_path()):
        data = read_state()
        if data.get("mode") == "error":
            return
        if _is_stale_thinking(data, event, generation_id):
            return
        if data.get("mode") != "confirm":
            previous = data.get("mode", "thinking")
            data["resume_mode"] = previous if previous in RESUMABLE_MODES else "thinking"
            if previous == "done":
                if "done_at" in data:
                    data["resume_done_at"] = data["done_at"]
                if "settled_generation" in data:
                    data["resume_settled_generation"] = data.get("settled_generation")
        data["mode"] = "confirm"
        data["confirm_at"] = time.time()
        if generation_id:
            data["generation_id"] = generation_id
        transcript_path = payload.get("transcript_path") or payload.get("transcriptPath")
        if transcript_path:
            data["transcript_path"] = transcript_path
        session_id = payload.get("session_id") or payload.get("sessionId")
        if session_id:
            data["session_id"] = session_id
        cwd = payload.get("cwd")
        if cwd:
            data["cwd"] = cwd
        write_state(data)


def _finish_confirm_as_done(data: dict) -> None:
    generation_id = data.get("generation_id")
    data.clear()
    data["mode"] = "done"
    data["done_at"] = time.time()
    if generation_id:
        data["settled_generation"] = generation_id


def _finish_thinking_as_done(data: dict) -> None:
    _finish_confirm_as_done(data)


def _clear_confirm_context(data: dict) -> None:
    data.pop("transcript_path", None)
    data.pop("session_id", None)
    data.pop("cwd", None)
    data.pop("thinking_watch_offset", None)
    data.pop("confirm_at", None)


def mark_confirm_done_if_pending() -> bool:
    with FileLock(lock_path()):
        data = read_state()
        if data.get("mode") != "confirm":
            return False
        _finish_confirm_as_done(data)
        write_state(data)
        return True


def mark_restore_from_confirm(*, event: str = "", payload: dict | None = None) -> bool:
    """Claude 点 No / idle_prompt / Stop 等恢复；idle_prompt 也用于 Ctrl+C 后回到等待输入。"""
    payload = payload or {}
    with FileLock(lock_path()):
        data = read_state()
        mode = data.get("mode")

        if event == "Notification":
            ntype = payload.get("notification_type", "")
            if ntype in NOTIFICATION_SKIP_RESTORE:
                return False
            if ntype in NOTIFICATION_IDLE_TYPES:
                if mode == "confirm":
                    _finish_confirm_as_done(data)
                    write_state(data)
                    return True
                if mode == "thinking":
                    _finish_thinking_as_done(data)
                    write_state(data)
                    return True
                return False
            if ntype == "permission_prompt":
                return False

        if mode != "confirm":
            return False

        if event in CONFIRM_IGNORE_EVENTS:
            return False

        if event in CONFIRM_DONE_EVENTS:
            _finish_confirm_as_done(data)
            write_state(data)
            return True

        _restore_from_confirm(data)
        write_state(data)
        return True


def mark_done(*, generation_id: str | None = None) -> None:
    def mutate(data: dict) -> None:
        settled = generation_id or data.get("generation_id")
        data.clear()
        data["mode"] = "done"
        data["done_at"] = time.time()
        if settled:
            data["settled_generation"] = settled

    update_state(mutate)


def mark_error() -> None:
    def mutate(data: dict) -> None:
        data.clear()
        data["mode"] = "error"

    update_state(mutate)


def mark_off() -> None:
    def mutate(data: dict) -> None:
        data.clear()
        data.update(default_state())

    update_state(mutate)


def apply_hook(state: str, payload: dict | None = None) -> None:
    """根据 Hook 事件与 stdin 上下文写入灯态。

    红灯仅在整轮失败、无法继续时触发（Cursor stop/error、Claude StopFailure），
    单次工具失败仍保持黄灯 thinking。
    """
    payload = payload or {}
    event = payload.get("hook_event_name", "")
    generation_id = payload.get("generation_id")

    if state == "off":
        mark_off()
        return
    if state == "error":
        if event in ("StopFailure", "stop", "Stop"):
            mark_error()
        return
    if state == "done":
        if event in ("TranscriptDenied", "ConfirmTimeout"):
            if mark_confirm_done_if_pending():
                return
            return
        if event in ("stop", "Stop", "UserInterrupt"):
            if event != "UserInterrupt":
                status = payload.get("status", "completed")
                if status == "error":
                    mark_error()
                    return
                if status == "aborted":
                    mark_off()
                    return
        mark_done(generation_id=generation_id)
        return
    if state == "thinking":
        mark_thinking(event=event, generation_id=generation_id, payload=payload)
        return
    if state == "confirm":
        mark_confirm(event=event, generation_id=generation_id, payload=payload)
        return
    if state == "restore":
        mark_restore_from_confirm(event=event, payload=payload)
        return


def resolve_output(data: dict | None = None) -> str:
    data = data or read_state()
    mode = data.get("mode", "off")

    if mode == "error":
        return "error"
    if mode == "done":
        return "done"
    if mode == "confirm":
        return "confirm"
    if mode == "thinking":
        return "thinking"
    return "off"