#Requires -Version 5.1
<#
.SYNOPSIS
  安装 Cursor Hooks，将 Agent 状态转发到 ESP32 信号灯。

.DESCRIPTION
  1. 检查 Python 与 pyserial
  2. 生成 pc/config.json（若不存在）
  3. 将 hooks.json 写入 %USERPROFILE%\.cursor\hooks.json
     若已有 hooks，会合并 ai-traffic-light 相关条目
#>

param(
    [string]$Port = "",
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

$PcDir = Join-Path $ProjectRoot "pc"
$ConfigPath = Join-Path $PcDir "config.json"
$ConfigExample = Join-Path $PcDir "config.example.json"
$HookBridge = Join-Path $PcDir "hook_bridge.py"
$CursorHooksDir = Join-Path $env:USERPROFILE ".cursor"
$CursorHooksFile = Join-Path $CursorHooksDir "hooks.json"

Write-Step "检查 Python"
$pythonExe = $null
$candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")
)
foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
        $pythonExe = $candidate
        break
    }
}
if (-not $pythonExe) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd -and $pythonCmd.Source -notmatch "WindowsApps") {
        $pythonExe = $pythonCmd.Source
    }
}
if (-not $pythonExe) {
    throw "未找到 python，请先安装 Python 3.8+"
}
Write-Host "使用: $pythonExe"
& $pythonExe --version

Write-Step "安装 Python 依赖"
& $pythonExe -m pip install -r (Join-Path $PcDir "requirements.txt")

Write-Step "配置串口"
if (-not (Test-Path $ConfigPath)) {
    Copy-Item $ConfigExample $ConfigPath
    Write-Host "已创建 $ConfigPath"
}

if ($Port) {
    $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    $cfg.port = $Port
    $cfg | ConvertTo-Json | Set-Content $ConfigPath -Encoding UTF8
    Write-Host "串口已设为 $Port"
} else {
    Write-Host "当前串口配置:"
    Get-Content $ConfigPath
    Write-Host "`n如需修改，编辑 config.json 或重新运行: .\setup_hooks.ps1 -Port COM5"
}

Write-Step "生成 Cursor Hooks 配置"
$RunHook = Join-Path $PcDir "run_hook.cmd"
$runHookContent = @"
@echo off
set `"PCDIR=%~dp0`"
`"$pythonExe`" `"%PCDIR%hook_bridge.py`" %*
"@
Set-Content -Path $RunHook -Value $runHookContent -Encoding ASCII

$hookCmd = $RunHook.Replace("\", "\\")

$newHooks = @{
    version = 1
    hooks = @{
        sessionStart       = @(@{ command = "$hookCmd off" })
        beforeSubmitPrompt = @(@{ command = "$hookCmd thinking" })
        afterAgentThought  = @(@{ command = "$hookCmd thinking" })
        preToolUse         = @(@{ command = "$hookCmd thinking" })
        postToolUse        = @(@{ command = "$hookCmd thinking" })
        beforeShellExecution = @(@{ command = "$hookCmd thinking" })
        beforeReadFile     = @(@{ command = "$hookCmd thinking" })
        beforeMCPExecution = @(@{ command = "$hookCmd thinking" })
        subagentStart      = @(@{ command = "$hookCmd thinking" })
        preCompact         = @(@{ command = "$hookCmd thinking" })
        postToolUseFailure = @(@{ command = "$hookCmd error" })
        stop               = @(@{ command = "$hookCmd done" })
        sessionEnd         = @(@{ command = "$hookCmd off" })
    }
}

if (-not (Test-Path $CursorHooksDir)) {
    New-Item -ItemType Directory -Path $CursorHooksDir | Out-Null
}

if (Test-Path $CursorHooksFile) {
    $existing = Get-Content $CursorHooksFile -Raw | ConvertFrom-Json
    if (-not $existing.hooks) {
        $existing | Add-Member -NotePropertyName hooks -NotePropertyValue ([pscustomobject]@{})
    }
    foreach ($key in $newHooks.hooks.Keys) {
        $existing.hooks | Add-Member -NotePropertyName $key -NotePropertyValue $newHooks.hooks[$key] -Force
    }
    $existing.version = 1
    $existing | ConvertTo-Json -Depth 10 | Set-Content $CursorHooksFile -Encoding UTF8
    Write-Host "已合并到现有 hooks: $CursorHooksFile"
} else {
    $newHooks | ConvertTo-Json -Depth 10 | Set-Content $CursorHooksFile -Encoding UTF8
    Write-Host "已创建: $CursorHooksFile"
}

Write-Step "完成"
Write-Host @"

下一步:
  1. 用 Arduino IDE 烧录 esp32/ai_traffic_light/ai_traffic_light.ino
  2. 在设备管理器中确认 ESP32 的 COM 口，写入 pc/config.json
  3. 运行测试: python pc/test_serial.py
  4. 重启 Cursor，在 Agent 中发送一条消息验证灯光

灯光含义:
  黄灯 = Cursor 正在思考 / 调用工具
  绿灯 = 本轮 Agent 完成
  红灯 = 工具调用失败
  熄灭 = 会话结束
"@ -ForegroundColor Green
