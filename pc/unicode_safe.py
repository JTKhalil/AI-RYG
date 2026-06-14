"""清洗 Hook stdin 中的非法 Unicode（孤立 surrogate 等）。"""

from __future__ import annotations

from typing import Any


def sanitize_str(value: str) -> str:
    if not value:
        return value
    return value.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


def sanitize_obj(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_str(value)
    if isinstance(value, dict):
        return {sanitize_str(k) if isinstance(k, str) else k: sanitize_obj(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_obj(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_obj(item) for item in value)
    return value


def ipc_payload(payload: dict) -> dict:
    """IPC 只传状态机需要的字段，避免大段 tool 输出触发编码问题。"""
    keys = (
        "hook_event_name",
        "generation_id",
        "status",
        "notification_type",
        "tool_name",
    )
    slim = {k: payload[k] for k in keys if k in payload}
    return sanitize_obj(slim)
