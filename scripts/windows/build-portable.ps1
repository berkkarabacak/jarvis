# ==GRoK== Build a downloadable Jarvis portable zip for Windows
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$OutDir = Join-Path $Root "dist"
$Stage = Join-Path $env:TEMP "jarvis-portable-stage-GRoK"
$Zip = Join-Path $OutDir "Jarvis-Windows-Portable-GRoK.zip"

Write-Host "Building portable Jarvis from $Root"

if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage, $OutDir | Out-Null

$include = @(
  "app",
  "deploy",
  "desktop",
  "scripts",
  "docs",
  "requirements.txt",
  "README.md",
  "RUN-JARVIS.bat",
  ".env.example"
)

foreach ($item in $include) {
  $src = Join-Path $Root $item
  if (Test-Path $src) {
    $dest = Join-Path $Stage $item
    if (Test-Path $src -PathType Container) {
      Copy-Item -Recurse -Force $src $dest
    } else {
      $parent = Split-Path $dest -Parent
      if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
      Copy-Item -Force $src $dest
    }
  }
}

# strip caches
Get-ChildItem -Path $Stage -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $Stage -Recurse -Directory -Filter "node_modules" -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $Stage -Recurse -Directory -Filter ".venv" -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# README for users
@"
Jarvis — Windows portable (advanced) ==GRoK==
=============================================

Prefer Jarvis-Setup.exe if you have it: double-click, paste the key, done.
This zip is the advanced copy (you install Python yourself).

1. Install Python 3.10+ from https://www.python.org/downloads/ (check "Add to PATH")
2. Unzip this folder anywhere
3. Double-click RUN-JARVIS.bat
4. First run creates .env — paste your OPENROUTER_API_KEY and save
5. Run RUN-JARVIS.bat again
6. Say: "Jarvis, create an Excel file of my tasks" or "organize my documents"

Workspace (safe sandbox):
  %USERPROFILE%\Documents\Jarvis\
    Inbox\  Documents\  Scripts\  Exports\  Memory\

Put files to organize into Documents\Jarvis\Inbox

Voice: Edge/Chrome window opens automatically. Allow microphone once.
"@ | Set-Content -Encoding utf8 (Join-Path $Stage "START-HERE.txt")

if (Test-Path $Zip) { Remove-Item -Force $Zip }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip -Force
$size = (Get-Item $Zip).Length
Write-Host "Created $Zip ($([math]::Round($size/1MB,2)) MB)"
Write-Host $Zip
