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
# stop 之后到达的 thinking Hook 视为迟到事件，保持绿灯直到新回合开始


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
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


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


def mark_thinking(*, event: str = "", generation_id: str | None = None) -> None:
    with FileLock(lock_path()):
        data = read_state()
        if _is_stale_thinking(data, event, generation_id):
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
        write_state(new_state)


def mark_confirm(*, event: str = "", generation_id: str | None = None) -> None:
    with FileLock(lock_path()):
        data = read_state()
        if data.get("mode") == "error":
            return
        if _is_stale_thinking(data, event, generation_id):
            return
        if data.get("mode") == "confirm" and not generation_id:
            return
        if (
            data.get("mode") == "confirm"
            and generation_id
            and data.get("generation_id") == generation_id
        ):
            return
        new_state: dict = {"mode": "confirm"}
        if generation_id:
            new_state["generation_id"] = generation_id
        write_state(new_state)


def mark_done(*, generation_id: str | None = None) -> None:
    def mutate(data: dict) -> None:
        data.clear()
        data["mode"] = "done"
        data["done_at"] = time.time()
        if generation_id:
            data["settled_generation"] = generation_id

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
        if event in ("stop", "Stop"):
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
        mark_thinking(event=event, generation_id=generation_id)
        return
    if state == "confirm":
        mark_confirm(event=event, generation_id=generation_id)
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