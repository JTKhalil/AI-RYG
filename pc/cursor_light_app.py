"""Cursor AI 信号灯 - Windows 桌面程序入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def autostart_command() -> str:
    from app_paths import exe_path, is_frozen

    if is_frozen():
        return f'"{exe_path()}"'
    return f'"{sys.executable}" "{Path(__file__).resolve()}"'


def run_hook_mode(state: str, event: str = "") -> int:
    from hook_entry import run

    return run(state, event)


def set_autostart(enable: bool) -> None:
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    name = "CursorTrafficLight"
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enable:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


def is_autostart_enabled() -> bool:
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, "CursorTrafficLight")
            return value == autostart_command()
    except OSError:
        return False


def notify_already_running() -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            "Cursor AI 信号灯已在运行，请查看系统托盘。",
            "Cursor AI 信号灯",
            0x40,
        )


def create_tray_icon(daemon):
    import os

    from PIL import Image, ImageDraw
    import pystray

    from app_config import load_config, rescan_and_save
    from hook_source import (
        HOOK_SOURCE_CLAUDE,
        HOOK_SOURCE_CURSOR,
        get_hook_source,
        hook_source_label,
        set_hook_source,
    )
    from install_claude_hooks import check_claude_hooks_status
    from install_hooks import check_hooks_status
    from serial_ports import list_scored_ports
    from app_paths import data_dir

    def make_icon(rgb: tuple[int, int, int]):
        img = Image.new("RGB", (64, 64), rgb)
        draw = ImageDraw.Draw(img)
        draw.ellipse((8, 8, 56, 56), fill=(255, 255, 255))
        draw.ellipse((14, 14, 50, 50), fill=rgb)
        return img

    icon = pystray.Icon(
        "CursorTrafficLight",
        make_icon((255, 193, 7)),
        "Cursor AI 信号灯",
    )

    def status_text() -> str:
        if daemon.error:
            return f"串口异常: {daemon.error}"
        if daemon.running:
            cfg = load_config()
            return f"监听中 ({cfg.get('port', '?')})"
        return "已停止"

    def listener_status_text() -> str:
        source = get_hook_source()
        if source == HOOK_SOURCE_CURSOR:
            status = check_hooks_status()
        else:
            status = check_claude_hooks_status()
        name = hook_source_label(source)
        if status.ok:
            return f"监听源: {name}（已就绪）"
        return f"监听源: {name}（{status.detail}）"

    def on_select_cursor(_icon, _item):
        try:
            set_hook_source(HOOK_SOURCE_CURSOR)
            status = check_hooks_status()
        except (ValueError, OSError) as exc:
            icon.notify("Cursor Hooks 失败", str(exc))
            return
        if hasattr(icon, "update_menu"):
            icon.update_menu()
        icon.notify(
            "监听 Cursor",
            f"Hooks 已写入\n{status.detail}\n请重启 Cursor 后生效",
        )

    def on_select_claude(_icon, _item):
        try:
            set_hook_source(HOOK_SOURCE_CLAUDE)
            status = check_claude_hooks_status()
        except (ValueError, OSError) as exc:
            icon.notify("Claude Hooks 失败", str(exc))
            return
        if hasattr(icon, "update_menu"):
            icon.update_menu()
        icon.notify(
            "监听 Claude Code",
            f"Hooks 已写入\n{status.detail}\n新开 Claude 会话后生效",
        )

    def is_cursor_selected(_item) -> bool:
        return get_hook_source() == HOOK_SOURCE_CURSOR

    def is_claude_selected(_item) -> bool:
        return get_hook_source() == HOOK_SOURCE_CLAUDE

    def on_open_config(_icon, _item):
        os.startfile(str(data_dir()))

    def on_rescan_port(_icon, _item):
        cfg = rescan_and_save()
        if cfg is None:
            icon.notify("串口", "未检测到可用串口")
            return
        daemon.stop()
        daemon.start()
        ports = list_scored_ports()
        detail = ports[0].label if ports else cfg.get("port", "?")
        icon.notify("串口", f"已切换到 {detail}")

    def on_restart_serial(_icon, _item):
        daemon.stop()
        daemon.start()
        icon.notify("串口", "已重新连接")

    def on_autostart(_icon, _item):
        enabled = is_autostart_enabled()
        set_autostart(not enabled)
        icon.notify("开机自启", "已开启" if not enabled else "已关闭")

    def on_quit(_icon, _item):
        daemon.stop()
        icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem(lambda text: status_text(), None, enabled=False),
        pystray.MenuItem(lambda text: listener_status_text(), None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "监听 Cursor",
            on_select_cursor,
            checked=is_cursor_selected,
        ),
        pystray.MenuItem(
            "监听 Claude Code",
            on_select_claude,
            checked=is_claude_selected,
        ),
        pystray.MenuItem("重新扫描串口", on_rescan_port),
        pystray.MenuItem("重新连接串口", on_restart_serial),
        pystray.MenuItem("打开配置目录", on_open_config),
        pystray.MenuItem(
            lambda text: "关闭开机自启" if is_autostart_enabled() else "开启开机自启",
            on_autostart,
        ),
        pystray.MenuItem("退出", on_quit),
    )
    return icon


def run_gui() -> int:
    from app_config import ensure_config
    from hook_source import apply_hook_source, get_hook_source
    from light_daemon import LightDaemon
    from single_instance import SingleInstance

    try:
        instance = SingleInstance()
    except RuntimeError:
        notify_already_running()
        return 0

    try:
        ensure_config()
        apply_hook_source(get_hook_source())

        daemon = LightDaemon()
        daemon.start()
        icon = create_tray_icon(daemon)
        icon.run()
        daemon.stop()
        return 0
    finally:
        instance.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Cursor AI 信号灯")
    parser.add_argument("--hook", choices=["thinking", "confirm", "done", "error", "off"])
    parser.add_argument("--event", default="", help="Cursor/Claude Hook 事件名")
    parser.add_argument("--install-hooks", action="store_true")
    parser.add_argument("--install-claude-hooks", action="store_true")
    args = parser.parse_args()

    if args.hook:
        return run_hook_mode(args.hook, args.event)
    if args.install_hooks:
        from hook_source import HOOK_SOURCE_CURSOR, set_hook_source

        set_hook_source(HOOK_SOURCE_CURSOR)
        print("已切换为监听 Cursor")
        return 0
    if args.install_claude_hooks:
        from hook_source import HOOK_SOURCE_CLAUDE, set_hook_source

        set_hook_source(HOOK_SOURCE_CLAUDE)
        print("已切换为监听 Claude Code")
        return 0

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
