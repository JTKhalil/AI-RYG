"""Windows 单实例互斥锁。"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import ctypes
    import os
    import subprocess
    from ctypes import wintypes

    from app_paths import APP_NAME, LEGACY_APP_NAME

    _ERROR_ALREADY_EXISTS = 183
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateMutexW = _kernel32.CreateMutexW
    _CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _CreateMutexW.restype = wintypes.HANDLE

    _PROCESS_NAMES = {f"{APP_NAME}.exe".lower(), f"{LEGACY_APP_NAME}.exe".lower()}

    def _other_traffic_light_pids() -> list[int]:
        my_pid = os.getpid()
        pids: list[int] = []
        for image_name in sorted(_PROCESS_NAMES):
            try:
                out = subprocess.check_output(
                    [
                        "tasklist",
                        "/FI",
                        f"IMAGENAME eq {image_name}",
                        "/FO",
                        "CSV",
                        "/NH",
                    ],
                    text=True,
                    errors="ignore",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.CalledProcessError):
                continue
            for line in out.splitlines():
                line = line.strip()
                if not line or line.startswith('"INFO:'):
                    continue
                parts = [part.strip('"') for part in line.split('","')]
                if len(parts) < 2 or parts[0].lower() not in _PROCESS_NAMES:
                    continue
                try:
                    pid = int(parts[1])
                except ValueError:
                    continue
                if pid != my_pid:
                    pids.append(pid)
        return sorted(set(pids))

    def terminate_other_instances() -> None:
        for pid in _other_traffic_light_pids():
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )

    def count_traffic_light_processes() -> int:
        return len(_other_traffic_light_pids()) + 1

    class SingleInstance:
        name = f"Global\\{APP_NAME}Mutex"

        def __init__(self) -> None:
            terminate_other_instances()
            self._handle = _CreateMutexW(None, False, self.name)
            if not self._handle:
                raise OSError("CreateMutexW failed")
            if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
                raise RuntimeError(f"{APP_NAME} 已在运行")

        def close(self) -> None:
            if self._handle:
                _kernel32.CloseHandle(self._handle)
                self._handle = None

        def __enter__(self) -> SingleInstance:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            self.close()

else:

    def count_traffic_light_processes() -> int:
        return 1

    class SingleInstance:
        def __enter__(self) -> SingleInstance:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass
