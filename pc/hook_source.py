"""监听源互斥切换：Cursor 与 Claude 二选一。"""

from __future__ import annotations

from app_config import DEFAULT_CONFIG, load_config_raw, save_config
from install_claude_hooks import install_claude_hooks, uninstall_claude_hooks
from install_hooks import install_hooks

HOOK_SOURCE_CURSOR = "cursor"
HOOK_SOURCE_CLAUDE = "claude"
VALID_HOOK_SOURCES = {HOOK_SOURCE_CURSOR, HOOK_SOURCE_CLAUDE}


def get_hook_source(cfg: dict | None = None) -> str:
    cfg = cfg or load_config_raw()
    source = cfg.get("hook_source", HOOK_SOURCE_CURSOR)
    if source not in VALID_HOOK_SOURCES:
        return HOOK_SOURCE_CURSOR
    return source


def apply_hook_source(source: str) -> None:
    if source not in VALID_HOOK_SOURCES:
        raise ValueError(f"未知监听源: {source}")
    # 始终保留 ~/.cursor/hooks.json（含 stop），避免切源时 Cursor 丢失完成 Hook。
    # 实际是否处理由 hook_entry 按 hook_source 过滤。
    install_hooks()
    if source == HOOK_SOURCE_CURSOR:
        uninstall_claude_hooks()
    else:
        install_claude_hooks()


def refresh_active_hooks() -> str:
    """按当前配置重新安装 Hooks，不切换监听源。"""
    source = get_hook_source()
    apply_hook_source(source)
    return source


def set_hook_source(source: str) -> str:
    if source not in VALID_HOOK_SOURCES:
        raise ValueError(f"未知监听源: {source}")
    cfg = {**DEFAULT_CONFIG, **load_config_raw(), "hook_source": source}
    save_config(cfg)
    apply_hook_source(source)
    return source


def hook_source_label(source: str | None = None) -> str:
    source = source or get_hook_source()
    return "Cursor" if source == HOOK_SOURCE_CURSOR else "Claude"
