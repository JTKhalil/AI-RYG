#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$PcDir = Join-Path $Root "pc"
$DistExe = Join-Path $PcDir "dist\CodingLight.exe"
$Python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python 3.12 not found: $Python"
}

Write-Host "==> Install deps" -ForegroundColor Cyan
& $Python -m pip install -r (Join-Path $PcDir "requirements.txt")

Write-Host "==> Process icon" -ForegroundColor Cyan
& $Python (Join-Path $Root "scripts\process_icon.py")

Write-Host "==> Build EXE" -ForegroundColor Cyan
Push-Location $PcDir
& $Python -m PyInstaller --noconfirm CodingLight.spec
& $Python -m PyInstaller --noconfirm CodingLightHook.spec
& $Python -m PyInstaller --noconfirm CodingLightUninstall.spec
Pop-Location

$HookDir = Join-Path $PcDir "dist\CodingLightHook"
$HookExe = Join-Path $HookDir "CodingLightHook.exe"
if (-not (Test-Path $HookExe)) {
    throw "Build failed: $HookExe"
}

if (-not (Test-Path $DistExe)) {
    throw "Build failed: $DistExe"
}

$UninstallExe = Join-Path $PcDir "dist\CodingLightUninstall.exe"
if (-not (Test-Path $UninstallExe)) {
    throw "Build failed: $UninstallExe"
}

Write-Host "==> Build installer" -ForegroundColor Cyan
Push-Location $PcDir
& $Python -m PyInstaller --noconfirm CodingLightSetup.spec
Pop-Location

$SetupExe = Join-Path $PcDir "dist\CodingLightSetup.exe"
if (-not (Test-Path $SetupExe)) {
    throw "Build failed: $SetupExe"
}

Write-Host ""
Write-Host "Done:" -ForegroundColor Green
Write-Host "  App:     $DistExe"
Write-Host "  Setup:   $SetupExe"
Write-Host "  Default: C:\Program Files\CodingLight"
