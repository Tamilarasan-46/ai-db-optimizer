<#
.SYNOPSIS
  Switch which database the AI Database Optimizer analyses, then recreate the
  backend so it reconnects to the new target.

.DESCRIPTION
  Rewrites only the database name in the TARGET_DATABASE_URL line of .env
  (keeping the same user / password / host / port), then runs
  `docker compose ... up -d --force-recreate backend`.

  Run setup-target-readonly-user.sql against a database ONCE before analysing it
  (the read-only role needs CONNECT + SELECT in that database).

.EXAMPLE
  .\switch-target-db.ps1 tectalik_trade_api_dev
  .\switch-target-db.ps1 jwl_erp_dev
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Database
)

$ErrorActionPreference = "Stop"
$envFile = Join-Path $PSScriptRoot ".env"
$compose = Join-Path $PSScriptRoot "docker-compose.new-container.yml"

if (-not (Test-Path $envFile)) { throw ".env not found at $envFile" }

# Read as UTF-8 (PS 5.1 Get-Content misreads UTF-8 and mangles comment glyphs).
$lines = [System.IO.File]::ReadAllLines($envFile)
$found = $false
for ($i = 0; $i -lt $lines.Count; $i++) {
    # match commented or uncommented TARGET_DATABASE_URL; capture everything up to the last /<dbname>
    if ($lines[$i] -match '^\s*#?\s*TARGET_DATABASE_URL\s*=\s*(postgresql://[^/]+)/[^\s]+') {
        $prefix = $Matches[1]
        $lines[$i] = "TARGET_DATABASE_URL=$prefix/$Database"
        $found = $true
        break
    }
}
if (-not $found) {
    throw "No TARGET_DATABASE_URL line found in .env. Add one first (see .env.example)."
}

# Write back as UTF-8 without BOM (so docker compose parses the first line cleanly).
[System.IO.File]::WriteAllLines($envFile, $lines)
Write-Host "[ok] TARGET_DATABASE_URL now points at database: $Database" -ForegroundColor Green
Write-Host "     (reminder: run setup-target-readonly-user.sql against '$Database' once if you haven't)" -ForegroundColor Yellow

Write-Host "[..] Recreating backend so it reconnects..." -ForegroundColor Cyan
docker compose -f $compose up -d --force-recreate backend

Write-Host "[ok] Done. Verify with:" -ForegroundColor Green
Write-Host "     docker logs --tail 20 ai-opt-backend"
Write-Host "     curl.exe http://localhost:8000/api/queries/slow"
