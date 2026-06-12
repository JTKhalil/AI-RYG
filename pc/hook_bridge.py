"""Cursor Hook 入口（开发模式兼容）。"""

from __future__ import annotations

import sys
from pathlib import Path

VALID_STATES = {"thinking", "confirm", "done", "error", "off"}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in VALID_STATES:
        print(
            f"用法: {Path(__file__).name} <thinking|confirm|done|error|off>",
            file=sys.stderr,
        )
        return 1

    from hook_entry import read_payload, run

    payload = read_payload()
    return run(sys.argv[1], payload.get("hook_event_name", ""))


if __name__ == "__main__":
    raise SystemExit(main())
