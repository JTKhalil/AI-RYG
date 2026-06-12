# Cursor AI 信号灯

用 ESP32 红绿灯模块实时显示 Cursor Agent 的工作状态。

**完整安装与使用说明请阅读：[使用说明.md](./使用说明.md)** · 简洁版：[简明使用说明.md](./简明使用说明.md)

| 灯光 | 含义 |
|------|------|
| 黄灯 | 思考中（提交问题、推理、调用工具） |
| 绿灯 | 思考结束（本轮 Agent 完成） |
| 红灯 | 报错（工具调用失败） |
| 熄灭 | 会话结束 |

## 系统架构

```
Cursor Agent 事件
      │
      ▼
~/.cursor/hooks.json  ──►  hook_bridge.py  ──►  串口 COMx  ──►  ESP32  ──►  红绿灯
```

Cursor [Hooks](https://cursor.com/docs/hooks) 在 Agent 生命周期各阶段触发脚本，脚本通过串口向 ESP32 发送单字符命令（`Y`/`G`/`R`/`O`）。

## 硬件接线（ESP32-C3）

板子引出引脚：**GPIO 0–10、20–21**，以及 **3V / 5V / GND**。

### 四线模块（PIN1 / PIN2 / VCC / GND）

这是最常见的 ESP32 配套三色灯模块，只有 4 根线：

| 模块线 | 接 ESP32-C3 |
|--------|-------------|
| **VCC** | **5V**（多数模块用 5V；若标注 3.3V 则接 3V） |
| **GND** | **GND** |
| **PIN1** | **GPIO 4** |
| **PIN2** | **GPIO 5** |

两根信号线组合控制三种颜色：

| PIN1 | PIN2 | 亮灯 |
|------|------|------|
| 低 | 低 | 全灭 |
| 低 | 高 | 红 |
| 高 | 低 | 黄 |
| 高 | 高 | 绿 |

固件默认已启用 `TWO_PIN_MODULE = true`，**重新烧录后即可使用**。

> 编码表（PIN1=GPIO4，PIN2=GPIO5）已按本模块实测写入固件，修改后需重新烧录。

### 三线独立模块（红 / 黄 / 绿 各一根 + GND）

| 信号灯 | GPIO |
|--------|------|
| 红 | GPIO 4 |
| 黄 | GPIO 5 |
| 绿 | GPIO 6 |
| GND | GND |

固件中将 `TWO_PIN_MODULE` 改为 `false`。

## 快速开始

### 1. 烧录 ESP32 固件

1. 安装 [Arduino IDE](https://www.arduino.cc/en/software) 并添加 ESP32 开发板支持
2. 打开 `esp32/ai_traffic_light/ai_traffic_light.ino`
3. 开发板选 **ESP32C3 Dev Module**，USB CDC On Boot 选 **Enabled**（USB 直连电脑时）
4. 选择 COM 口并上传固件

上传成功后，串口监视器（115200）会显示 `Cursor AI Traffic Light Ready`。

### 2. 安装 PC 端

```powershell
cd D:\ESP32\ai信号灯
pip install -r pc/requirements.txt
copy pc\config.example.json pc\config.json
```

编辑 `pc/config.json`，将 `port` 改为 ESP32 的实际 COM 口（设备管理器中查看）：

```json
{
  "port": "COM3",
  "baud": 115200
}
```

### 3. 测试串口

```powershell
python pc/test_serial.py
```

应依次看到：熄灭 → 黄 → 绿 → 红 → 熄灭。

也可手动发送：

```powershell
python pc/serial_sender.py thinking
python pc/serial_sender.py done
python pc/serial_sender.py error
```

### 4. 安装 Cursor Hooks

```powershell
.\scripts\setup_hooks.ps1 -Port COM3
```

脚本会在 `%USERPROFILE%\.cursor\hooks.json` 写入 Hook 配置。若已有其他 Hook，会自动合并。

**重启 Cursor** 后 Hook 生效。向 Agent 发送一条消息，黄灯应亮起；回复完成后变绿。

## Hook 事件映射

| Cursor 事件 | 灯光 |
|-------------|------|
| `beforeSubmitPrompt` | 黄 |
| `afterAgentThought` | 黄 |
| `preToolUse` / `postToolUse` | 黄 |
| `subagentStart` | 黄 |
| `postToolUseFailure` | 红 |
| `stop` | 绿 |
| `sessionEnd` | 熄灭 |

可在 Cursor 设置 → **Hooks** 页或 **Hooks** 输出通道中调试。

## 串口协议

波特率 **115200**，发送单字符 + 换行：

| 命令 | 含义 |
|------|------|
| `Y` | 黄灯 |
| `G` | 绿灯 |
| `R` | 红灯（慢闪） |
| `O` | 全灭 |

## 自定义 GPIO

修改 `esp32/ai_traffic_light/ai_traffic_light.ino` 顶部的引脚定义：

```cpp
#define PIN_RED    4   // ESP32-C3 推荐
#define PIN_YELLOW 5
#define PIN_GREEN  6
```

## 故障排查

| 现象 | 处理 |
|------|------|
| Hook 不触发 | 重启 Cursor；检查 `%USERPROFILE%\.cursor\hooks.json` 路径是否正确 |
| 串口打不开 | 关闭 Arduino 串口监视器；确认 COM 口未被其他程序占用 |
| 灯不亮 | 检查接线与共阴/共阳设置；用 `test_serial.py` 单独测试 |
| 一直是黄灯 | 正常——Agent 多步工具调用期间会持续为黄色，直到 `stop` 事件 |

## 文件结构

```
ai信号灯/
├── esp32/ai_traffic_light/   # ESP32 固件
├── pc/                       # Python 串口桥接
│   ├── hook_bridge.py        # Cursor Hook 入口
│   ├── serial_sender.py      # 串口发送
│   ├── test_serial.py        # 测试脚本
│   └── config.json           # 串口配置（需自行创建）
├── hooks/hooks.json.example  # Hook 配置示例
└── scripts/setup_hooks.ps1   # 一键安装 Hook
```
