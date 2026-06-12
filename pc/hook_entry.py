"""Hook 快速入口：仅依赖 light_state，避免加载托盘/串口等重型模块。"""

from __future__ import annotations

import json
import sys
from datetime import datetime

from app_paths import log_path
from light_ipc import send_notify
from light_state import apply_hook


def read_payload() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def log_hook(state: str, payload: dict) -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    event = payload.get("hook_event_name", "?")
    generation = payload.get("generation_id", "?")
    status = payload.get("status", "")
    extra = f" status={status}" if status else ""
    line = (
        f"{datetime.now().isoformat(timespec='seconds')} "
        f"hook {state} event={event} gen={generation}{extra}\n"
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def run(state: str, event: str = "") -> int:
    payload = read_payload()
    if event:
        payload.setdefault("hook_event_name", event)
    log_hook(state, payload)
    if send_notify(state, payload):
        return 0
    try:
        apply_hook(state, payload)
    except Exception as exc:
        print(f"[cursor-light] {exc}", file=sys.stderr)
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Cursor AI 信号灯 Hook")
    parser.add_argument("state", choices=["thinking", "confirm", "done", "error", "off"])
    parser.add_argument("--event", default="")
    args = parser.parse_args()
    return run(args.state, args.event)


if __name__ == "__main__":
    raise SystemExit(main())
