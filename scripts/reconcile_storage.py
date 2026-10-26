#!/usr/bin/env python
"""NEXUS Storage Reconciliation & Orphan Cleanup Utility (Phase 32C).

Cross-references PostgreSQL metadata (storage_key) against persistent tenant files on disk.

Operational Modes:
- Audit / Dry-Run (DEFAULT): Reports missing disk files and unindexed orphaned files without mutating disk.
- Purge (--delete-orphans): Removes confirmed orphan files and prunes empty parent directories up to tenants root.

Usage:
  python scripts/reconcile_storage.py                  # Audit / dry-run mode (safe)
  python scripts/reconcile_storage.py --delete-orphans # Explicit operator purge confirmation
"""

import argparse
import os
import sys
from pathlib import Path

# Setup sys.path for backend imports
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

backend_dir = project_root / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.database import SessionLocal  # noqa: E402
from app.core.backup import reconcile_tenant_storage  # noqa: E402


def _redact_credentials(message: str, url_hint: str | None = None) -> str:
    """Redact passwords and sensitive credentials from error messages."""
    import re
    import urllib.parse
    redacted = message
    if url_hint:
        try:
            from sqlalchemy.engine import make_url
            u = make_url(url_hint)
            if u.password:
                redacted = redacted.replace(u.password, "******")
                q_pw = urllib.parse.quote(u.password)
                if q_pw and q_pw != u.password:
                    redacted = redacted.replace(q_pw, "******")
                qp_pw = urllib.parse.quote_plus(u.password)
                if qp_pw and qp_pw != u.password:
                    redacted = redacted.replace(qp_pw, "******")
        except Exception:
            pass
    return re.sub(r"://([^:@/]+):([^@/]+)@", r"://\1:******@", redacted)


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXUS Storage Reconciliation & Orphan Cleanup")
    parser.add_argument(
        "--delete-orphans",
        action="store_true",
        default=os.getenv("DELETE_ORPHANS", "false").lower() in ("true", "1", "yes"),
        help="Explicitly enable unindexed orphan file deletion (default: false, dry-run only)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Custom base data directory path (defaults to settings.DATA_DIR)",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Custom database connection URL override (defaults to settings.DATABASE_URL)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output reconciliation result as machine-readable JSON",
    )
    args = parser.parse_args()

    try:
        if args.database_url:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            custom_engine = create_engine(args.database_url)
            CustomSession = sessionmaker(autocommit=False, autoflush=False, bind=custom_engine)
            session_factory = CustomSession
        else:
            session_factory = SessionLocal

        with session_factory() as db:
            base_path = Path(args.data_dir) if args.data_dir else None
            result = reconcile_tenant_storage(db=db, base_dir=base_path, delete_orphans=args.delete_orphans)
    except Exception as exc:
        err_msg = _redact_credentials(str(exc), args.database_url)
        if args.json:
            import json
            print(json.dumps({
                "status": "error",
                "error_type": type(exc).__name__,
                "message": err_msg,
                "is_consistent": False,
            }))
        else:
            print(f"\nERROR: Storage reconciliation failed with execution/connection error: {type(exc).__name__}: {err_msg}", file=sys.stderr)
        return 2

    if args.json:
        import json
        payload = result.to_dict()
        payload["status"] = "consistent" if result.is_consistent else "inconsistent"
        print(json.dumps(payload, indent=2))
    else:
        print("=== NEXUS Tenant Storage Reconciliation ===")
        print(f"Mode: {'PURGE (orphans will be deleted)' if args.delete_orphans else 'DRY RUN (audit only, no files modified)'}")
        print(f"\n[Authoritative DB Records]: {result.total_db_records}")
        print(f"[Physical Files on Disk]  : {result.total_disk_files}")
        print(f"[Missing Database Files]  : {len(result.missing_files)}")
        for missing in result.missing_files[:5]:
            print(f"  - ID: {missing[0]}, file: {missing[1]}, key: {missing[2]}")

        print(f"[Unindexed Orphan Files]  : {len(result.orphan_files)}")
        for orphan in result.orphan_files[:10]:
            print(f"  - Orphan: {orphan} ({orphan.stat().st_size if orphan.exists() else 0} bytes)")

        if args.delete_orphans:
            print(f"[Purged Orphan Files]     : {len(result.purged_files)}")

        if result.is_consistent:
            print("\nSUCCESS: Storage is 100% consistent with database records.")
        else:
            if not args.delete_orphans:
                print("\nWARNING: Inconsistencies detected. Rerun with --delete-orphans to prune orphaned files.")

    return 0 if result.is_consistent else 1


if __name__ == "__main__":
    sys.exit(main())
