# Build Jarvis-Setup.exe on a Windows machine (Odin).
# Linux CI cannot produce a usable Windows installer. This script is the source of truth.
#
#   powershell -ExecutionPolicy Bypass -File scripts\windows\build-installer.ps1
#
# Output: dist\Jarvis-Setup.exe
# Does not commit the exe. Re-run on Windows after pulling this branch.

[CmdletBinding()]
param(
  [string]$PythonVersion = "3.12.10",
  [switch]$SkipNpmInstall,
  [string]$SignCert = $env:JARVIS_SIGN_CERT
)

$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
  throw "Run this script on a Windows PC (Odin). Linux cannot build Jarvis-Setup.exe."
}

function Get-RepoRoot {
  $here = $PSScriptRoot
  if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
  return (Resolve-Path (Join-Path $here "..\..")).Path
}

function Assert-Command([string]$Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Missing '$Name' on PATH. Install it, then re-run this script."
  }
}

$Root = Get-RepoRoot
$OutDir = Join-Path $Root "dist"
$Payload = Join-Path $OutDir "installer-payload"
$PythonDir = Join-Path $Payload "python"
$BackendDir = Join-Path $Payload "backend"
$CacheDir = Join-Path $OutDir "installer-cache"
$DesktopDir = Join-Path $Root "desktop"
$FinalExe = Join-Path $OutDir "Jarvis-Setup.exe"

Write-Host "Jarvis Windows installer build"
Write-Host "Repo: $Root"

Assert-Command "node"
Assert-Command "npm"

New-Item -ItemType Directory -Force -Path $OutDir, $Payload, $CacheDir | Out-Null
if (Test-Path $PythonDir) { Remove-Item -Recurse -Force $PythonDir }
if (Test-Path $BackendDir) { Remove-Item -Recurse -Force $BackendDir }
New-Item -ItemType Directory -Force -Path $PythonDir, $BackendDir | Out-Null

# --- App tree (no tests, no desktop, no venv) ---
Write-Host "==> Staging backend"
$backendItems = @("app", "deploy", "requirements.txt", ".env.example", "run_jarvis_server.py")
foreach ($item in $backendItems) {
  $src = Join-Path $Root $item
  if (-not (Test-Path $src)) { continue }
  $dest = Join-Path $BackendDir $item
  if (Test-Path $src -PathType Container) {
    Copy-Item -Recurse -Force $src $dest
  } else {
    Copy-Item -Force $src $dest
  }
}
Get-ChildItem -Path $BackendDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# Operator talk secret — private build env only. Never commit this file.
# Berk sets JARVIS_OPERATOR_OPENROUTER_KEY or OPENROUTER_API_KEY (and
# optionally JARVIS_HOSTED_TALK_URL) on Odin. Family users never see it.
$opKey = $env:JARVIS_OPERATOR_OPENROUTER_KEY
if (-not $opKey) { $opKey = $env:OPENROUTER_API_KEY }
$opUrl = $env:JARVIS_HOSTED_TALK_URL
if ($opKey -or $opUrl) {
  $opLines = @()
  if ($opKey) { $opLines += "JARVIS_OPERATOR_OPENROUTER_KEY=$opKey" }
  if ($opUrl) { $opLines += "JARVIS_HOSTED_TALK_URL=$opUrl" }
  Set-Content -LiteralPath (Join-Path $BackendDir "operator.env") -Value ($opLines -join "`n") -Encoding ascii
  Write-Host "==> Wrote operator.env into installer payload (not in git)"
}

# --- Official CPython embeddable runtime ---
$pyTag = $PythonVersion.Split(".")[0] + $PythonVersion.Split(".")[1]
$embedName = "python-$PythonVersion-embed-amd64.zip"
$embedUrl = "https://www.python.org/ftp/python/$PythonVersion/$embedName"
$embedZip = Join-Path $CacheDir $embedName
if (-not (Test-Path $embedZip)) {
  Write-Host "==> Downloading $embedUrl"
  Invoke-WebRequest -Uri $embedUrl -OutFile $embedZip -UseBasicParsing
} else {
  Write-Host "==> Using cached $embedZip"
}
Write-Host "==> Expanding embeddable Python"
Expand-Archive -Path $embedZip -DestinationPath $PythonDir -Force

$runtimePy = Join-Path $PythonDir "python.exe"
if (-not (Test-Path $runtimePy)) { throw "python.exe missing in $PythonDir" }

# Embeddable CPython isolates via python*._pth: PYTHONPATH and cwd are ignored.
# Point the runtime at the sibling backend so ``-m app.*`` and uvicorn resolve.
$pth = Get-ChildItem -Path $PythonDir -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) { throw "python*._pth missing from embeddable runtime" }
$pthHelper = Join-Path $Root "scripts\windows\embeddable_pth.py"
Write-Host "==> Adding ../backend to $($pth.Name) (isolated Python ignores PYTHONPATH)"
& $runtimePy $pthHelper $pth.FullName
if ($LASTEXITCODE -ne 0) { throw "embeddable_pth.py failed" }

$getPip = Join-Path $CacheDir "get-pip.py"
if (-not (Test-Path $getPip)) {
  Write-Host "==> Downloading get-pip.py"
  Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing
}

Write-Host "==> Installing pip into bundled runtime"
& $runtimePy $getPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip.py failed" }

$reqSrc = Join-Path $Root "requirements.txt"
$reqDst = Join-Path $CacheDir "installer-requirements.txt"
Get-Content -LiteralPath $reqSrc |
  Where-Object { $_ -notmatch "^\s*pytest" } |
  Set-Content -LiteralPath $reqDst -Encoding ascii

Write-Host "==> pip install (runtime, no pytest)"
& $runtimePy -m pip install --no-warn-script-location -r $reqDst
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# --- Electron NSIS ---
Push-Location $DesktopDir
try {
  if (-not $SkipNpmInstall -or -not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
    Write-Host "==> npm install (desktop)"
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
  }
  Write-Host "==> electron-builder NSIS"
  npx electron-builder --win nsis --config electron-builder.installer.yml
  if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }
} finally {
  Pop-Location
}

$built = Join-Path $DesktopDir "dist\Jarvis-Setup.exe"
if (-not (Test-Path $built)) {
  $found = Get-ChildItem -Path (Join-Path $DesktopDir "dist") -Filter "Jarvis-Setup*.exe" -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if ($found) { $built = $found.FullName }
}
if (-not (Test-Path $built)) { throw "electron-builder did not produce Jarvis-Setup.exe" }

Copy-Item -Force $built $FinalExe

if ($SignCert) {
  Assert-Command "signtool"
  Write-Host "==> Signing $FinalExe"
  signtool sign /fd SHA256 /n $SignCert /tr http://timestamp.digicert.com /td SHA256 $FinalExe
  if ($LASTEXITCODE -ne 0) { throw "signtool failed" }
} else {
  Write-Host "==> Skip signing (set JARVIS_SIGN_CERT to sign on Odin)"
}

$size = (Get-Item $FinalExe).Length
Write-Host "Created $FinalExe ($([math]::Round($size/1MB, 1)) MB)"
Write-Host "Give that one file to the user. Do not zip it. Do not commit it."
Write-Host $FinalExe
