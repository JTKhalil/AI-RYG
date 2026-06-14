#Requires -Version 5.1
$Candidates = @(
    (Join-Path $env:ProgramFiles "CodingLight\CodingLight.exe"),
    (Join-Path $env:LOCALAPPDATA "CodingLight\CodingLight.exe"),
    (Join-Path $env:LOCALAPPDATA "CursorTrafficLight\CursorTrafficLight.exe"),
    (Join-Path (Split-Path -Parent $PSScriptRoot) "pc\dist\CodingLight.exe")
)

foreach ($Exe in $Candidates) {
    if (Test-Path $Exe) {
        Start-Process $Exe
        exit 0
    }
}

Write-Host "CodingLight.exe not found. Run CodingLightSetup.exe to install." -ForegroundColor Red
exit 1
