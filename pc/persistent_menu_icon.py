"""Windows 托盘菜单：切换类设置项点击后不自动关闭。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from pystray import Menu
from pystray._win32 import Icon as Win32Icon
from pystray._util import win32


def keep_menu_open(func):
    """标记菜单项：执行后保持菜单展开。"""
    func._keep_menu_open = True
    return func


def _item_keep_open(item) -> bool:
    if item is Menu.SEPARATOR:
        return False
    action = item._action
    if isinstance(action, Menu) or action is None:
        return False
    return bool(getattr(action, "_keep_menu_open", False))


class PersistentMenuIcon(Win32Icon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._keep_open_flags: list[bool] = []

    def _update_menu(self) -> None:
        super()._update_menu()
        self._keep_open_flags = [_item_keep_open(item) for item in self.menu]

    def _on_notify(self, wparam, lparam) -> None:
        if lparam == win32.WM_LBUTTONUP:
            self()
            return

        if not (self._menu_handle and lparam == win32.WM_RBUTTONUP):
            return

        while True:
            win32.SetForegroundWindow(self._hwnd)

            point = wintypes.POINT()
            win32.GetCursorPos(ctypes.byref(point))

            hmenu, callbacks = self._menu_handle
            index = win32.TrackPopupMenuEx(
                hmenu,
                win32.TPM_RIGHTALIGN
                | win32.TPM_BOTTOMALIGN
                | win32.TPM_RETURNCMD,
                point.x,
                point.y,
                self._menu_hwnd,
                None,
            )

            if index <= 0:
                break

            try:
                callbacks[index - 1](self)
            except Exception:
                self._log.error(
                    "An error occurred when calling menu handler",
                    exc_info=True,
                )
                break

            menu_index = index - 1
            if menu_index >= len(self._keep_open_flags):
                break
            if not self._keep_open_flags[menu_index]:
                break

            win32.PostMessage(self._menu_hwnd, win32.WM_NULL, 0, 0)
