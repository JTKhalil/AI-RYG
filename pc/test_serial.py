"""串口与固件诊断 + 灯光测试。"""

from __future__ import annotations

import sys
import time

import serial

from app_config import load_config
from app_paths import log_path
from light_state import mark_done, mark_error, mark_off, mark_thinking
from serial_ports import list_scored_ports
from tray_launcher import daemon_running, start_tray_detached


def probe_firmware(port: str, baud: int = 115200) -> tuple[bool, str]:
    """直连串口，确认 ESP32 固件是否在运行。"""
    try:
        with serial.Serial(port, baud, timeout=1.5) as ser:
            ser.reset_input_buffer()
            time.sleep(0.4)
            boot = ser.read(512).decode("utf-8", errors="replace")
            if "waiting for download" in boot.lower():
                return False, "ESP32 处于下载模式，未运行信号灯固件（请用 Arduino 烧录后按 RESET）"
            ser.write(b"Y\n")
            ser.flush()
            time.sleep(0.6)
            resp = boot + ser.read(512).decode("utf-8", errors="replace")
            if "OK:YELLOW" in resp or "Traffic Light Ready" in resp:
                return True, "固件正常"
            if resp.strip():
                return False, f"串口有数据但非本固件: {resp.strip()[:120]}"
            return False, "串口无响应：很可能未烧录 ai_traffic_light.ino 固件"
    except serial.SerialException as exc:
        msg = str(exc)
        if "PermissionError" in msg or "拒绝" in msg:
            return False, f"无法打开 {port}（被其他程序占用，请先退出托盘程序/Arduino 串口监视器）"
        if "FileNotFound" in msg or "找不到" in msg:
            return False, f"找不到串口 {port}，请检查 USB 连接"
        return False, msg


def print_port_hint() -> None:
    ports = list_scored_ports()
    if not ports:
        print("未检测到任何 USB 串口。")
        return
    print("当前检测到的串口：")
    for item in ports:
        print(f"  {item.label}")


def ensure_daemon() -> None:
    if daemon_running():
        return
    start_tray_detached()
    for _ in range(20):
        time.sleep(0.25)
        if daemon_running():
            return
    raise RuntimeError("守护进程启动失败，请先运行 CodingLight.exe")


def main() -> int:
    cfg = load_config()
    port = cfg.get("port", "COM14")
    baud = int(cfg.get("baud", 115200))

    print(f"=== 1. 固件诊断 ({port}) ===")
    ok, detail = probe_firmware(port, baud)
    print(detail)
    if not ok:
        print_port_hint()
        print()
        print("请按以下步骤烧录固件：")
        print("  1. Arduino IDE → 开发板选 ESP32C3 Dev Module")
        print("  2. USB CDC On Boot = Enabled")
        print("  3. 打开 esp32/ai_traffic_light/ai_traffic_light.ino 并上传")
        print("  4. 模块 GND/R/Y/G 分别接 GND、GPIO4、GPIO5、GPIO6")
        print("  5. 上传完成后按一下 ESP32 的 RESET，再重新运行本脚本")
        return 1

    print()
    print("=== 2. 灯光测试（经守护进程）===")
    try:
        ensure_daemon()
        for label, action in [
            ("黄灯 - 思考中", mark_thinking),
            ("绿灯 - 完成", mark_done),
            ("红灯 - 报错", mark_error),
            ("熄灭", mark_off),
        ]:
            print(f"-> {label}")
            action()
            time.sleep(3)
        print(f"测试完成，日志: {log_path()}")
    except KeyboardInterrupt:
        print("\n已中断")
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
