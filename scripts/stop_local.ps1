# ==============================================================================
# NEXUS — Zero-Cost Local Operations Shutdown Script (PowerShell)
#
# Safely stops NEXUS local services without destroying volumes or deleting data.
# ==============================================================================
param (
    [switch]$KeepData = $true
)

Write-Host "Stopping NEXUS Zero-Cost Local Operations stack..." -ForegroundColor Yellow
docker compose -f docker-compose.local.yml stop

Write-Host "`n✓ NEXUS services stopped successfully." -ForegroundColor Green
Write-Host "  Database and cache data volumes are preserved intact." -ForegroundColor Gray
Write-Host "  To restart: .\scripts\start_local.ps1`n" -ForegroundColor Cyan
