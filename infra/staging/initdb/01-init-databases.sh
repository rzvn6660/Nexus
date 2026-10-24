#!/bin/bash
set -euo pipefail

# ==============================================================================
# NEXUS Staging PostgreSQL Initialization Script
#
# Mounted into /docker-entrypoint-initdb.d/ to run on initial database cluster
# initialization (FRESH VOLUME ONLY).
#
# IMPORTANT LIFECYCLE NOTE:
# The official PostgreSQL Docker entrypoint executes /docker-entrypoint-initdb.d/*
# scripts ONLY when the database data directory (/var/lib/postgresql/data) is completely
# empty (fresh volume). If PGDATA already contains an initialized cluster (existing
# volume or restored state), this directory is skipped entirely. Any post-restore
# verification against an existing volume must ensure nexus_test_db exists independently.
# ==============================================================================

echo "[initdb] Initializing NEXUS Staging databases..."

# 1. Enable pgvector on the primary staging database
echo "[initdb] Enabling vector extension on primary staging database: ${POSTGRES_DB}..."
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL

# 2. Provision dedicated test database 'nexus_test_db' required by test gate
echo "[initdb] Provisioning dedicated test database 'nexus_test_db'..."
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "postgres" <<-EOSQL
    SELECT 'CREATE DATABASE nexus_test_db OWNER ' || quote_ident('${POSTGRES_USER}')
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'nexus_test_db')\gexec
    GRANT ALL PRIVILEGES ON DATABASE nexus_test_db TO "${POSTGRES_USER}";
EOSQL

# 3. Enable pgvector on 'nexus_test_db'
echo "[initdb] Enabling vector extension on test database: nexus_test_db..."
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "nexus_test_db" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL

echo "[initdb] PostgreSQL staging initialization complete. Databases '${POSTGRES_DB}' and 'nexus_test_db' ready with pgvector."
