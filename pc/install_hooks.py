"""安装 Cursor Hooks，指向本程序 exe。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from app_paths import exe_path, hook_exe_path, is_frozen

HOOK_MAP = {
    "sessionStart": "off",
    "beforeSubmitPrompt": "thinking",
    "afterAgentThought": "thinking",
    "preToolUse": "thinking",
    "postToolUse": "thinking",
    "beforeShellExecution": "thinking",
    "beforeReadFile": "thinking",
    "beforeMCPExecution": "thinking",
    "subagentStart": "thinking",
    "preCompact": "thinking",
    "postToolUseFailure": "thinking",
    "stop": "done",
    "sessionEnd": "off",
}


@dataclass(frozen=True)
class HookStatus:
    ok: bool
    label: str
    detail: str


def hooks_file_path() -> Path:
    return Path.home() / ".cursor" / "hooks.json"


def hook_command(state: str, event: str = "") -> str:
    if is_frozen():
        cmd = f'"{hook_exe_path()}" {state}'
    else:
        entry = Path(__file__).resolve().parent / "hook_entry.py"
        cmd = f'"{sys.executable}" "{entry}" {state}'
    if event:
        cmd += f" --event {event}"
    return cmd


def build_hooks() -> dict:
    hooks = {}
    for event, state in HOOK_MAP.items():
        hooks[event] = [{"command": hook_command(state, event)}]
    return {"version": 1, "hooks": hooks}


def _normalize_cmd(cmd: str) -> str:
    return cmd.strip().lower().replace("/", "\\")


def _is_our_hook_command(cmd: str) -> bool:
    norm = _normalize_cmd(cmd)
    return "--hook" in norm and (
        "cursortrafficlight.exe" in norm
        or "cursortrafficlighthook.exe" in norm
        or "cursor_light_app.py" in norm
        or "hook_entry.py" in norm
    )


def check_hooks_status() -> HookStatus:
    path = hooks_file_path()
    expected = build_hooks()["hooks"]

    if not path.exists():
        return HookStatus(
            ok=False,
            label="Cursor Hooks: 未安装",
            detail="未找到 hooks.json",
        )

    try:
        existing = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return HookStatus(
            ok=False,
            label="Cursor Hooks: 配置损坏",
            detail=str(path),
        )

    installed = existing.get("hooks", {})
    matched = 0
    outdated = 0
    missing = 0

    for event, entries in expected.items():
        expected_cmd = entries[0]["command"]
        actual_entries = installed.get(event)
        if not actual_entries:
            missing += 1
            continue
        actual_cmd = actual_entries[0].get("command", "")
        if _normalize_cmd(actual_cmd) == _normalize_cmd(expected_cmd):
            matched += 1
        elif _is_our_hook_command(actual_cmd):
            outdated += 1
        else:
            missing += 1

    total = len(HOOK_MAP)
    if matched == total:
        return HookStatus(
            ok=True,
            label="Cursor Hooks: 已安装",
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
            label="Cursor Hooks: 需更新",
            detail="，".join(parts) or "配置不完整",
        )
    return HookStatus(
        ok=False,
        label="Cursor Hooks: 未安装",
        detail="未检测到本程序的 Hook 配置",
    )


def install_hooks() -> Path:
    cursor_dir = Path.home() / ".cursor"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    hooks_file = cursor_dir / "hooks.json"
    new_hooks = build_hooks()

    if hooks_file.exists():
        try:
            existing = json.loads(hooks_file.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            existing = {"version": 1, "hooks": {}}
        if "hooks" not in existing:
            existing["hooks"] = {}
        for event, entries in new_hooks["hooks"].items():
            existing["hooks"][event] = entries
        existing["version"] = 1
        payload = existing
    else:
        payload = new_hooks

    hooks_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return hooks_file


def uninstall_cursor_hooks() -> None:
    path = hooks_file_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return

    hooks = data.get("hooks", {})
    changed = False
    for event in HOOK_MAP:
        entries = hooks.get(event)
        if not entries:
            continue
        kept = [
            entry
            for entry in entries
            if not _is_our_hook_command(entry.get("command", ""))
        ]
        if kept != entries:
            changed = True
            if kept:
                hooks[event] = kept
            else:
                hooks.pop(event, None)

    if not changed:
        return

    data["hooks"] = hooks
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
