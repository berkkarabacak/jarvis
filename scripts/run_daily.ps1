$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

# Load API_SECRET from .env
$secret = $null
Get-Content .\.env | ForEach-Object {
  if ($_ -match '^\s*API_SECRET=(.+)$') { $secret = $Matches[1].Trim() }
}
if (-not $secret) { throw "API_SECRET missing in .env" }

$jobId = Get-Content .\data\job_id.txt -Raw
$day = (Get-Date).ToString("yyyy-MM-dd")
$headers = @{
  "X-Api-Key" = $secret
  "Idempotency-Key" = "$jobId-$day"
}

Write-Host "Running job $jobId for $day ..."
$r = Invoke-RestMethod -Uri "http://127.0.0.1:8787/api/jobs/$jobId/run" -Method Post -Headers $headers -TimeoutSec 600
$r | ConvertTo-Json -Depth 6
