#Requires -Version 5.1
#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$PcDir = Join-Path $Root "pc"
$Python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$SetupExe = Join-Path $PcDir "dist\CodingLightSetup.exe"

if (-not (Test-Path $Python)) {
    throw "未找到 Python 3.12: $Python"
}

if (-not (Test-Path (Join-Path $PcDir "dist\CodingLight.exe"))) {
    Write-Host "Run scripts\build_exe.ps1 first" -ForegroundColor Red
    exit 1
}

Write-Host "==> 静默安装到 Program Files" -ForegroundColor Cyan
Push-Location $PcDir
& $Python -c @"
from installer_logic import default_install_dir, install_app
dest = install_app(default_install_dir(), desktop_shortcut=True, autostart=True, launch_after=True)
print('Installed:', dest)
"@
Pop-Location

Write-Host ""
Write-Host "Done!" -ForegroundColor Green
Write-Host "  App:    $env:ProgramFiles\CodingLight\CodingLight.exe"
Write-Host "  Config: $env:APPDATA\CodingLight\config.json"
Write-Host ""
Write-Host "也可直接双击 dist\CodingLightSetup.exe 使用图形安装界面。"
