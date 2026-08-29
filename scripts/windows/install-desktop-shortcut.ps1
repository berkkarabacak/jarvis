# ==GRoK== Creates a Desktop shortcut for the local Control Room app window.
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$repo = (Resolve-Path (Join-Path $here "..\..")).Path
$bat = Join-Path $here "start-control-room.bat"
$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "AI Control Room.lnk"

$w = New-Object -ComObject WScript.Shell
$sc = $w.CreateShortcut($lnkPath)
$sc.TargetPath = $bat
$sc.WorkingDirectory = $repo
$sc.WindowStyle = 1
$sc.Description = "AI Control Room (local) ==GRoK=="
$sc.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
$sc.Save()

Write-Host "Shortcut created: $lnkPath"
Write-Host "Double-click to start the local app (first run installs deps)."
