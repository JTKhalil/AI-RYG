#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$PcDir = Join-Path $Root "pc"
$DistExe = Join-Path $PcDir "dist\CursorTrafficLight.exe"
$Python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"

if (-not (Test-Path $Python)) {
    throw "未找到 Python 3.12: $Python"
}

Write-Host "==> 安装依赖" -ForegroundColor Cyan
& $Python -m pip install -r (Join-Path $PcDir "requirements.txt")

Write-Host "==> 打包 EXE" -ForegroundColor Cyan
Push-Location $PcDir
& $Python -m PyInstaller --noconfirm CursorTrafficLight.spec
& $Python -m PyInstaller --noconfirm CursorTrafficLightHook.spec
Pop-Location

$HookDir = Join-Path $PcDir "dist\CursorTrafficLightHook"
$HookExe = Join-Path $HookDir "CursorTrafficLightHook.exe"
if (-not (Test-Path $HookExe)) {
    throw "打包失败，未找到 $HookExe"
}

if (-not (Test-Path $DistExe)) {
    throw "打包失败，未找到 $DistExe"
}

Write-Host ""
Write-Host "打包完成: $DistExe" -ForegroundColor Green
Write-Host "运行安装: powershell -ExecutionPolicy Bypass -File `"$Root\scripts\install_app.ps1`""
