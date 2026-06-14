"""安装 Claude Code Hooks，与 Cursor Hooks 共用同一信号灯程序。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from install_hooks import (
    HookStatus,
    _is_our_hook_command,
    hook_command,
    hook_commands_match,
)

# event -> (light state, 是否为工具事件需 matcher "*")
CLAUDE_HOOK_MAP: dict[str, tuple[str, bool]] = {
    "SessionStart": ("off", False),
    "UserPromptSubmit": ("thinking", False),
    "PreToolUse": ("thinking", True),
    "PermissionRequest": ("confirm", False),
    "PostToolUse": ("thinking", True),
    "PostToolBatch": ("thinking", False),
    "SubagentStart": ("thinking", False),
    "PreCompact": ("thinking", False),
    "PostToolUseFailure": ("thinking", True),
    "PermissionDenied": ("done", False),
    "StopFailure": ("error", False),
    "Stop": ("done", False),
    "SessionEnd": ("off", False),
}

LEGACY_CLAUDE_EVENTS = {"MessageDisplay"}


def settings_file_path() -> Path:
    """Claude Code 会读取；Cursor IDE 不加载用户级 settings.local.json。"""
    return Path.home() / ".claude" / "settings.local.json"


def shared_settings_file_path() -> Path:
    """Cursor 与 Claude 都会读 — 仅用于卸载遗留 Hook。"""
    return Path.home() / ".claude" / "settings.json"


def claude_settings_paths() -> tuple[Path, Path]:
    return settings_file_path(), shared_settings_file_path()


def _handler_for_state(state: str, event: str) -> dict:
    return {"type": "command", "command": hook_command(state, event)}


def _event_groups(event: str, state: str, needs_tool_matcher: bool) -> list[dict]:
    handler = _handler_for_state(state, event)
    if needs_tool_matcher:
        return [{"matcher": "*", "hooks": [handler]}]
    return [{"hooks": [handler]}]


def build_claude_hooks() -> dict:
    hooks: dict[str, list] = {}
    for event, (state, needs_matcher) in CLAUDE_HOOK_MAP.items():
        hooks[event] = _event_groups(event, state, needs_matcher)
    hooks["Notification"] = [
        {
            "matcher": "idle_prompt",
            "hooks": [_handler_for_state("restore", "Notification")],
        },
        {
            "matcher": "permission_prompt",
            "hooks": [_handler_for_state("restore", "Notification")],
        },
    ]
    return hooks


def _handler_command(handler: dict) -> str:
    cmd = handler.get("command", "")
    args = handler.get("args") or []
    if args:
        return " ".join([cmd, *args])
    return cmd


def _upsert_handler_in_group(group: dict, handler: dict) -> None:
    hooks = group.setdefault("hooks", [])
    for index, existing in enumerate(hooks):
        if _is_our_hook_command(_handler_command(existing)):
            hooks[index] = handler
            return
    hooks.append(handler)


def merge_event_hooks(existing: list | None, desired: list) -> list:
    merged = copy.deepcopy(existing or [])
    for desired_group in desired:
        desired_handler = desired_group["hooks"][0]
        if "matcher" in desired_group:
            matcher = desired_group["matcher"]
            matched_group = next(
                (g for g in merged if g.get("matcher") == matcher),
                None,
            )
            if matched_group is None:
                merged.append(copy.deepcopy(desired_group))
            else:
                _upsert_handler_in_group(matched_group, desired_handler)
        else:
            plain_group = next(
                (g for g in merged if "matcher" not in g and "hooks" in g),
                None,
            )
            if plain_group is None:
                merged.append(copy.deepcopy(desired_group))
            else:
                _upsert_handler_in_group(plain_group, desired_handler)
    return _dedupe_our_handlers(merged)


def _dedupe_our_handlers(groups: list) -> list:
    cleaned: list = []
    for group in groups:
        handlers = group.get("hooks", [])
        new_handlers = []
        kept_ours = False
        for handler in handlers:
            cmd = _handler_command(handler)
            if _is_our_hook_command(cmd):
                if kept_ours:
                    continue
                kept_ours = True
            new_handlers.append(handler)
        if not new_handlers:
            continue
        new_group = copy.deepcopy(group)
        new_group["hooks"] = new_handlers
        cleaned.append(new_group)
    return cleaned


def _load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 Claude 配置: {path}") from exc


def _save_settings(path: Path, settings: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _count_expected_groups(expected: dict) -> int:
    return sum(len(groups) for groups in expected.values())


def _find_group_handler_status(
    actual_groups: list,
    desired_group: dict,
    expected_cmd: str,
) -> str | None:
    matcher = desired_group.get("matcher")
    for group in actual_groups:
        if matcher is not None and group.get("matcher") != matcher:
            continue
        if matcher is None and "matcher" in group:
            continue
        for handler in group.get("hooks", []):
            actual_cmd = _handler_command(handler)
            if hook_commands_match(actual_cmd, expected_cmd):
                return "matched"
            if _is_our_hook_command(actual_cmd):
                return "outdated"
    return None


def _settings_has_our_hooks(settings: dict) -> bool:
    for groups in settings.get("hooks", {}).values():
        for group in groups or []:
            for handler in group.get("hooks", []):
                if _is_our_hook_command(_handler_command(handler)):
                    return True
    return False


def check_claude_hooks_status() -> HookStatus:
    path = settings_file_path()
    expected = build_claude_hooks()

    if not path.exists():
        return HookStatus(
            ok=False,
            label="Claude Hooks: 未安装",
            detail="未找到 ~/.claude/settings.local.json",
        )

    try:
        existing = _load_settings(path)
    except ValueError as exc:
        return HookStatus(
            ok=False,
            label="Claude Hooks: 配置损坏",
            detail=str(exc),
        )

    legacy_leak = False
    shared = shared_settings_file_path()
    if shared.exists():
        try:
            legacy_leak = _settings_has_our_hooks(_load_settings(shared))
        except ValueError:
            legacy_leak = False

    installed = existing.get("hooks", {})
    matched = 0
    outdated = 0
    missing = 0

    for event, desired_groups in expected.items():
        actual_groups = installed.get(event)
        if not actual_groups:
            missing += len(desired_groups)
            continue

        for desired_group in desired_groups:
            expected_cmd = _handler_command(desired_group["hooks"][0])
            result = _find_group_handler_status(
                actual_groups,
                desired_group,
                expected_cmd,
            )
            if result == "matched":
                matched += 1
            elif result == "outdated":
                outdated += 1
            else:
                missing += 1

    total = _count_expected_groups(expected)
    if matched == total and not legacy_leak:
        return HookStatus(
            ok=True,
            label="Claude Hooks: 已安装",
            detail="全部事件已指向当前程序",
        )
    if matched == total and legacy_leak:
        return HookStatus(
            ok=False,
            label="Claude Hooks: 需清理",
            detail="settings.json 仍有遗留 Hook，请重新选择监听源",
        )
    if matched > 0 or outdated > 0:
        parts = []
        if outdated:
            parts.append(f"{outdated} 项路径过期")
        if missing:
            parts.append(f"{missing} 项缺失")
        if legacy_leak:
            parts.append("settings.json 有遗留")
        return HookStatus(
            ok=False,
            label="Claude Hooks: 需更新",
            detail="，".join(parts) or "配置不完整",
        )
    return HookStatus(
        ok=False,
        label="Claude Hooks: 未安装",
        detail="未检测到本程序的 Hook 配置",
    )


def _strip_our_handlers_from_groups(groups: list | None) -> list:
    cleaned: list = []
    for group in groups or []:
        handlers = [
            handler
            for handler in group.get("hooks", [])
            if not _is_our_hook_command(_handler_command(handler))
        ]
        if not handlers:
            continue
        new_group = copy.deepcopy(group)
        new_group["hooks"] = handlers
        cleaned.append(new_group)
    return cleaned


def _strip_our_hooks_from_settings(settings: dict) -> bool:
    hooks = settings.get("hooks", {})
    changed = False
    claude_events = set(CLAUDE_HOOK_MAP) | {"Notification"} | LEGACY_CLAUDE_EVENTS
    for event in claude_events:
        groups = hooks.get(event)
        if not groups:
            continue
        cleaned = _strip_our_handlers_from_groups(groups)
        if cleaned != groups:
            changed = True
            if cleaned:
                hooks[event] = cleaned
            else:
                hooks.pop(event, None)
    if changed:
        settings["hooks"] = hooks
    return changed


def purge_shared_claude_hooks() -> bool:
    """从 settings.json 移除本程序 Hook（避免 Cursor 误触发）。"""
    path = shared_settings_file_path()
    if not path.exists():
        return False
    try:
        settings = _load_settings(path)
    except ValueError:
        return False
    if not _strip_our_hooks_from_settings(settings):
        return False
    _save_settings(path, settings)
    return True


def _install_into_settings(settings: dict) -> None:
    hooks = settings.setdefault("hooks", {})
    desired_all = build_claude_hooks()
    for event, desired_groups in desired_all.items():
        cleaned = _strip_our_handlers_from_groups(hooks.get(event))
        hooks[event] = merge_event_hooks(cleaned, desired_groups)

    for event in LEGACY_CLAUDE_EVENTS:
        groups = hooks.get(event)
        if not groups:
            continue
        cleaned = _strip_our_handlers_from_groups(groups)
        if cleaned:
            hooks[event] = cleaned
        else:
            hooks.pop(event, None)


def install_claude_hooks() -> Path:
    purge_shared_claude_hooks()

    path = settings_file_path()
    try:
        settings = _load_settings(path) if path.exists() else {}
    except ValueError:
        settings = {}

    _install_into_settings(settings)
    _save_settings(path, settings)
    return path


def uninstall_claude_hooks() -> None:
    changed_any = False
    for path in claude_settings_paths():
        if not path.exists():
            continue
        try:
            settings = _load_settings(path)
        except ValueError:
            continue
        if _strip_our_hooks_from_settings(settings):
            changed_any = True
            _save_settings(path, settings)
    if not changed_any:
        return
