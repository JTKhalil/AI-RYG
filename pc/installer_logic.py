"""CodingLight 安装逻辑（安装程序与脚本共用）。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from app_paths import (
    APP_NAME,
    APP_PUBLISHER,
    APP_VERSION,
    HOOK_DIR_NAME,
    HOOK_EXE_NAME,
    LEGACY_APP_NAME,
    LEGACY_HOOK_DIR_NAME,
    LEGACY_HOOK_EXE_NAME,
    UNINSTALL_EXE_NAME,
    UNINSTALL_REG_KEY,
)


def is_admin() -> bool:
    if sys.platform != "win32":
        return True
    import ctypes

    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def relaunch_as_admin(extra_args: list[str] | None = None) -> None:
    import ctypes

    if getattr(sys, "frozen", False):
        executable = sys.executable
        params = " ".join(extra_args or [])
    else:
        executable = sys.executable
        script = Path(__file__).resolve().parent / "installer_app.py"
        parts = [f'"{script}"', *(extra_args or [])]
        params = " ".join(parts)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
    raise SystemExit(0)


def default_install_dir() -> Path:
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    return Path(program_files) / APP_NAME


def payload_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "payload"
    return Path(__file__).resolve().parent / "dist"


def _appdata_dir(name: str) -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / name


def migrate_user_data() -> None:
    new_dir = _appdata_dir(APP_NAME)
    if new_dir.exists():
        return
    for legacy in (LEGACY_APP_NAME,):
        old_dir = _appdata_dir(legacy)
        if old_dir.exists():
            shutil.copytree(old_dir, new_dir)
            return


def stop_running_apps() -> None:
    if sys.platform != "win32":
        return
    for name in (APP_NAME, LEGACY_APP_NAME, "CursorTrafficLight"):
        subprocess.run(
            ["taskkill", "/IM", f"{name}.exe", "/F"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    time.sleep(0.8)


def _copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def install_app(
    install_dir: Path,
    *,
    desktop_shortcut: bool = True,
    autostart: bool = True,
    launch_after: bool = False,
) -> Path:
    src = payload_dir()
    app_exe = src / f"{APP_NAME}.exe"
    icon_file = src / "tray_icon.ico"
    hook_src = src / HOOK_DIR_NAME

    if not app_exe.exists():
        raise FileNotFoundError(f"缺少安装包文件: {app_exe}")
    if not hook_src.exists():
        raise FileNotFoundError(f"缺少 Hook 目录: {hook_src}")

    stop_running_apps()
    migrate_user_data()

    install_dir = install_dir.resolve()
    install_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(app_exe, install_dir / f"{APP_NAME}.exe")
    if icon_file.exists():
        shutil.copy2(icon_file, install_dir / "tray_icon.ico")
    _copy_tree(hook_src, install_dir / HOOK_DIR_NAME)

    uninstall_src = src / UNINSTALL_EXE_NAME
    if uninstall_src.exists():
        shutil.copy2(uninstall_src, install_dir / UNINSTALL_EXE_NAME)

    dest_exe = install_dir / f"{APP_NAME}.exe"
    dest_icon = install_dir / "tray_icon.ico"
    dest_uninstall = install_dir / UNINSTALL_EXE_NAME

    if desktop_shortcut:
        _create_shortcut(dest_exe, install_dir, dest_icon)
    _cleanup_legacy_shortcuts()
    _set_autostart(dest_exe, enabled=autostart)
    if dest_uninstall.exists():
        register_uninstall(install_dir)

    if launch_after:
        subprocess.Popen([str(dest_exe)], cwd=str(install_dir))

    return dest_exe


def _dir_size_kb(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return max(1, total // 1024)


def register_uninstall(install_dir: Path) -> None:
    import winreg

    install_dir = install_dir.resolve()
    uninstall_exe = install_dir / UNINSTALL_EXE_NAME
    app_exe = install_dir / f"{APP_NAME}.exe"
    uninstall_cmd = f'"{uninstall_exe}"'
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_REG_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_PUBLISHER)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, uninstall_cmd)
        winreg.SetValueEx(
            key, "QuietUninstallString", 0, winreg.REG_SZ, f'{uninstall_cmd} /silent'
        )
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, f'"{app_exe}",0')
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, _dir_size_kb(install_dir))
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def unregister_uninstall() -> None:
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_REG_KEY)
    except OSError:
        pass


def read_install_dir() -> Path | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_REG_KEY) as key:
            location, _ = winreg.QueryValueEx(key, "InstallLocation")
            if location:
                return Path(location)
    except OSError:
        pass
    return None


def resolve_install_dir() -> Path:
    if getattr(sys, "frozen", False):
        parent = Path(sys.executable).resolve().parent
        if (parent / f"{APP_NAME}.exe").exists() or (parent / UNINSTALL_EXE_NAME).exists():
            return parent
    registered = read_install_dir()
    if registered and registered.exists():
        return registered
    return default_install_dir()


def uninstall_app(
    install_dir: Path | None = None,
    *,
    remove_user_data: bool = False,
) -> None:
    install_dir = (install_dir or resolve_install_dir()).resolve()
    app_exe = install_dir / f"{APP_NAME}.exe"

    stop_running_apps()
    if app_exe.exists():
        _set_autostart(app_exe, enabled=False)
    _remove_shortcut()
    _cleanup_legacy_shortcuts()
    unregister_uninstall()

    if remove_user_data:
        for name in (APP_NAME, LEGACY_APP_NAME, "CursorTrafficLight"):
            data = _appdata_dir(name)
            if data.exists():
                shutil.rmtree(data, ignore_errors=True)

    _schedule_remove_install_dir(install_dir)


def _remove_shortcut() -> None:
    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
    shortcut = desktop / f"{APP_NAME}.lnk"
    if shortcut.exists():
        shortcut.unlink()


def _running_uninstaller_path() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def _remove_install_dir_contents(install_dir: Path) -> None:
    """删除安装目录内除当前卸载程序外的所有内容。"""
    blocker = _running_uninstaller_path()
    if not install_dir.exists():
        return
    for item in install_dir.iterdir():
        try:
            if blocker and item.resolve() == blocker:
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        except OSError:
            pass


def _schedule_remove_install_dir(install_dir: Path) -> None:
    install_dir = install_dir.resolve()
    _remove_install_dir_contents(install_dir)

    target = str(install_dir).replace("'", "''")
    ps = f"""
$target = '{target}'
foreach ($null in 1..90) {{
    Start-Sleep -Seconds 2
    if (-not (Test-Path -LiteralPath $target)) {{ break }}
    Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
}}
"""

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-Command",
            ps,
        ],
        creationflags=creationflags,
        startupinfo=startupinfo,
        close_fds=True,
    )


def _create_shortcut(exe: Path, work_dir: Path, icon: Path) -> None:
    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
    shortcut = desktop / f"{APP_NAME}.lnk"
    ps = f"""
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut('{shortcut}')
$lnk.TargetPath = '{exe}'
$lnk.WorkingDirectory = '{work_dir}'
$lnk.IconLocation = '{icon},0'
$lnk.Save()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _cleanup_legacy_shortcuts() -> None:
    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
    for name in ("Cursor AI Traffic Light.lnk",):
        path = desktop / name
        if path.exists():
            path.unlink()


def _set_autostart(exe: Path, *, enabled: bool) -> None:
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        for legacy in (LEGACY_APP_NAME, "CursorTrafficLight"):
            try:
                winreg.DeleteValue(key, legacy)
            except FileNotFoundError:
                pass
