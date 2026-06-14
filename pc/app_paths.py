"""应用路径：开发模式与 PyInstaller 打包后通用。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "CodingLight"
APP_VERSION = "1.0.0"
APP_PUBLISHER = "CodingLight"
GITHUB_REPO_OWNER = "JTKhalil"
GITHUB_REPO = "AI-RYG"
SETUP_ASSET_NAME = "CodingLightSetup.exe"
HOOK_DIR_NAME = "CodingLightHook"
HOOK_EXE_NAME = "CodingLightHook.exe"
UNINSTALL_EXE_NAME = "CodingLightUninstall.exe"
UNINSTALL_REG_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\CodingLight"
LEGACY_APP_NAME = "CursorTrafficLight"
LEGACY_HOOK_DIR_NAME = "CursorTrafficLightHook"
LEGACY_HOOK_EXE_NAME = "CursorTrafficLightHook.exe"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def exe_path() -> Path:
    return Path(sys.executable).resolve()


def deployed_hook_exe_path() -> Path | None:
    """已部署的 Hook exe（Program Files / LocalAppData）。"""
    for root in install_roots():
        for hook_folder, hook_exe in (
            (HOOK_DIR_NAME, HOOK_EXE_NAME),
            (LEGACY_HOOK_DIR_NAME, LEGACY_HOOK_EXE_NAME),
        ):
            candidate = root / hook_folder / hook_exe
            if candidate.exists():
                return candidate
    return None


def install_roots() -> list[Path]:
    roots: list[Path] = []
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        roots.append(Path(program_files) / APP_NAME)
        roots.append(Path(program_files) / LEGACY_APP_NAME)
    local_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    roots.append(local_root / APP_NAME)
    roots.append(local_root / LEGACY_APP_NAME)
    return roots


def hook_exe_path() -> Path:
    if is_frozen():
        onedir = app_dir() / HOOK_DIR_NAME / HOOK_EXE_NAME
        if onedir.exists():
            return onedir
        legacy = app_dir() / LEGACY_HOOK_DIR_NAME / LEGACY_HOOK_EXE_NAME
        if legacy.exists():
            return legacy
        return app_dir() / HOOK_EXE_NAME
    deployed = deployed_hook_exe_path()
    if deployed is not None:
        return deployed
    return Path(__file__).resolve().parent / "hook_entry.py"


def app_dir() -> Path:
    if is_frozen():
        return exe_path().parent
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    """打包资源路径（图标等）。"""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", app_dir()))
    else:
        base = app_dir()
    return base.joinpath(*parts)


def data_dir() -> Path:
    path = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def state_path() -> Path:
    return data_dir() / "light_state.json"


def lock_path() -> Path:
    return data_dir() / "light_state.lock"


def log_path() -> Path:
    return data_dir() / "app.log"


def pid_path() -> Path:
    return data_dir() / "daemon.pid"


def update_check_cache_path() -> Path:
    return data_dir() / "update_check.json"
