"""CodingLight 卸载程序（可在 Windows 设置 > 应用中卸载）。"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox, ttk

from installer_logic import (
    is_admin,
    relaunch_as_admin,
    resolve_install_dir,
    uninstall_app,
)


def _is_silent(argv: list[str]) -> bool:
    flags = {arg.lower() for arg in argv}
    return "/silent" in flags or "/quiet" in flags


def main() -> int:
    if sys.platform == "win32" and not is_admin():
        relaunch_as_admin(sys.argv[1:])

    install_dir = resolve_install_dir()
    silent = _is_silent(sys.argv[1:])
    flags = {arg.lower() for arg in sys.argv[1:]}
    remove_user_data = "/keep-data" not in flags

    if not silent:
        root = tk.Tk()
        root.withdraw()
        if not messagebox.askokcancel(
            "卸载 CodingLight",
            f"确定要卸载 CodingLight 吗？\n\n安装位置:\n{install_dir}",
        ):
            root.destroy()
            return 0
        root.destroy()

    uninstall_app(install_dir, remove_user_data=remove_user_data)

    if not silent:
        info = tk.Tk()
        info.withdraw()
        messagebox.showinfo("卸载完成", "CodingLight 已从本机移除。")
        info.destroy()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
