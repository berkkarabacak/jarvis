# ==GRoK== Local AI Control Room on Windows
# Starts uvicorn on 127.0.0.1 and opens the CEO UI as an app window.
#
#   powershell -ExecutionPolicy Bypass -File scripts\windows\start-control-room.ps1
#   powershell -File scripts\windows\start-control-room.ps1 -NoBrowser
#   powershell -File scripts\windows\start-control-room.ps1 -Prime
#   Prefer the Electron app: npm start --prefix desktop

[CmdletBinding()]
param(
  [switch]$NoBrowser,
  [switch]$Prime,
  [switch]$SetupOnly,
  [int]$Port = 0
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  $here = $PSScriptRoot
  if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
  return (Resolve-Path (Join-Path $here "..\..")).Path
}

function Read-DotEnv([string]$Path) {
  $map = @{}
  if (-not (Test-Path -LiteralPath $Path)) { return $map }
  Get-Content -LiteralPath $Path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $i = $line.IndexOf("=")
    if ($i -lt 1) { return }
    $k = $line.Substring(0, $i).Trim()
    $v = $line.Substring($i + 1).Trim()
    if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) {
      $v = $v.Substring(1, $v.Length - 2)
    }
    $map[$k] = $v
  }
  return $map
}

function Ensure-Venv([string]$Root) {
  $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
  if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Host "==> Creating .venv"
    python -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "python -m venv failed. Install Python 3.10+ and retry." }
  }
  $pip = Join-Path $Root ".venv\Scripts\pip.exe"
  Write-Host "==> Installing requirements (quiet)"
  & $pip install -q -r (Join-Path $Root "requirements.txt")
  if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
  return $venvPy
}

function Ensure-EnvFile([string]$Root) {
  $envPath = Join-Path $Root ".env"
  $localExample = Join-Path $Root "deploy\local-windows.env.example"
  $baseExample = Join-Path $Root ".env.example"
  if (Test-Path -LiteralPath $envPath) {
    Write-Host "==> Using existing .env"
    return $envPath
  }
  $src = if (Test-Path -LiteralPath $localExample) { $localExample } else { $baseExample }
  if (-not (Test-Path -LiteralPath $src)) { throw "No .env.example found" }
  Copy-Item -LiteralPath $src -Destination $envPath
  $py = Join-Path $Root ".venv\Scripts\python.exe"
  if (-not (Test-Path -LiteralPath $py)) { $py = "python" }
  $apiSecret = & $py -c "import secrets; print(secrets.token_urlsafe(48))"
  $fernet = & $py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>$null
  if (-not $fernet) {
    & (Join-Path $Root ".venv\Scripts\pip.exe") install -q cryptography | Out-Null
    $fernet = & $py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  }
  $text = Get-Content -LiteralPath $envPath -Raw
  $text = $text -replace "(?m)^API_SECRET=.*$", "API_SECRET=$apiSecret"
  if ($text -match "(?m)^TOKEN_ENCRYPTION_KEY=") {
    $text = $text -replace "(?m)^TOKEN_ENCRYPTION_KEY=.*$", "TOKEN_ENCRYPTION_KEY=$fernet"
  } else {
    $text = $text.TrimEnd() + "`r`nTOKEN_ENCRYPTION_KEY=$fernet`r`n"
  }
  [System.IO.File]::WriteAllText($envPath, $text)
  Write-Host "==> Wrote .env with generated API_SECRET (set OPENROUTER_API_KEY before chat works)"
  Write-Host "    $envPath"
  return $envPath
}

function Open-CeoWindow([string]$Url) {
  $paths = @(
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
    (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe")
  )
  foreach ($exe in $paths) {
    if ($exe -and (Test-Path -LiteralPath $exe)) {
      Write-Host "==> Opening app window: $Url"
      $arg1 = "--app=$Url"
      Start-Process -FilePath $exe -ArgumentList $arg1, "--new-window"
      return
    }
  }
  Write-Host "==> Opening default browser: $Url"
  Start-Process $Url
}

$Root = Get-RepoRoot
Set-Location -LiteralPath $Root
Write-Host "AI Control Room (local Windows) ==GRoK=="
Write-Host "Repo: $Root"

$venvPy = Ensure-Venv $Root
$envFile = Ensure-EnvFile $Root
$dotenv = Read-DotEnv $envFile

if ($Port -le 0) {
  if ($dotenv.ContainsKey("PORT") -and $dotenv["PORT"]) { $Port = [int]$dotenv["PORT"] } else { $Port = 8787 }
}
$hostBind = "127.0.0.1"

foreach ($k in $dotenv.Keys) {
  [Environment]::SetEnvironmentVariable($k, [string]$dotenv[$k], "Process")
}
$env:HOST = $hostBind
$env:PORT = "$Port"
$env:PUBLIC_BASE_URL = "http://127.0.0.1:$Port"

if ($Prime) {
  $env:PRIME_AGENT_ENABLED = "true"
  if (-not $env:PRIME_AGENT_WORKDIR) {
    $wd = Join-Path $env:USERPROFILE "AI-Control-Room-Workspace"
    New-Item -ItemType Directory -Force -Path $wd | Out-Null
    $env:PRIME_AGENT_WORKDIR = $wd
  }
  if (-not $env:PRIME_AGENT_BIN) {
    $which = Get-Command prime-agent -ErrorAction SilentlyContinue
    if ($which) { $env:PRIME_AGENT_BIN = $which.Source }
  }
  Write-Host "==> Prime mode ON"
  Write-Host "    PRIME_AGENT_BIN=$($env:PRIME_AGENT_BIN)"
  Write-Host "    PRIME_AGENT_WORKDIR=$($env:PRIME_AGENT_WORKDIR)"
  if (-not $env:PRIME_AGENT_BIN) {
    Write-Warning "prime-agent not on PATH. Install it or set PRIME_AGENT_BIN in .env."
  }
}

if (-not $env:OPENROUTER_API_KEY) {
  Write-Warning "OPENROUTER_API_KEY is empty - set it in .env for live chat."
}

$dataDir = Join-Path $Root "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

if ($SetupOnly) {
  Write-Host "==> Setup only complete."
  exit 0
}

$ceoUrl = "http://127.0.0.1:$Port/ceo"
Write-Host "==> Starting uvicorn on ${hostBind}:$Port"
Write-Host "    CEO: $ceoUrl"
Write-Host "    Ctrl+C to stop"
Write-Host "    Tip: npm start --prefix desktop  # Electron shell, same UI"

if (-not $NoBrowser) {
  $urlForJob = $ceoUrl
  Start-Job -ScriptBlock {
    param($u)
    Start-Sleep -Seconds 2
    $edgeCandidates = @(
      (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
      (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
      (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe")
    )
    $edge = $null
    foreach ($c in $edgeCandidates) {
      if ($c -and (Test-Path -LiteralPath $c)) { $edge = $c; break }
    }
    if ($edge) {
      Start-Process -FilePath $edge -ArgumentList @("--app=$u", "--new-window")
    } else {
      Start-Process $u
    }
  } -ArgumentList $urlForJob | Out-Null
}

& $venvPy -m uvicorn app.main:app --host $hostBind --port $Port --proxy-headers --forwarded-allow-ips=127.0.0.1
