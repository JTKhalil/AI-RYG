"""配置读写与默认 COM 口。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app_paths import config_path, data_dir
from serial_ports import detect_best_port, list_scored_ports, port_exists

DEFAULT_CONFIG = {"port": "COM14", "baud": 115200, "hook_source": "cursor"}


def detect_port() -> dict | None:
    best = detect_best_port()
    if best is None:
        return None
    return {"port": best.device, "baud": 115200}


def ensure_config() -> dict:
    path = config_path()
    if path.exists():
        with path.open(encoding="utf-8-sig") as f:
            cfg = json.load(f)
        return refresh_port_if_needed(cfg)

    legacy = Path(__file__).resolve().parent / "config.json"
    if legacy.exists():
        shutil.copy2(legacy, path)
        with path.open(encoding="utf-8-sig") as f:
            cfg = json.load(f)
        return refresh_port_if_needed(cfg)

    cfg = detect_port() or DEFAULT_CONFIG.copy()
    save_config(cfg)
    return cfg


def refresh_port_if_needed(cfg: dict) -> dict:
    """配置端口不可用或发现更高优先级 ESP32 时自动更新。"""
    current = cfg.get("port", "")
    if not current:
        return cfg
    if current and port_exists(current):
        return cfg

    detected = detect_port()
    if detected is None:
        return cfg

    merged = {**DEFAULT_CONFIG, **cfg, **detected}
    if merged.get("port") != current:
        save_config(merged)
    return merged


def rescan_and_save() -> dict | None:
    """主动扫描并写入最佳串口，返回新配置；无可用端口时返回 None。"""
    detected = detect_port()
    if detected is None:
        return None
    cfg = load_config_raw()
    merged = {**DEFAULT_CONFIG, **cfg, **detected}
    save_config(merged)
    return merged


def load_config_raw() -> dict:
    path = config_path()
    if not path.exists():
        return DEFAULT_CONFIG.copy()
    try:
        with path.open(encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()


def set_port(port: str) -> dict:
    """写入指定串口并返回完整配置。"""
    cfg = load_config_raw()
    merged = {**DEFAULT_CONFIG, **cfg, "port": port}
    save_config(merged)
    return merged


def clear_port() -> dict:
    """清除串口配置（用户主动断开）。"""
    cfg = load_config_raw()
    merged = {**DEFAULT_CONFIG, **cfg, "port": ""}
    save_config(merged)
    return merged


def save_config(cfg: dict) -> None:
    data_dir()
    config_path().write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_config() -> dict:
    return refresh_port_if_needed(load_config_raw())


def list_available_ports() -> list[str]:
    return [p.device for p in list_scored_ports()]
