"""串口枚举与 ESP32 设备识别。"""

from __future__ import annotations

import re
from dataclasses import dataclass

VID_PID_RE = re.compile(r"VID:PID=([0-9A-F]+):([0-9A-F]+)", re.I)

# Espressif 原生 USB；常见 USB-UART 芯片
ESPRESSIF_VID = 0x303A
UART_VIDS = {0x10C4, 0x1A86, 0x0403, 0x2341}

DESC_HINTS = (
    "ESP32",
    "ESP32C3",
    "ESP32-C3",
    "ESPRESSIF",
    "JTAG/serial",
    "USB JTAG",
    "CP210",
    "CH340",
    "CH910",
    "CH343",
    "FT232",
    "FTDI",
    "SILICON LABS",
    "USB SERIAL",
    "USB-SERIAL",
)


@dataclass(frozen=True)
class PortInfo:
    device: str
    description: str
    hwid: str
    score: int

    @property
    def label(self) -> str:
        desc = self.description.strip() or "未知设备"
        return f"{self.device} — {desc}"


def parse_vid_pid(hwid: str) -> tuple[int | None, int | None]:
    match = VID_PID_RE.search(hwid or "")
    if not match:
        return None, None
    return int(match.group(1), 16), int(match.group(2), 16)


def score_port(device: str, description: str, hwid: str) -> int:
    if device.upper() == "COM1":
        return -1

    desc = (description or "").upper()
    hwid_u = (hwid or "").upper()
    vid, _pid = parse_vid_pid(hwid)
    score = 0

    if vid == ESPRESSIF_VID:
        score = max(score, 100)
    if vid in UART_VIDS:
        score = max(score, 60)

    for hint in DESC_HINTS:
        if hint in desc or hint in hwid_u:
            score = max(score, 80 if "ESP" in hint or "JTAG" in hint else 70)

    if score == 0:
        score = 10
    return score


def list_scored_ports() -> list[PortInfo]:
    try:
        from serial.tools import list_ports
    except Exception:
        return []

    items: list[PortInfo] = []
    for port in list_ports.comports():
        s = score_port(port.device, port.description or "", port.hwid or "")
        if s < 0:
            continue
        items.append(
            PortInfo(
                device=port.device,
                description=port.description or "",
                hwid=port.hwid or "",
                score=s,
            )
        )

    items.sort(key=lambda p: (p.score, p.device), reverse=True)
    return items


def detect_best_port() -> PortInfo | None:
    ports = list_scored_ports()
    return ports[0] if ports else None


def port_exists(device: str) -> bool:
    return any(p.device == device for p in list_scored_ports())
