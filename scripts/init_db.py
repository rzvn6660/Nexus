"""Database initialization and connectivity verification script."""

import os
import sys

# Ensure backend root is on sys.path
backend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, backend_path)

from app.core.config import settings
from app.core.database import check_database_connection, engine
from app.models.base import Base


def main() -> None:
    """Check connectivity and create registered ORM tables if needed."""
    print("=" * 60)
    print("NEXUS -- Database Initialization")
    print("=" * 60)

    print(f"Connecting to database at: {settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}")

    status = check_database_connection()
    if status.get("status") == "connected":
        print(f"[OK] Database connection established (latency: {status.get('latency_ms')}ms)")
        print("[INFO] Creating registered tables if not present...")
        Base.metadata.create_all(bind=engine)
        print("[OK] Schema initialization complete.")
    else:
        print(f"[WARNING] Could not connect to database: {status.get('error')}")
        print("[INFO] If running locally without Docker, start PostgreSQL or run: docker compose up -d postgres")


if __name__ == "__main__":
    main()
