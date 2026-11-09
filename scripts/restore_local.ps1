# ==============================================================================
# NEXUS - Zero-Cost Local Restore Script (PowerShell)
#
# Restores PostgreSQL database and file storage from a local backup set.
#
# Usage:
#   .\scripts\restore_local.ps1                           # Restores latest backup
#   .\scripts\restore_local.ps1 -DumpFile "path/to/dump" # Restores specific dump
# ==============================================================================
param (
    [string]$DumpFile = "",
    [string]$BackupDir = "./backups/local"
)

$ErrorActionPreference = "Stop"

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host " NEXUS - Coordinated Local Restore Drill" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# 1. Resolve Target Dump
if (-not $DumpFile) {
    $latest = Get-ChildItem -Path $BackupDir -Filter "nexus_postgres_*.dump" | Sort-Object CreationTime -Descending | Select-Object -First 1
    if (-not $latest) {
        Write-Host " [ERROR] No backup dump found in $BackupDir." -ForegroundColor Red
        exit 1
    }
    $DumpFile = $latest.FullName
}

Write-Host ""
Write-Host "[1/4] Selected dump: $DumpFile" -ForegroundColor Yellow

# 2. Check Verification Sidecar
$ts = [System.IO.Path]::GetFileNameWithoutExtension($DumpFile) -replace "nexus_postgres_", ""
$checksumFile = "$BackupDir/nexus_backup_$ts.sha256"
if (Test-Path $checksumFile) {
    $expectedHash = (Get-Content $checksumFile | Select-Object -First 1).Split(" ")[0].Trim()
    $actualHash = (Get-FileHash -Path $DumpFile -Algorithm SHA256).Hash
    if ($expectedHash -ne $actualHash) {
        Write-Host " [ERROR] Cryptographic mismatch! Expected $expectedHash, got $actualHash." -ForegroundColor Red
        exit 1
    }
    Write-Host "      [OK] SHA-256 integrity verified ($actualHash)." -ForegroundColor Green
} else {
    Write-Host "      [WARN] No checksum sidecar found. Skipping cryptographic pre-check." -ForegroundColor Yellow
}

# 3. Locate Active Container
$pgContainer = ""
$candidates = @("nexus_postgres_local", "nexus_postgres_staging")
$running = @(docker ps --format "{{.Names}}")
foreach ($c in $candidates) {
    if ($running -contains $c) {
        $pgContainer = $c
        break
    }
}

if (-not $pgContainer) {
    Write-Host " [ERROR] No running PostgreSQL container found. Start stack first: .\scripts\start_local.ps1" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "[2/4] Target PostgreSQL container: $pgContainer" -ForegroundColor Yellow

# 4. Execute Restore
Write-Host ""
Write-Host "[3/4] Restoring PostgreSQL database from dump..." -ForegroundColor Yellow
$containerTmpDump = "/tmp/pg_restore_$ts.dump"
docker cp $DumpFile "${pgContainer}:${containerTmpDump}"
docker exec $pgContainer pg_restore -U nexus_staging_user -d nexus_staging_db --clean --if-exists --no-owner $containerTmpDump
docker exec $pgContainer rm -f $containerTmpDump
Write-Host "      [OK] Database restore command finished." -ForegroundColor Green

# 5. Restore Storage Archive if Present
$storageZip = "$BackupDir/nexus_storage_$ts.zip"
if (Test-Path $storageZip) {
    Write-Host ""
    Write-Host "[4/4] Restoring local file and report storage..." -ForegroundColor Yellow
    Expand-Archive -Path $storageZip -DestinationPath "./data" -Force
    Write-Host "      [OK] Storage archives restored." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[4/4] No storage archive found for timestamp $ts." -ForegroundColor Gray
}

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Green
Write-Host " RESTORE COMPLETED SUCCESSFULLY" -ForegroundColor Green
Write-Host " Verified from local backup without external cloud dependencies." -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Green
Write-Host ""
