"""应用路径：开发模式与 PyInstaller 打包后通用。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "CursorTrafficLight"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def exe_path() -> Path:
    return Path(sys.executable).resolve()


def hook_exe_path() -> Path:
    if is_frozen():
        onedir = app_dir() / "CursorTrafficLightHook" / "CursorTrafficLightHook.exe"
        if onedir.exists():
            return onedir
        return app_dir() / "CursorTrafficLightHook.exe"
    return Path(__file__).resolve().parent / "hook_entry.py"


def app_dir() -> Path:
    if is_frozen():
        return exe_path().parent
    return Path(__file__).resolve().parent


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
