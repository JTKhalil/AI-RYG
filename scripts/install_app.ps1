#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$InstallDir = Join-Path $env:LOCALAPPDATA "CursorTrafficLight"
$SrcExe = Join-Path $Root "pc\dist\CursorTrafficLight.exe"
$SrcHookDir = Join-Path $Root "pc\dist\CursorTrafficLightHook"
$DestExe = Join-Path $InstallDir "CursorTrafficLight.exe"
$DestHookDir = Join-Path $InstallDir "CursorTrafficLightHook"
$Desktop = [Environment]::GetFolderPath("Desktop")
$Shortcut = Join-Path $Desktop "Cursor AI Traffic Light.lnk"

if (-not (Test-Path $SrcExe)) {
    Write-Host "Run scripts\build_exe.ps1 first" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $SrcHookDir "CursorTrafficLightHook.exe"))) {
    Write-Host "Run scripts\build_exe.ps1 first (missing Hook exe)" -ForegroundColor Red
    exit 1
}

Write-Host "==> Install to $InstallDir" -ForegroundColor Cyan
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item $SrcExe $DestExe -Force
if (Test-Path $DestHookDir) {
    Remove-Item $DestHookDir -Recurse -Force
}
Copy-Item $SrcHookDir $DestHookDir -Recurse -Force
Remove-Item (Join-Path $InstallDir "CursorTrafficLightHook.exe") -Force -ErrorAction SilentlyContinue

Write-Host "==> Create desktop shortcut" -ForegroundColor Cyan
$WshShell = New-Object -ComObject WScript.Shell
$Lnk = $WshShell.CreateShortcut($Shortcut)
$Lnk.TargetPath = $DestExe
$Lnk.WorkingDirectory = $InstallDir
$Lnk.Save()

Write-Host "==> Start app" -ForegroundColor Cyan
Start-Process $DestExe

Write-Host ""
Write-Host "Done!" -ForegroundColor Green
Write-Host "  App:    $DestExe"
Write-Host "  Hook:   $(Join-Path $DestHookDir 'CursorTrafficLightHook.exe')"
Write-Host "  Config: $env:APPDATA\CursorTrafficLight\config.json"
Write-Host "  Log:    $env:APPDATA\CursorTrafficLight\app.log"
Write-Host ""
Write-Host "Restart Cursor after first launch."
