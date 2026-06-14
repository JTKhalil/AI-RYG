"""串口连接设置弹窗。"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

_dialog_lock = threading.Lock()
_dialog_open = False
_dialog_root: tk.Tk | None = None


def _focus_dialog() -> None:
    global _dialog_root
    root = _dialog_root
    if root is None:
        return
    try:
        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)
        root.after(100, lambda: root.attributes("-topmost", False))
        root.focus_force()
    except tk.TclError:
        pass


def open_port_settings_dialog(daemon, icon) -> None:
    """在独立线程中打开弹窗，避免阻塞托盘菜单且确保可正常关闭。"""
    global _dialog_open

    with _dialog_lock:
        if _dialog_open:
            _focus_dialog()
            return
        _dialog_open = True

    def run() -> None:
        global _dialog_open, _dialog_root
        try:
            _show_dialog(daemon, icon)
        except Exception as exc:
            from light_daemon import log

            log(f"port settings dialog error: {exc}")
        finally:
            with _dialog_lock:
                _dialog_open = False
                _dialog_root = None

    threading.Thread(target=run, daemon=True, name="port-settings-dialog").start()


def _active_port(daemon) -> str:
    from app_config import load_config_raw

    port = load_config_raw().get("port", "")
    if port and daemon.running:
        return port
    return ""


def _show_dialog(daemon, icon) -> None:
    global _dialog_root

    from app_config import clear_port, set_port
    from serial_ports import list_all_ports

    root = tk.Tk()
    with _dialog_lock:
        _dialog_root = root
    root.title("连接设置")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=12)
    frame.grid(row=0, column=0, sticky="nsew")

    status_var = tk.StringVar()

    def update_status() -> None:
        active = _active_port(daemon)
        if active:
            status_var.set(f"当前连接: {active}")
        elif daemon.error:
            status_var.set(f"未连接（{daemon.error}）")
        else:
            status_var.set("当前未连接")

    update_status()
    ttk.Label(frame, textvariable=status_var).grid(row=0, column=0, sticky="w", pady=(0, 8))

    list_host = ttk.Frame(frame)
    list_host.grid(row=1, column=0, sticky="nsew")

    canvas = tk.Canvas(list_host, width=420, height=240, highlightthickness=0)
    scrollbar = ttk.Scrollbar(list_host, orient="vertical", command=canvas.yview)
    rows_frame = ttk.Frame(canvas)

    rows_frame.bind(
        "<Configure>",
        lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    canvas.create_window((0, 0), window=rows_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    hint = ttk.Label(frame, text="同一时间只能连接一个串口", foreground="#666666")
    hint.grid(row=2, column=0, sticky="w", pady=(8, 0))

    busy = {"value": False}
    row_buttons: dict[str, ttk.Button] = {}

    def set_busy(value: bool) -> None:
        busy["value"] = value
        state = "disabled" if value else "normal"
        for btn in row_buttons.values():
            btn.configure(state=state)
        close_btn.configure(state=state)

    def refresh_rows() -> None:
        for child in rows_frame.winfo_children():
            child.destroy()
        row_buttons.clear()

        ports = list_all_ports()
        active = _active_port(daemon)

        if not ports:
            ttk.Label(rows_frame, text="未检测到可用串口").grid(
                row=0, column=0, sticky="w", pady=4
            )
            update_status()
            return

        for index, port in enumerate(ports):
            row = ttk.Frame(rows_frame)
            row.grid(row=index, column=0, sticky="ew", pady=3)
            rows_frame.columnconfigure(0, weight=1)

            label = port.label
            if port.device == active:
                label = f"● {label}"
            ttk.Label(row, text=label, width=42).pack(side="left", padx=(0, 8))

            if port.device == active:
                btn = ttk.Button(
                    row,
                    text="断开",
                    width=8,
                    command=lambda p=port.device: disconnect_port(p),
                )
            else:
                btn = ttk.Button(
                    row,
                    text="连接",
                    width=8,
                    command=lambda p=port.device: connect_port(p),
                )
            btn.pack(side="right")
            row_buttons[port.device] = btn

        update_status()

    def refresh_menu() -> None:
        if icon is not None and hasattr(icon, "update_menu"):
            icon.update_menu()

    def connect_port(port: str) -> None:
        if busy["value"] or port == _active_port(daemon):
            return
        set_busy(True)

        def work() -> None:
            try:
                if daemon.running:
                    daemon.stop()
                set_port(port)
                daemon.start()
                root.after(0, lambda: (refresh_rows(), refresh_menu()))
            finally:
                root.after(0, lambda: set_busy(False))

        threading.Thread(target=work, daemon=True).start()

    def disconnect_port(port: str) -> None:
        if busy["value"] or port != _active_port(daemon):
            return
        set_busy(True)

        def work() -> None:
            try:
                daemon.stop()
                clear_port()
                root.after(0, lambda: (refresh_rows(), refresh_menu()))
            finally:
                root.after(0, lambda: set_busy(False))

        threading.Thread(target=work, daemon=True).start()

    def on_close() -> None:
        root.quit()
        root.destroy()

    btn_row = ttk.Frame(frame)
    btn_row.grid(row=3, column=0, sticky="e", pady=(12, 0))
    close_btn = ttk.Button(btn_row, text="关闭", command=on_close, width=10)
    close_btn.pack(side="right")

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.bind("<Escape>", lambda _event: on_close())

    refresh_rows()

    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 2
    root.geometry(f"+{x}+{y}")

    root.mainloop()
