#Requires -Version 5.1
$Exe = Join-Path $env:LOCALAPPDATA "CursorTrafficLight\CursorTrafficLight.exe"
$Legacy = Join-Path (Split-Path -Parent $PSScriptRoot) "pc\dist\CursorTrafficLight.exe"

if (Test-Path $Exe) {
    Start-Process $Exe
    Write-Host "Started: $Exe"
} elseif (Test-Path $Legacy) {
    Start-Process $Legacy
    Write-Host "Started: $Legacy"
} else {
    Write-Host "请先运行 scripts\build_exe.ps1 和 scripts\install_app.ps1" -ForegroundColor Red
    exit 1
}
