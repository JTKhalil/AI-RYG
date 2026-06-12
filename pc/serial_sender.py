"""已废弃：请使用 CursorTrafficLight.exe 或 light_state + LightDaemon。

保留此模块仅为向后兼容，直接写串口会与守护进程冲突。
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path


def send_state(state: str) -> None:
    warnings.warn(
        "serial_sender.send_state 已废弃，请运行 CursorTrafficLight.exe",
        DeprecationWarning,
        stacklevel=2,
    )
    from light_state import mark_done, mark_error, mark_off, mark_thinking

    actions = {
        "thinking": mark_thinking,
        "done": mark_done,
        "error": mark_error,
        "off": mark_off,
    }
    if state not in actions:
        raise ValueError(f"未知状态: {state}")
    actions[state]()


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print(f"用法: python {Path(__file__).name} <thinking|done|error|off>", file=sys.stderr)
        print("建议直接运行 CursorTrafficLight.exe", file=sys.stderr)
        return 1
    try:
        send_state(argv[0])
    except Exception as exc:
        print(f"失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
