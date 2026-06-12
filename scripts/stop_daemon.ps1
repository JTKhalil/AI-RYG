#Requires -Version 5.1
$PcDir = Join-Path (Split-Path -Parent $PSScriptRoot) "pc"
$PidFile = Join-Path $PcDir ".daemon.pid"

if (-not (Test-Path $PidFile)) {
    Write-Host "Daemon not running"
    exit 0
}

$daemonPid = Get-Content $PidFile
Stop-Process -Id $daemonPid -Force -ErrorAction SilentlyContinue
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "Daemon stopped ($daemonPid)"
