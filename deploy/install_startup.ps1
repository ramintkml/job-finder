$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$vbs = Join-Path $PSScriptRoot "start_at_login.vbs"
$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$lnkPath = Join-Path $startup "LinkedIn Job Finder.lnk"

if (-not (Test-Path $vbs)) {
  throw "Missing $vbs"
}

New-Item -ItemType Directory -Force -Path $startup | Out-Null
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnkPath)
$sc.TargetPath = $vbs
$sc.WorkingDirectory = $repo
$sc.WindowStyle = 1
$sc.Description = "Start LinkedIn Job Finder tunnel, worker, and dashboard"
$sc.Save()

Write-Host "Startup shortcut created:"
Write-Host "  $lnkPath"
Write-Host "Target: $($sc.TargetPath)"
Write-Host ""
Write-Host "It runs 20 seconds after you sign in to Windows, then opens launch.bat and the dashboard."
