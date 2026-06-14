"""Hook 与守护进程之间的本地 IPC，避免仅依赖状态文件轮询。"""

from __future__ import annotations

import json
import socket
import threading
from typing import Callable

IPC_HOST = "127.0.0.1"
IPC_PORT = 37521
IPC_TIMEOUT_SEC = 0.05

_stop = threading.Event()


def send_notify(state: str, payload: dict | None = None) -> bool:
    """向运行中的守护进程发送灯态；成功则 Hook 无需再写状态文件。"""
    from unicode_safe import ipc_payload, sanitize_obj

    safe_payload = sanitize_obj(ipc_payload(payload or {}))
    message = json.dumps(
        {"state": state, "payload": safe_payload},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    data = (message + "\n").encode("utf-8", errors="replace")
    try:
        with socket.create_connection(
            (IPC_HOST, IPC_PORT),
            timeout=IPC_TIMEOUT_SEC,
        ) as conn:
            conn.sendall(data)
        return True
    except OSError:
        return False


def start_server(handler: Callable[[str, dict], None]) -> threading.Thread:
    """在后台线程监听 Hook 通知。"""

    def serve() -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((IPC_HOST, IPC_PORT))
            server.listen(8)
            server.settimeout(0.5)
            while not _stop.is_set():
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with conn:
                    conn.settimeout(IPC_TIMEOUT_SEC)
                    try:
                        raw = conn.recv(8192)
                    except OSError:
                        continue
                    if not raw:
                        continue
                    try:
                        msg = json.loads(raw.decode("utf-8").strip())
                        handler(msg.get("state", ""), msg.get("payload") or {})
                    except (json.JSONDecodeError, TypeError):
                        continue
        finally:
            server.close()

    _stop.clear()
    thread = threading.Thread(target=serve, name="LightIPC", daemon=True)
    thread.start()
    return thread


def stop_server(_thread: threading.Thread | None) -> None:
    _stop.set()
