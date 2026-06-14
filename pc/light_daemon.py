"""串口守护：独占 COM 口，下发状态命令（灯效由固件实现），支持断线重连。"""

from __future__ import annotations

import threading
import time
from datetime import datetime

import serial

from app_config import load_config, rescan_and_save
from app_paths import log_path, pid_path
from light_ipc import start_server, stop_server
from confirm_transcript import (
    INTERRUPT_POLL_SEC,
    check_user_interrupt,
    is_awaiting_tool_permission,
)
from claude_session import check_session_stopped
from light_state import apply_hook, read_state, resolve_output

COMMANDS = {
    "thinking": b"Y\n",
    "confirm": b"C\n",
    "done": b"G\n",
    "error": b"R\n",
    "off": b"O\n",
}

RECONNECT_DELAY_SEC = 2.0
# busy→idle 后稍等，让 PermissionRequest / tool_use 写入 transcript
SESSION_IDLE_DEFER_SEC = 0.8


def log(msg: str) -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 1_000_000:
        backup = path.with_suffix(".log.old")
        backup.unlink(missing_ok=True)
        path.replace(backup)
    line = f"{datetime.now().isoformat(timespec='seconds')} daemon {msg}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


class LightDaemon:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ipc_thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._wake = threading.Event()
        self._last_interrupt_poll = 0.0
        self._session_status: str | None = None
        self._idle_defer_until = 0.0
        self.last_sent: str | None = None
        self.running = False
        self.error: str | None = None
        self._ser: serial.Serial | None = None

    def start(self) -> None:
        with self._start_lock:
            if self.running or (self._thread and self._thread.is_alive()):
                return
            self._stop.clear()
            self.error = None
            self._ipc_thread = start_server(self._on_ipc_notify)
            self._thread = threading.Thread(target=self._run, name="LightDaemon", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        stop_server(self._ipc_thread)
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None
        self._ipc_thread = None
        self._ser = None
        self.running = False
        pid_path().unlink(missing_ok=True)

    def _on_ipc_notify(self, state: str, payload: dict) -> None:
        if not state:
            return
        try:
            before = resolve_output()
            apply_hook(state, payload)
            after = resolve_output()
            if after != before:
                log(f"ipc {state}")
                self._idle_defer_until = 0.0
                self._wake.set()
        except Exception as exc:
            log(f"ipc error {exc}")

    def _send_target(self, ser: serial.Serial, target: str) -> None:
        if target == self.last_sent:
            return
        ser.write(COMMANDS[target])
        ser.flush()
        log(f"send {target}")
        self.last_sent = target

    def _flush_pending(self, ser: serial.Serial) -> None:
        target = resolve_output()
        with self._send_lock:
            self._send_target(ser, target)

    def _poll_thinking_interrupt(self) -> bool:
        """Claude Ctrl+C/Esc 不写 Stop Hook：轮询 transcript + ~/.claude/sessions 状态。"""
        now = time.time()
        if now - self._last_interrupt_poll < INTERRUPT_POLL_SEC:
            return False
        self._last_interrupt_poll = now

        data = read_state()
        mode = data.get("mode")
        if mode != "thinking":
            self._session_status = None
            self._idle_defer_until = 0.0
            return False

        reason = None
        target_state = None
        if check_user_interrupt(data):
            self._idle_defer_until = 0.0
            reason = "UserInterrupt"
            target_state = "done"
        else:
            stopped, status = check_session_stopped(data, prev_status=self._session_status)
            self._session_status = status
            if not stopped:
                self._idle_defer_until = 0.0
            else:
                if is_awaiting_tool_permission(data):
                    self._idle_defer_until = 0.0
                    reason = "PendingToolPermission"
                    target_state = "confirm"
                else:
                    if self._idle_defer_until == 0.0:
                        self._idle_defer_until = now + SESSION_IDLE_DEFER_SEC
                    if now < self._idle_defer_until:
                        return False
                    self._idle_defer_until = 0.0
                    if is_awaiting_tool_permission(data):
                        reason = "PendingToolPermission"
                        target_state = "confirm"
                    else:
                        reason = "SessionIdle"
                        target_state = "done"

        if not reason or not target_state:
            return False

        before = resolve_output()
        apply_hook(target_state, {"hook_event_name": reason})
        after = resolve_output()
        if after != before:
            log(f"poll {reason} -> {after}")
            self._session_status = None
        return after != before

    def _run(self) -> None:
        self.running = True
        pid_path().write_text(str(__import__("os").getpid()), encoding="utf-8")
        log("thread started")

        try:
            while not self._stop.is_set():
                cfg = load_config()
                port = cfg["port"]
                baud = int(cfg.get("baud", 115200))
                self.error = None
                log(f"connecting port={port}")

                try:
                    with serial.Serial(port, baud, timeout=0.2, write_timeout=1) as ser:
                        log(f"connected port={port}")
                        self.last_sent = None
                        self._ser = ser
                        self._flush_pending(ser)
                        while not self._stop.is_set():
                            if self._wake.wait(0.05):
                                self._wake.clear()
                                self._flush_pending(ser)
                            if self._poll_thinking_interrupt():
                                self._flush_pending(ser)
                                continue
                            target = resolve_output()
                            if target != self.last_sent:
                                with self._send_lock:
                                    self._send_target(ser, target)
                except serial.SerialException as exc:
                    self.error = str(exc)
                    log(f"serial error {exc}")
                    new_cfg = rescan_and_save()
                    if new_cfg and new_cfg.get("port") != port:
                        log(f"auto rescan switched port -> {new_cfg['port']}")
                    if self._stop.wait(RECONNECT_DELAY_SEC):
                        break
                except Exception as exc:
                    self.error = str(exc)
                    log(f"error {exc}")
                    if self._stop.wait(RECONNECT_DELAY_SEC):
                        break
        finally:
            self.running = False
            self._ser = None
            pid_path().unlink(missing_ok=True)
            log("thread stopped")
