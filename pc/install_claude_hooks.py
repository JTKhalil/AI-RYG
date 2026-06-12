"""安装 Claude Code Hooks，与 Cursor Hooks 共用同一信号灯程序。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from install_hooks import HookStatus, _is_our_hook_command, _normalize_cmd, hook_command

# event -> (light state, 是否为工具事件需 matcher "*")
CLAUDE_HOOK_MAP: dict[str, tuple[str, bool]] = {
    "SessionStart": ("off", False),
    "UserPromptSubmit": ("thinking", False),
    "PreToolUse": ("thinking", True),
    "PostToolUse": ("thinking", True),
    "PostToolBatch": ("thinking", False),
    "SubagentStart": ("thinking", False),
    "PreCompact": ("thinking", False),
    "PostToolUseFailure": ("thinking", True),
    "StopFailure": ("error", False),
    "Stop": ("done", False),
    "SessionEnd": ("off", False),
}


def settings_file_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


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
    return merged


def _load_settings() -> dict:
    path = settings_file_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 Claude 配置: {path}") from exc


def check_claude_hooks_status() -> HookStatus:
    path = settings_file_path()
    expected = build_claude_hooks()

    if not path.exists():
        return HookStatus(
            ok=False,
            label="Claude Hooks: 未安装",
            detail="未找到 ~/.claude/settings.json",
        )

    try:
        existing = _load_settings()
    except ValueError as exc:
        return HookStatus(
            ok=False,
            label="Claude Hooks: 配置损坏",
            detail=str(exc),
        )

    installed = existing.get("hooks", {})
    matched = 0
    outdated = 0
    missing = 0

    for event, desired_groups in expected.items():
        desired_handler = desired_groups[0]["hooks"][0]
        expected_cmd = _handler_command(desired_handler)
        actual_groups = installed.get(event)
        if not actual_groups:
            missing += 1
            continue

        found = False
        for group in actual_groups:
            for handler in group.get("hooks", []):
                actual_cmd = _handler_command(handler)
                if _normalize_cmd(actual_cmd) == _normalize_cmd(expected_cmd):
                    matched += 1
                    found = True
                    break
                if _is_our_hook_command(actual_cmd):
                    outdated += 1
                    found = True
                    break
            if found:
                break
        if not found:
            missing += 1

    total = len(CLAUDE_HOOK_MAP)
    if matched == total:
        return HookStatus(
            ok=True,
            label="Claude Hooks: 已安装",
            detail="全部事件已指向当前程序",
        )
    if matched > 0 or outdated > 0:
        parts = []
        if outdated:
            parts.append(f"{outdated} 项路径过期")
        if missing:
            parts.append(f"{missing} 项缺失")
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


def install_claude_hooks() -> Path:
    path = settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        settings = _load_settings() if path.exists() else {}
    except ValueError:
        settings = {}

    hooks = settings.setdefault("hooks", {})
    for event, desired_groups in build_claude_hooks().items():
        hooks[event] = merge_event_hooks(hooks.get(event), desired_groups)

    path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _remove_our_handlers_from_groups(groups: list) -> list:
    cleaned: list = []
    for group in groups:
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


def uninstall_claude_hooks() -> None:
    path = settings_file_path()
    if not path.exists():
        return
    try:
        settings = _load_settings()
    except ValueError:
        return

    hooks = settings.get("hooks", {})
    changed = False
    for event in CLAUDE_HOOK_MAP:
        groups = hooks.get(event)
        if not groups:
            continue
        cleaned = _remove_our_handlers_from_groups(groups)
        if cleaned != groups:
            changed = True
            if cleaned:
                hooks[event] = cleaned
            else:
                hooks.pop(event, None)

    if not changed:
        return

    settings["hooks"] = hooks
    path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
