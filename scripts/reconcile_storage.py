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
    args = parser.parse_args()

    print("=== NEXUS Tenant Storage Reconciliation ===")
    print(f"Mode: {'PURGE (orphans will be deleted)' if args.delete_orphans else 'DRY RUN (audit only, no files modified)'}")

    with SessionLocal() as db:
        base_path = Path(args.data_dir) if args.data_dir else None
        result = reconcile_tenant_storage(db=db, base_dir=base_path, delete_orphans=args.delete_orphans)

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
        return 0
    else:
        if not args.delete_orphans:
            print("\nWARNING: Inconsistencies detected. Rerun with --delete-orphans to prune orphaned files.")
        return 1 if result.missing_files else 0


if __name__ == "__main__":
    sys.exit(main())
