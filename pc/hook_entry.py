"""Hook 快速入口：仅依赖 light_state，避免加载托盘/串口等重型模块。"""

from __future__ import annotations

import json
import sys
from datetime import datetime

from app_paths import log_path
from confirm_transcript import (
    run_transcript_watch,
    schedule_thinking_interrupt_watch,
    schedule_transcript_watch,
)
from hook_origin import should_process_hook
from hook_source import get_hook_source
from light_ipc import send_notify
from light_state import apply_hook
from tray_launcher import ensure_tray_if_needed
from unicode_safe import ipc_payload, sanitize_obj


def read_payload() -> dict:
    try:
        if hasattr(sys.stdin, "buffer"):
            raw_bytes = sys.stdin.buffer.read()
            raw = raw_bytes.decode("utf-8-sig", errors="replace")
        else:
            raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return sanitize_obj(json.loads(raw))
    except json.JSONDecodeError:
        return {}


def log_hook(state: str, payload: dict) -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    event = payload.get("hook_event_name", "?")
    generation = payload.get("generation_id", "?")
    status = payload.get("status", "")
    ntype = payload.get("notification_type", "")
    tool = payload.get("tool_name", "")
    extra = f" status={status}" if status else ""
    if ntype:
        extra += f" ntype={ntype}"
    if tool:
        extra += f" tool={tool}"
    line = (
        f"{datetime.now().isoformat(timespec='seconds')} "
        f"hook {state} event={event} gen={generation}{extra}\n"
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def log_hook_skipped(state: str, payload: dict, active: str, origin: str, cli_event: str = "") -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    event = payload.get("hook_event_name") or cli_event or "?"
    line = (
        f"{datetime.now().isoformat(timespec='seconds')} "
        f"hook skipped state={state} event={event} "
        f"origin={origin} active={active}\n"
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def run(state: str, event: str = "") -> int:
    payload = read_payload()
    stdin_event = str(payload.get("hook_event_name") or "")

    active = get_hook_source()
    process, origin = should_process_hook(payload, active, cli_event=event)
    if not process:
        log_hook_skipped(state, payload, active, origin, event)
        return 0

    if event:
        payload.setdefault("hook_event_name", event)
    if stdin_event:
        payload["hook_event_name"] = stdin_event

    log_hook(state, payload)
    try:
        apply_hook(state, payload)
    except Exception as exc:
        print(f"[cursor-light] {exc}", file=sys.stderr)
        return 1
    event_name = payload.get("hook_event_name", event)
    if state == "confirm" and event_name == "PermissionRequest":
        schedule_transcript_watch(payload=payload)
    if state == "thinking" and event_name in ("UserPromptSubmit", "PostToolBatch"):
        schedule_thinking_interrupt_watch(payload=payload)
    try:
        if not send_notify(state, ipc_payload(payload)):
            ensure_tray_if_needed()
    except Exception as exc:
        print(f"[cursor-light] ipc: {exc}", file=sys.stderr)
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="CodingLight Hook")
    parser.add_argument(
        "state",
        choices=["thinking", "confirm", "done", "error", "off", "restore", "watch-transcript"],
    )
    parser.add_argument("--event", default="")
    parser.add_argument("--transcript", default="")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--mode",
        default="confirm",
        choices=["confirm", "thinking"],
        help="transcript 监听模式",
    )
    args = parser.parse_args()
    if args.state == "watch-transcript":
        if not args.transcript:
            return 1
        return run_transcript_watch(
            args.transcript,
            args.offset,
            watch_mode=args.mode,
        )
    return run(args.state, args.event)


if __name__ == "__main__":
    raise SystemExit(main())
