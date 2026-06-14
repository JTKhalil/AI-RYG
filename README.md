# CodingLight

用 ESP32 红绿灯模块实时显示 Cursor / Claude Agent 的工作状态。

| 灯光 | 含义 |
|------|------|
| 黄灯 | 思考中（提交问题、推理、调用工具） |
| 绿灯 | 思考结束（本轮 Agent 完成） |
| 红灯 | 报错（工具调用失败） |
| 熄灭 | 会话结束 |

## 系统架构

```
Cursor / Claude Agent 事件
            │
            ▼
~/.cursor/hooks.json  ──►  CodingLightHook.exe  ──►  LightDaemon  ──►  串口 COMx  ──►  ESP32  ──►  红绿灯
                                    ▲
                            CodingLight.exe（托盘）
```

- **CodingLight.exe**：系统托盘常驻，管理串口连接、Hook 安装与连接设置。
- **CodingLightHook.exe**：由 Cursor Hooks 调用，将 Agent 状态转发给后台守护进程。
- **配置与日志**：`%APPDATA%\CodingLight\`（与安装目录分离，卸载时默认一并删除）。

Cursor [Hooks](https://cursor.com/docs/hooks) 在 Agent 生命周期各阶段触发脚本，最终通过串口向 ESP32 发送单字符命令（`Y` / `G` / `R` / `O`）。

---

## 用户安装（推荐）

### 要求

- Windows 10 / 11
- **需要管理员权限**（默认安装到 `C:\Program Files\CodingLight`，并注册系统卸载项）

### 步骤

1. 双击 **`pc/dist/CodingLightSetup.exe`**（或从发布页下载的安装包）。
2. 在 UAC 提示中允许管理员权限。
3. 确认安装路径（默认 `C:\Program Files\CodingLight`），可选：
   - 创建桌面快捷方式
   - 开机自启
   - 安装后立即运行
4. 烧录 ESP32 固件（见下文「硬件与固件」）。
5. 右键托盘图标 → **连接设置**，选择 COM 口并保存。
6. 托盘菜单 → **安装 Cursor Hooks**（或 **安装 Claude Hooks**），然后**重启 Cursor**。

### 卸载

- **设置 → 应用 → CodingLight → 卸载**，或运行安装目录中的 `CodingLightUninstall.exe`。
- 默认会删除 `%APPDATA%\CodingLight\` 下的配置与日志。
- 安装目录会在卸载程序退出后由后台任务自动清理（无黑窗口弹出）。
- 若需保留用户配置，可手动运行：`CodingLightUninstall.exe /keep-data`

### 检查更新

- 托盘菜单 → **检查更新**：访问 [GitHub Releases](https://github.com/JTKhalil/AI-RYG/releases) 对比版本，有新版本时打开下载页。
- 启动时会自动检查（每 24 小时最多一次）；发现新版本会弹窗提示。
- 下载新版 `CodingLightSetup.exe` 后重新安装即可覆盖升级。

---

## 开发者：从源码构建

### 环境

- Python 3.12（路径默认 `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`）
- Windows PowerShell 5.1+

### 一键打包

```powershell
cd AI-RYG
.\scripts\build_exe.ps1
```

产物位于 `pc/dist/`（已加入 `.gitignore`，需本地构建）：

| 文件 | 说明 |
|------|------|
| `CodingLightSetup.exe` | 图形化安装包（**唯一分发产物**） |
| `CodingLight.exe` | 托盘主程序（安装包内置，不单独发布） |
| `CodingLightHook/` | Hook 可执行文件目录（安装包内置） |
| `CodingLightUninstall.exe` | 卸载程序（安装包内置） |

> 图标由 `scripts/process_icon.py` 从 `pc/assets/icon_source.png` 生成，打包脚本会自动处理。

### 发布新版本（GitHub Releases）

1. 修改 `pc/app_paths.py` 中的 `APP_VERSION`（需与 Git tag 一致，如 `1.0.1` ↔ `v1.0.1`）。
2. 提交并推送代码。
3. 打 tag 并推送，GitHub Actions 会自动构建并发布：

```powershell
git tag v1.0.1
git push origin v1.0.1
```

Release 仅上传 `CodingLightSetup.exe`；用户端托盘「检查更新」会自动发现新版本。

### 静默安装到 Program Files（需管理员 PowerShell）

```powershell
.\scripts\install_app.ps1
```

### 源码模式运行（无需打包）

```powershell
cd AI-RYG
pip install -r pc/requirements.txt
copy pc\config.example.json %APPDATA%\CodingLight\config.json
python pc/cursor_light_app.py
```

Hook 可用脚本安装：

```powershell
.\scripts\setup_hooks.ps1 -Port COM3
```

---

## 硬件与固件

### 烧录 ESP32 固件

1. 安装 [Arduino IDE](https://www.arduino.cc/en/software) 并添加 ESP32 开发板支持。
2. 打开 `esp32/ai_traffic_light/ai_traffic_light.ino`。
3. 开发板选 **ESP32C3 Dev Module**，USB CDC On Boot 选 **Enabled**（USB 直连电脑时）。
4. 选择 COM 口并上传固件。

上传成功后，串口监视器（115200）会显示就绪信息。

### 硬件接线（ESP32-C3）

板子引出引脚：**GPIO 0–10、20–21**，以及 **3V / 5V / GND**。

#### 四线模块（PIN1 / PIN2 / VCC / GND）

| 模块线 | 接 ESP32-C3 |
|--------|-------------|
| **VCC** | **5V**（多数模块用 5V；若标注 3.3V 则接 3V） |
| **GND** | **GND** |
| **PIN1** | **GPIO 4** |
| **PIN2** | **GPIO 5** |

| PIN1 | PIN2 | 亮灯 |
|------|------|------|
| 低 | 低 | 全灭 |
| 低 | 高 | 红 |
| 高 | 低 | 黄 |
| 高 | 高 | 绿 |

固件默认 `TWO_PIN_MODULE = true`，重新烧录后即可使用。

#### 三线独立模块（红 / 黄 / 绿 各一根 + GND）

| 信号灯 | GPIO |
|--------|------|
| 红 | GPIO 4 |
| 黄 | GPIO 5 |
| 绿 | GPIO 6 |
| GND | GND |

固件中将 `TWO_PIN_MODULE` 改为 `false`。

### 测试串口

打包安装后可在安装目录运行，或源码模式：

```powershell
python pc/test_serial.py
```

应依次看到：熄灭 → 黄 → 绿 → 红 → 熄灭。

---

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

可在 Cursor **设置 → Hooks** 或 **Hooks** 输出通道中调试。

---

## 串口协议

波特率 **115200**，发送单字符 + 换行：

| 命令 | 含义 |
|------|------|
| `Y` | 黄灯 |
| `G` | 绿灯 |
| `R` | 红灯（慢闪） |
| `O` | 全灭 |

---

## 路径说明

| 用途 | 路径 |
|------|------|
| 默认安装目录 | `C:\Program Files\CodingLight` |
| 用户配置 / 日志 | `%APPDATA%\CodingLight\` |
| Cursor Hooks | `%USERPROFILE%\.cursor\hooks.json` |
| 旧版名称（自动迁移） | `CursorTrafficLight` |

---

## 故障排查

| 现象 | 处理 |
|------|------|
| Hook 不触发 | 重启 Cursor；托盘菜单检查 Hook 状态并重新安装 |
| 串口打不开 | 托盘 → 连接设置，确认 COM 口；关闭占用串口的其他程序 |
| 灯不亮 | 检查接线；用 `test_serial.py` 单独测试 |
| 一直是黄灯 | 正常——Agent 多步工具调用期间会持续为黄色，直到 `stop` 事件 |
| 卸载后目录残留 | 使用新版 `CodingLightUninstall.exe`；若仍残留可手动删除 `C:\Program Files\CodingLight` |

---

## 文件结构

```
AI-RYG/
├── esp32/ai_traffic_light/     # ESP32 固件
├── pc/
│   ├── cursor_light_app.py     # 托盘主程序入口
│   ├── hook_entry.py           # Hook 子进程入口
│   ├── light_daemon.py         # 串口守护进程
│   ├── installer_app.py        # 图形安装程序
│   ├── uninstall_app.py        # 卸载程序
│   ├── installer_logic.py      # 安装 / 卸载逻辑
│   ├── install_hooks.py        # Cursor / Claude Hook 安装
│   ├── port_settings_dialog.py # 连接设置对话框
│   ├── update_checker.py       # GitHub Releases 更新检查
│   └── dist/                   # 打包产物（Setup.exe 等）
├── scripts/
│   ├── build_exe.ps1           # 完整打包流程
│   ├── install_app.ps1         # 静默安装（管理员）
│   ├── setup_hooks.ps1         # 源码模式 Hook 安装
│   └── process_icon.py         # 托盘 / EXE 图标处理
└── README.md
```

---

## 自定义 GPIO

修改 `esp32/ai_traffic_light/ai_traffic_light.ino` 顶部的引脚定义：

```cpp
#define PIN_RED    4
#define PIN_YELLOW 5
#define PIN_GREEN  6
```
