"""读取 Claude Code ~/.claude/sessions/*.json 会话状态（working / idle）。"""

from __future__ import annotations

import json
from pathlib import Path

SESSIONS_DIR = Path.home() / ".claude" / "sessions"

WORKING_STATUSES = frozenset({"working", "active", "running", "busy"})
IDLE_STATUSES = frozenset({"idle", "stopped", "waiting"})
BLOCKED_STATUSES = frozenset(
    {
        "waiting_for_permission",
        "waiting_for_input",
        "permission",
        "input_required",
        "blocked",
    }
)


def find_session(*, session_id: str | None = None, cwd: str | None = None) -> dict | None:
    if not SESSIONS_DIR.is_dir():
        return None
    candidates: list[tuple[int, dict]] = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if session_id and data.get("sessionId") != session_id:
            continue
        if cwd and data.get("cwd") != cwd:
            continue
        updated = int(data.get("statusUpdatedAt") or data.get("updatedAt") or 0)
        candidates.append((updated, data))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def snapshot_session_baseline(state: dict) -> None:
    session = find_session(session_id=state.get("session_id"), cwd=state.get("cwd"))
    if not session:
        return
    state["thinking_session_status"] = session.get("status")
    state["thinking_session_baseline_at"] = int(
        session.get("statusUpdatedAt") or session.get("updatedAt") or 0
    )


def check_session_stopped(state: dict, *, prev_status: str | None = None) -> tuple[bool, str | None]:
    """Claude 会话从 working 回到 idle，或 idle 期间 statusUpdatedAt 推进（含 Esc 取消）。"""
    import time

    started = float(state.get("thinking_started_at") or 0)
    if time.time() - started < 1.5:
        return False, prev_status

    session = find_session(session_id=state.get("session_id"), cwd=state.get("cwd"))
    if not session:
        return False, prev_status

    status = str(session.get("status") or "")
    updated = int(session.get("statusUpdatedAt") or session.get("updatedAt") or 0)
    baseline = int(state.get("thinking_session_baseline_at") or 0)

    if status in BLOCKED_STATUSES:
        return False, status

    if status not in IDLE_STATUSES:
        return False, status

    if prev_status in WORKING_STATUSES:
        return True, status

    if updated > baseline:
        return True, status

    return False, status
