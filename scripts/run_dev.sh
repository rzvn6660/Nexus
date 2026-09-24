#!/usr/bin/env bash
set -e

echo "=================================================="
echo "Starting NEXUS Local Development Environment"
echo "=================================================="

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "[INFO] Creating .env from .env.example..."
    cp .env.example .env
fi

# Start Docker containers if Docker is available
if command -v docker >/dev/null 2>&1; then
    echo "[INFO] Starting PostgreSQL via Docker Compose..."
    docker compose up -d postgres
else
    echo "[WARNING] Docker not detected. Ensure local PostgreSQL is running on port 5432."
fi

# Run backend
echo "[INFO] Starting FastAPI backend on http://localhost:8000..."
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
