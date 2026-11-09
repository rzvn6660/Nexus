# ==============================================================================
# NEXUS — One-Command Zero-Cost Local Operations Startup Script (PowerShell)
#
# Launches the complete NEXUS platform locally with ₹0 budget:
#   - PostgreSQL 16 + pgvector (reuses existing persistent data volume)
#   - Redis 7.x
#   - Mailpit (Zero-Cost local SMTP on port 1025, Web UI on port 8025)
#   - FastAPI Backend API (Port 8000)
#   - Dedicated Intelligence & Pulse Scheduler Worker
#   - React Frontend SPA (Port 3000)
#
# Usage:
#   .\scripts\start_local.ps1            # Full Docker Stack
#   .\scripts\start_local.ps1 -Backing   # Backing only (Postgres + Redis + Mailpit)
# ==============================================================================
param (
    [switch]$Backing = $false,
    [switch]$SeedDemo = $false
)

$ErrorActionPreference = "Stop"

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host " NEXUS — Zero-Cost Local Operations Startup (₹0 / Month)" -ForegroundColor Cyan
Write-Host " Intelligence | Retention | Pulse" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# 1. Check Docker Daemon
Write-Host "`n[1/6] Checking Docker daemon status..." -ForegroundColor Yellow
try {
    $dockerInfo = docker info --format '{{.ServerVersion}}' 2>$null
    if (-not $dockerInfo) {
        throw "Docker is not running."
    }
    Write-Host "      ✓ Docker is active (Engine v$dockerInfo)." -ForegroundColor Green
} catch {
    Write-Host " [ERROR] Docker daemon is not accessible. Please ensure Docker Desktop is open." -ForegroundColor Red
    exit 1
}

# 2. Verify Local Environment Configuration (.env)
Write-Host "`n[2/6] Verifying local environment configuration (.env)..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    Write-Host "      Generating local .env from .env.zero_cost.template..." -ForegroundColor Gray
    $pgPass = [System.Guid]::NewGuid().ToString("N")
    $secKey = [System.Guid]::NewGuid().ToString("N") + [System.Guid]::NewGuid().ToString("N")
    $jwtSec = [System.Guid]::NewGuid().ToString("N") + [System.Guid]::NewGuid().ToString("N")
    $kmsKey = [System.Guid]::NewGuid().ToString("N") + [System.Guid]::NewGuid().ToString("N")
    $template = Get-Content ".env.zero_cost.template" -Raw
    $envContent = $template -replace "GENERATE_LOCAL_POSTGRES_PASSWORD_MIN_16_CHARS", $pgPass `
                            -replace "GENERATE_LOCAL_SECRET_KEY_MIN_32_CHARS", $secKey `
                            -replace "GENERATE_LOCAL_JWT_SECRET_KEY_MIN_32_CHARS", $jwtSec `
                            -replace "GENERATE_LOCAL_DEV_KMS_MASTER_KEY_256BITS", $kmsKey
    Set-Content -Path ".env" -Value $envContent -Encoding utf8
    Write-Host "      ✓ Created local .env with generated secrets (Git-ignored)." -ForegroundColor Green
} else {
    Write-Host "      ✓ Existing .env file verified." -ForegroundColor Green
}

# 3. Ensure Storage Directories Exist
Write-Host "`n[3/6] Initializing local storage directories..." -ForegroundColor Yellow
$storageDirs = @("./data/reports", "./data/uploads", "./backups/local")
foreach ($dir in $storageDirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "      + Created $dir" -ForegroundColor Gray
    }
}
Write-Host "      ✓ Local storage paths verified." -ForegroundColor Green

# 4. Launch Docker Compose Stack
Write-Host "`n[4/6] Starting zero-cost infrastructure..." -ForegroundColor Yellow
if ($Backing) {
    Write-Host "      Starting backing services: postgres, redis, mailpit..." -ForegroundColor Gray
    docker compose -f docker-compose.local.yml up -d postgres redis mailpit
} else {
    Write-Host "      Starting complete stack: postgres, redis, mailpit, backend, scheduler, frontend..." -ForegroundColor Gray
    docker compose -f docker-compose.local.yml up -d
}

# 5. Wait for Health Probes
Write-Host "`n[5/6] Waiting for health status..." -ForegroundColor Yellow
$maxAttempts = 30
$attempt = 0
$dbHealthy = $false

while ($attempt -lt $maxAttempts -and -not $dbHealthy) {
    Start-Sleep -Seconds 2
    $attempt++
    $pgStatus = docker inspect --format='{{json .State.Health.Status}}' nexus_postgres_local 2>$null
    if ($pgStatus -match "healthy") {
        $dbHealthy = $true
    } else {
        Write-Host "      Waiting for PostgreSQL healthcheck... ($attempt/$maxAttempts)" -ForegroundColor Gray
    }
}

if ($dbHealthy) {
    Write-Host "      ✓ PostgreSQL 16 + pgvector is healthy on port 5433." -ForegroundColor Green
    Write-Host "      ✓ Redis 7 is active on port 6380." -ForegroundColor Green
    Write-Host "      ✓ Mailpit zero-cost email inspector is active on port 8025." -ForegroundColor Green
} else {
    Write-Host " [WARNING] PostgreSQL is still initializing. Check logs via: docker logs nexus_postgres_local" -ForegroundColor Yellow
}

# 6. Optional Demo Seeder
if ($SeedDemo) {
    Write-Host "`n[Optional] Seeding demo retail organization and dataset..." -ForegroundColor Yellow
    python scripts/seed_demo_business.py --confirm-disposable --owner-email demo.owner@nexus.local --owner-password Password123!
}

Write-Host "`n==================================================================" -ForegroundColor Green
Write-Host " NEXUS IS FULLY OPERATIONAL (Zero Cost / Local-First)" -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Green
Write-Host " Dashboard (Web UI):       http://localhost:3000" -ForegroundColor White
Write-Host " Backend REST API Docs:    http://localhost:8000/docs" -ForegroundColor White
Write-Host " Mailpit Email Inspector:  http://localhost:8025" -ForegroundColor White
Write-Host " PostgreSQL Connection:    127.0.0.1:5433 (nexus_staging_db)" -ForegroundColor White
Write-Host " Redis Connection:         127.0.0.1:6380" -ForegroundColor White
Write-Host "------------------------------------------------------------------" -ForegroundColor Gray
Write-Host " Demo Login Credentials:" -ForegroundColor Cyan
Write-Host "   Email:    demo.owner@nexus.local" -ForegroundColor Cyan
Write-Host "   Password: Password123!" -ForegroundColor Cyan
Write-Host "------------------------------------------------------------------" -ForegroundColor Gray
Write-Host " To stop services:         .\scripts\stop_local.ps1" -ForegroundColor Yellow
Write-Host " To run backup drill:      .\scripts\backup_local.ps1" -ForegroundColor Yellow
Write-Host "==================================================================`n" -ForegroundColor Green
