"""CodingLight 图形化安装程序。"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from installer_logic import (
    default_install_dir,
    install_app,
    is_admin,
    relaunch_as_admin,
)
from app_paths import APP_NAME


class InstallerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("CodingLight 安装程序")
        self.root.resizable(False, False)

        frame = ttk.Frame(root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="CodingLight", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(
            frame,
            text="AI 编程状态信号灯 — 安装到本机",
            foreground="#666666",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))

        ttk.Label(frame, text="安装位置").grid(row=2, column=0, sticky="w")
        self.path_var = tk.StringVar(value=str(default_install_dir()))
        path_entry = ttk.Entry(frame, textvariable=self.path_var, width=52)
        path_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Button(frame, text="浏览…", command=self._browse).grid(
            row=3, column=2, padx=(8, 0), pady=(4, 0)
        )

        self.shortcut_var = tk.BooleanVar(value=True)
        self.autostart_var = tk.BooleanVar(value=True)
        self.launch_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="创建桌面快捷方式", variable=self.shortcut_var).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(12, 0)
        )
        ttk.Checkbutton(frame, text="开机自动启动", variable=self.autostart_var).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(4, 0)
        )
        ttk.Checkbutton(frame, text="安装完成后立即运行", variable=self.launch_var).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(4, 0)
        )

        self.status_var = tk.StringVar(value="准备安装（需要管理员权限）")
        ttk.Label(frame, textvariable=self.status_var, foreground="#444444").grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(14, 8)
        )

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=8, column=0, columnspan=3, sticky="e")
        ttk.Button(btn_row, text="退出", command=self.root.destroy).pack(side="right")
        self.install_btn = ttk.Button(btn_row, text="安装", command=self._install)
        self.install_btn.pack(side="right", padx=(0, 8))

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"+{x}+{y}")

    def _browse(self) -> None:
        selected = filedialog.askdirectory(
            title="选择安装目录",
            initialdir=str(default_install_dir().parent),
        )
        if selected:
            path = Path(selected)
            if path.name.lower() != APP_NAME.lower():
                path = path / APP_NAME
            self.path_var.set(str(path))

    def _install(self) -> None:
        install_dir = Path(self.path_var.get().strip())
        if not install_dir.name:
            messagebox.showerror("安装失败", "请填写安装目录。")
            return
        if install_dir.name.lower() != APP_NAME.lower():
            install_dir = install_dir / APP_NAME

        self.install_btn.configure(state="disabled")
        self.status_var.set("正在安装…")
        self.root.update_idletasks()

        try:
            dest = install_app(
                install_dir,
                desktop_shortcut=self.shortcut_var.get(),
                autostart=self.autostart_var.get(),
                launch_after=self.launch_var.get(),
            )
        except Exception as exc:
            self.install_btn.configure(state="normal")
            self.status_var.set("安装失败")
            messagebox.showerror("安装失败", str(exc))
            return

        self.status_var.set(f"安装完成: {dest}")
        self.root.destroy()


def main() -> int:
    if sys.platform == "win32" and not is_admin():
        relaunch_as_admin()
    root = tk.Tk()
    InstallerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
