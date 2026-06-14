"""检测守护进程、必要时拉起托盘程序。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def daemon_running() -> bool:
    from app_paths import pid_path

    path = pid_path()
    if not path.exists():
        return False
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        path.unlink(missing_ok=True)
        return False
    if sys.platform != "win32":
        return True
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
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


def tray_command() -> list[str]:
    from app_paths import exe_path, is_frozen

    if is_frozen():
        return [str(exe_path())]
    pc_dir = Path(__file__).resolve().parent
    return [sys.executable, str(pc_dir / "cursor_light_app.py")]


def start_tray_detached() -> None:
    if sys.platform != "win32":
        subprocess.Popen(tray_command(), cwd=str(Path(__file__).resolve().parent))
        return
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        tray_command(),
        cwd=str(Path(__file__).resolve().parent),
        creationflags=flags,
        close_fds=True,
    )


def ensure_tray_if_needed() -> None:
    """守护进程未运行时后台拉起托盘（不阻塞 Hook）。"""
    if daemon_running():
        return
    if sys.platform == "win32":
        from single_instance import _other_traffic_light_pids

        if _other_traffic_light_pids():
            return
    start_tray_detached()
