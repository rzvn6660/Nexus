@echo off
echo ==================================================
echo Starting NEXUS Local Development Environment
echo ==================================================

if not exist ".env" (
    echo [INFO] Copying .env.example to .env...
    copy .env.example .env
)

where docker >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo [INFO] Starting PostgreSQL container...
    docker compose up -d postgres
) else (
    echo [WARNING] Docker not found in PATH. Ensure PostgreSQL is running on port 5432.
)

echo [INFO] Starting NEXUS Backend server...
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
