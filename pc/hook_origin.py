"""区分 Hook 调用来自 Cursor IDE 还是 Claude Code CLI。"""

from __future__ import annotations

import os
import sys

from install_claude_hooks import CLAUDE_HOOK_MAP
from install_hooks import HOOK_MAP

CURSOR_NATIVE_EVENTS = frozenset(HOOK_MAP)
CLAUDE_NATIVE_EVENTS = frozenset(CLAUDE_HOOK_MAP) | {"Notification"}


def _build_process_tree() -> tuple[dict[int, int], dict[int, str]]:
    """Windows: pid -> ppid, pid -> exe name。"""
    if sys.platform != "win32":
        return {}, {}

    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    parents: dict[int, int] = {}
    names: dict[int, str] = {}
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == -1:
        return parents, names

    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                pid = int(entry.th32ProcessID)
                parents[pid] = int(entry.th32ParentProcessID)
                names[pid] = entry.szExeFile
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return parents, names


def detect_origin_from_process_tree(max_depth: int = 8) -> str:
    """沿父进程链查找 Cursor / Claude（stdin 为空时仍可靠）。"""
    if sys.platform != "win32":
        return "unknown"

    parents, names = _build_process_tree()
    if not names:
        return "unknown"

    pid = os.getppid()
    for _ in range(max_depth):
        name = names.get(pid, "").lower()
        if "cursor" in name:
            return "cursor"
        if "claude" in name:
            return "claude"
        pid = parents.get(pid, 0)
        if pid <= 0:
            break
    return "unknown"


def detect_hook_origin(payload: dict) -> str:
    """返回 'cursor'、'claude' 或 'unknown'。"""
    if payload.get("cursor_version") or payload.get("composer_mode"):
        return "cursor"
    if payload.get("conversation_id"):
        return "cursor"
    if payload.get("workspace_roots"):
        return "cursor"
    if payload.get("tool_use_id"):
        return "cursor"

    event = str(payload.get("hook_event_name") or "")
    if event in CURSOR_NATIVE_EVENTS:
        return "cursor"
    if event in CLAUDE_NATIVE_EVENTS:
        return "claude"

    if payload.get("entrypoint") == "cli":
        return "claude"

    transcript = str(payload.get("transcript_path") or "").replace("/", "\\").lower()
    if "\\.cursor\\" in transcript or "agent-transcripts" in transcript:
        return "cursor"
    if "\\.claude\\" in transcript:
        return "claude"

    return detect_origin_from_process_tree()


def should_process_hook(
    payload: dict,
    active_source: str,
    *,
    cli_event: str = "",
) -> tuple[bool, str]:
    """当前配置的监听源是否应处理此 Hook。"""
    internal_events = {"TranscriptDenied", "TranscriptAllowed", "ConfirmTimeout"}
    event = str(payload.get("hook_event_name") or cli_event or "")
    if event in internal_events:
        return True, "internal"

    origin = detect_hook_origin(payload)
    if payload.get("cursor_version") or payload.get("conversation_id"):
        origin = "cursor"

    if active_source == "claude":
        if origin == "claude" or origin == "internal":
            return True, origin
        if origin == "cursor":
            return False, origin
        tree = detect_origin_from_process_tree()
        if tree == "cursor":
            return False, "cursor"
        if tree == "claude":
            return True, "claude"
        return False, "unknown-blocked"

    if active_source == "cursor":
        if origin == "claude":
            return False, origin
        if origin in ("cursor", "internal"):
            return True, origin
        if cli_event == "stop" or event == "stop":
            return True, "cursor-stop"
        tree = detect_origin_from_process_tree()
        if tree == "claude":
            return False, "claude"
        if tree == "cursor":
            return True, "cursor"
        return True, "unknown-assumed-cursor"

    if origin == "unknown":
        tree = detect_origin_from_process_tree()
        if tree == "cursor":
            return True, "cursor"
        return active_source == "cursor", "unknown-assumed-cursor"
    return origin == active_source, origin
