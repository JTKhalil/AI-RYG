"""通过守护进程测试灯光：黄 -> 绿 -> 红 -> 灭。"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from app_paths import exe_path, is_frozen, log_path, pid_path
from light_state import mark_done, mark_error, mark_off, mark_thinking

SCRIPT_DIR = Path(__file__).resolve().parent


def daemon_running() -> bool:
    path = pid_path()
    if not path.exists():
        return False
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            path.unlink(missing_ok=True)
            return False
        code = ctypes.c_ulong()
        alive = (
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            and code.value == STILL_ACTIVE
        )
        ctypes.windll.kernel32.CloseHandle(handle)
        if not alive:
            path.unlink(missing_ok=True)
        return alive
    return True


def ensure_daemon() -> None:
    if daemon_running():
        return

    if is_frozen():
        cmd = [str(exe_path())]
    else:
        cmd = [sys.executable, str(SCRIPT_DIR / "cursor_light_app.py")]

    subprocess.Popen(cmd, cwd=str(SCRIPT_DIR))
    for _ in range(20):
        time.sleep(0.25)
        if daemon_running():
            return
    raise RuntimeError("守护进程启动失败，请先运行 CursorTrafficLight.exe")


def main() -> int:
    print("将依次测试：黄 -> 绿 -> 红 -> 灭（需 CursorTrafficLight 在运行）")
    try:
        ensure_daemon()
        for label, action in [
            ("黄灯 - 思考中", mark_thinking),
            ("绿灯 - 完成", mark_done),
            ("红灯 - 报错", mark_error),
            ("熄灭", mark_off),
        ]:
            print(f"-> {label}")
            action()
            time.sleep(3)
        print(f"测试完成，日志: {log_path()}")
    except KeyboardInterrupt:
        print("\n已中断")
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
