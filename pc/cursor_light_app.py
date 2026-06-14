"""CodingLight - Windows 桌面程序入口。"""

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

    from app_paths import APP_NAME, LEGACY_APP_NAME

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_command())
            try:
                winreg.DeleteValue(key, LEGACY_APP_NAME)
            except FileNotFoundError:
                pass
        else:
            for name in (APP_NAME, LEGACY_APP_NAME):
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass


def is_autostart_enabled() -> bool:
    import winreg

    from app_paths import APP_NAME, LEGACY_APP_NAME

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return value == autostart_command()
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, LEGACY_APP_NAME)
            return value == autostart_command()
    except OSError:
        return False


def notify_already_running() -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            "CodingLight 已在运行，请查看系统托盘。",
            "CodingLight",
            0x40,
        )


def create_tray_icon(daemon):
    from PIL import Image
    import pystray

    from app_config import load_config
    from app_paths import APP_NAME, resource_path
    from hook_source import (
        HOOK_SOURCE_CLAUDE,
        HOOK_SOURCE_CURSOR,
        get_hook_source,
        hook_source_label,
        set_hook_source,
    )
    from install_claude_hooks import check_claude_hooks_status
    from install_hooks import check_hooks_status
    from persistent_menu_icon import PersistentMenuIcon, keep_menu_open
    from port_settings_dialog import open_port_settings_dialog

    icon_path = resource_path("assets", "tray_icon.png")
    tray_image = Image.open(icon_path).convert("RGBA")

    icon = PersistentMenuIcon(
        APP_NAME,
        tray_image,
        "CodingLight",
    )

    def status_text() -> str:
        if daemon.error:
            return f"串口异常: {daemon.error}"
        if daemon.running:
            cfg = load_config()
            port = cfg.get("port") or "?"
            return f"监听中 ({port})"
        cfg = load_config()
        if not cfg.get("port"):
            return "未连接"
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

    @keep_menu_open
    def on_select_cursor(_icon, _item):
        try:
            set_hook_source(HOOK_SOURCE_CURSOR)
        except (ValueError, OSError):
            return

    @keep_menu_open
    def on_select_claude(_icon, _item):
        try:
            set_hook_source(HOOK_SOURCE_CLAUDE)
        except (ValueError, OSError):
            return

    def is_cursor_selected(_item) -> bool:
        return get_hook_source() == HOOK_SOURCE_CURSOR

    def is_claude_selected(_item) -> bool:
        return get_hook_source() == HOOK_SOURCE_CLAUDE

    def on_connection_settings(_icon, _item):
        open_port_settings_dialog(daemon, icon)

    @keep_menu_open
    def on_autostart(_icon, _item):
        enabled = is_autostart_enabled()
        set_autostart(not enabled)

    def is_autostart_checked(_item) -> bool:
        return is_autostart_enabled()

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
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("连接设置", on_connection_settings),
        pystray.MenuItem(
            "开机自启",
            on_autostart,
            checked=is_autostart_checked,
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
    except Exception:
        instance.close()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="CodingLight")
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
