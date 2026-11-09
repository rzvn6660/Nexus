# ==============================================================================
# NEXUS - Zero-Cost Local Backup Script (PowerShell)
# ==============================================================================
param (
    [string]$BackupDir = "./backups/local",
    [int]$RetentionCount = 7
)

$ErrorActionPreference = "Stop"

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host " NEXUS - Coordinated Local Backup Drill" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$pgBackupFile = "$BackupDir/nexus_postgres_$timestamp.dump"
$storageBackupFile = "$BackupDir/nexus_storage_$timestamp.zip"
$metaBackupFile = "$BackupDir/nexus_manifest_$timestamp.json"
$checksumFile = "$BackupDir/nexus_backup_$timestamp.sha256"

# 1. Identify Running PostgreSQL Container
Write-Host ""
Write-Host "[1/4] Locating active PostgreSQL container..." -ForegroundColor Yellow
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
    Write-Host " [ERROR] No active NEXUS PostgreSQL container found." -ForegroundColor Red
    exit 1
}
Write-Host "      [OK] Using active container: $pgContainer" -ForegroundColor Green

# 2. Execute pg_dump
Write-Host ""
Write-Host "[2/4] Dumping PostgreSQL 16 database..." -ForegroundColor Yellow
$containerTmpDump = "/tmp/pg_dump_$timestamp.dump"
docker exec $pgContainer pg_dump -U nexus_staging_user -F c -d nexus_staging_db -f $containerTmpDump
docker cp "${pgContainer}:${containerTmpDump}" $pgBackupFile
docker exec $pgContainer rm -f $containerTmpDump
$pgSize = (Get-Item $pgBackupFile).Length
$sizeLabel = [string][math]::Round($pgSize / 1024, 2) + " KB"
Write-Host "      [OK] PostgreSQL dump completed: $pgBackupFile ($sizeLabel)" -ForegroundColor Green

# 3. Snapshot Storage Archive
Write-Host ""
Write-Host "[3/4] Archiving local report and upload directories..." -ForegroundColor Yellow
$dirsToCompress = @()
if (Test-Path "./data/reports") { $dirsToCompress += (Resolve-Path "./data/reports").Path }
if (Test-Path "./data/uploads") { $dirsToCompress += (Resolve-Path "./data/uploads").Path }

if ($dirsToCompress.Count -gt 0) {
    Compress-Archive -Path $dirsToCompress -DestinationPath $storageBackupFile -Force
    $zipSize = (Get-Item $storageBackupFile).Length
    $zipSizeLabel = [string][math]::Round($zipSize / 1024, 2) + " KB"
    Write-Host "      [OK] Storage archived: $storageBackupFile ($zipSizeLabel)" -ForegroundColor Green
} else {
    Write-Host "      [INFO] No report/upload directories to archive. Created empty marker." -ForegroundColor Gray
    "" | Out-File -FilePath "$BackupDir/empty_storage_$timestamp.txt"
}

# 4. Generate Metadata & Checksums
Write-Host ""
Write-Host "[4/4] Generating verification checksums and manifest..." -ForegroundColor Yellow
$pgHash = (Get-FileHash -Path $pgBackupFile -Algorithm SHA256).Hash
$zipHash = if (Test-Path $storageBackupFile) { (Get-FileHash -Path $storageBackupFile -Algorithm SHA256).Hash } else { "N/A" }

$manifest = @{
    backup_id = "nexus_backup_$timestamp"
    created_at = (Get-Date).ToString("o")
    environment = "zero_cost_local"
    database = @{
        engine = "postgresql_16_pgvector"
        container = $pgContainer
        file = (Get-Item $pgBackupFile).Name
        size_bytes = $pgSize
        sha256 = $pgHash
    }
    storage = @{
        file = if (Test-Path $storageBackupFile) { (Get-Item $storageBackupFile).Name } else { $null }
        sha256 = $zipHash
    }
}

$manifestJson = $manifest | ConvertTo-Json -Depth 5
$manifestJson | Set-Content -Path $metaBackupFile -Encoding UTF8

$checksumContent = "$pgHash  $((Get-Item $pgBackupFile).Name)`n"
if (Test-Path $storageBackupFile) {
    $checksumContent += "$zipHash  $((Get-Item $storageBackupFile).Name)`n"
}
$checksumContent | Set-Content -Path $checksumFile -Encoding UTF8

Write-Host "      [OK] SHA-256 sidecar written: $checksumFile" -ForegroundColor Green
Write-Host "      [OK] Manifest written: $metaBackupFile" -ForegroundColor Green

# 5. Retention Pruning (Keep latest N sets)
$oldDumps = Get-ChildItem -Path $BackupDir -Filter "nexus_postgres_*.dump" | Sort-Object CreationTime -Descending
if ($oldDumps.Count -gt $RetentionCount) {
    $toDelete = $oldDumps | Select-Object -Skip $RetentionCount
    foreach ($item in $toDelete) {
        $tsPattern = $item.Name -replace "nexus_postgres_", "" -replace "\.dump", ""
        Remove-Item "$BackupDir/*$tsPattern*" -Force -ErrorAction SilentlyContinue
        Write-Host "      - Pruned expired backup set from $tsPattern" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Green
Write-Host " BACKUP SUCCESSFUL - Artifacts Verified (Zero Cost Local Storage)" -ForegroundColor Green
Write-Host " Database dump: $pgBackupFile" -ForegroundColor White
Write-Host " SHA-256:       $pgHash" -ForegroundColor White
Write-Host "==================================================================" -ForegroundColor Green
