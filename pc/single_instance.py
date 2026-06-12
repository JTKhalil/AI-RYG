"""Windows 单实例互斥锁。"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _ERROR_ALREADY_EXISTS = 183
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateMutexW = _kernel32.CreateMutexW
    _CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _CreateMutexW.restype = wintypes.HANDLE

    class SingleInstance:
        name = "Global\\CursorTrafficLightMutex"

        def __init__(self) -> None:
            self._handle = _CreateMutexW(None, False, self.name)
            if not self._handle:
                raise OSError("CreateMutexW failed")
            if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
                raise RuntimeError("CursorTrafficLight 已在运行")

        def close(self) -> None:
            if self._handle:
                _kernel32.CloseHandle(self._handle)
                self._handle = None

        def __enter__(self) -> SingleInstance:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            self.close()

else:

    class SingleInstance:
        def __enter__(self) -> SingleInstance:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass
