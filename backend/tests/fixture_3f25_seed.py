# NEXUS Phase 3F.25 — Isolated Recovery Fixture Seed Helper
#
# Provides deterministic fixture constants and a builder function for the
# nexus_fixture_staging_db recovery drill.
#
# Design: Zero DB connections. Stable deterministic UUIDs.
# Storage key format: tenants/{org_id}/{biz_id}/{ds_id}/{filename}
# Caller must: create directories, write CSV file, add ORM objects, commit.
# Forbidden: create_engine, sessionmaker, docker, psql, pg_dump, pg_restore.

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Fixed resource names (Phase 3F.25 contract — do NOT change)
# ---------------------------------------------------------------------------

FIXTURE_SOURCE_DB = "nexus_fixture_staging_db"
FIXTURE_SOURCE_VOLUME = "nexus_backend_fixture_staging_data"
FIXTURE_BACKUP_DIR = os.getenv(
    "NEXUS_FIXTURE_BACKUP_DIR",
    "/var/backups/nexus_fixture_staging"
    if os.name != "nt"
    else str(Path.home() / "nexus_backups_fixture_staging"),
)

FIXTURE_RESTORE_DB = "nexus_disposable_fixture_staging_db"
FIXTURE_RESTORE_VOLUME = "nexus_backend_disposable_fixture_staging_data"
FIXTURE_RESTORE_REDIS_VOLUME = "nexus_redis_disposable_fixture_staging_data"

# ---------------------------------------------------------------------------
# Supported PostgreSQL Drivers (Phase 3F.25 contract)
# ---------------------------------------------------------------------------

ALLOWED_POSTGRESQL_DRIVERS: frozenset[str] = frozenset(
    {
        "postgresql",
        "postgresql+psycopg",
        "postgresql+psycopg2",
        "postgresql+asyncpg",
        "postgres",
    }
)

# ---------------------------------------------------------------------------
# Deterministic UUIDs — stable identifiers for reproducible assertions
# ---------------------------------------------------------------------------

FIXTURE_ORG_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
FIXTURE_BIZ_ID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
FIXTURE_DS_ID  = "c3d4e5f6-a7b8-9012-cdef-123456789012"
FIXTURE_JOB_ID = "d4e5f6a7-b8c9-0123-def0-234567890123"

FIXTURE_ORG_SLUG = "fixture-drill-org"
FIXTURE_CSV_FILENAME = "fixture_sales.csv"

# Fixed CSV payload — two rows, three columns, deterministic bytes.
FIXTURE_CSV_CONTENT: bytes = (
    b"order_id,amount,date\n"
    b"ORD-F001,125.50,2026-01-01\n"
    b"ORD-F002,230.00,2026-01-02\n"
)

# Pre-computed SHA-256. Test test_sha256_constant_is_correct verifies this at
# runtime against hashlib.sha256(FIXTURE_CSV_CONTENT).hexdigest().
FIXTURE_CSV_SHA256: str = "c5397bc984c796833333e6836e672bdb66978cb6f73033354c3ca35e887b19cd"
FIXTURE_CSV_ROW_COUNT: int = 2
FIXTURE_CSV_COLUMN_COUNT: int = 3


def build_storage_key(org_id: str, biz_id: str, ds_id: str, filename: str) -> str:
    """Return canonical storage_key for reconciliation.

    Format: tenants/{org_id}/{biz_id}/{ds_id}/{filename}
    Mirrors DataGatewayService convention (no leading slash, forward slashes).
    """
    return f"tenants/{org_id}/{biz_id}/{ds_id}/{filename}"


def build_fixture_records(data_dir: Path):
    """Build one consistent set of ORM objects and the expected CSV path.

    Args:
        data_dir: Base data directory (volume mount root or tmp_path in tests).
                  No directories are created; no files are written here.

    Returns:
        Five-tuple (org, biz, ds, job, csv_path).

        Caller responsibilities:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_bytes(FIXTURE_CSV_CONTENT)
            session.add_all([org, biz]); session.flush()
            session.add_all([ds, job]); session.commit()
    """
    from app.models.tenant import (  # noqa: PLC0415
        Business,
        IngestionJob,
        Organization,
        UploadedDataset,
    )

    sk = build_storage_key(
        FIXTURE_ORG_ID, FIXTURE_BIZ_ID, FIXTURE_DS_ID, FIXTURE_CSV_FILENAME
    )

    org = Organization(
        id=FIXTURE_ORG_ID,
        name="Fixture Drill Organization",
        slug=FIXTURE_ORG_SLUG,
        status="active",
    )
    biz = Business(
        id=FIXTURE_BIZ_ID,
        organization_id=FIXTURE_ORG_ID,
        name="Fixture Drill Business",
        status="active",
    )
    ds = UploadedDataset(
        id=FIXTURE_DS_ID,
        organization_id=FIXTURE_ORG_ID,
        business_id=FIXTURE_BIZ_ID,
        filename=FIXTURE_CSV_FILENAME,
        file_type="csv",
        storage_key=sk,
        file_size_bytes=len(FIXTURE_CSV_CONTENT),
        row_count=FIXTURE_CSV_ROW_COUNT,
        column_count=FIXTURE_CSV_COLUMN_COUNT,
        content_hash=FIXTURE_CSV_SHA256,
        schema_json={
            "columns": ["order_id", "amount", "date"],
            "phase": "3f25_fixture",
            "drill_marker": "jsonb_fixture_test",
        },
        readiness_status="READY",
    )
    job = IngestionJob(
        id=FIXTURE_JOB_ID,
        organization_id=FIXTURE_ORG_ID,
        business_id=FIXTURE_BIZ_ID,
        dataset_id=FIXTURE_DS_ID,
        status="COMPLETED",
        target_entity="Sale",
        started_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc),
        rows_processed=FIXTURE_CSV_ROW_COUNT,
        error_message=None,
    )

    csv_path = (
        data_dir
        / "tenants"
        / FIXTURE_ORG_ID
        / FIXTURE_BIZ_ID
        / FIXTURE_DS_ID
        / FIXTURE_CSV_FILENAME
    )

    return org, biz, ds, job, csv_path


# ---------------------------------------------------------------------------
# Redis marker constants
# ---------------------------------------------------------------------------

FIXTURE_REDIS_MARKER_KEY: str = "nexus:drill:phase3f25:marker"
FIXTURE_REDIS_MARKER_VALUE: str = "fixture_redis_marker_verified_20261025"


# ---------------------------------------------------------------------------
# Idempotent fixture seeding and verification
# ---------------------------------------------------------------------------


def seed_fixture_records(
    session,
    data_dir: Path,
    *,
    fail_if_exists: bool = False,
):
    """Seed the isolated fixture records and physical CSV in a safe, idempotent manner.

    Args:
        session: Active SQLAlchemy Session.
        data_dir: Path to base tenant data directory.
        fail_if_exists: If True, raise RuntimeError if fixture org already exists.

    Returns:
        Six-tuple: (org, biz, ds, job, csv_path, status_str)
        where status_str is 'seeded_fresh' or 'already_seeded'.
    """
    from app.models.tenant import (  # noqa: PLC0415
        Business,
        IngestionJob,
        Organization,
        UploadedDataset,
    )

    org, biz, ds, job, csv_path = build_fixture_records(data_dir)

    existing_org = session.get(Organization, FIXTURE_ORG_ID)
    if existing_org is not None:
        if fail_if_exists:
            raise RuntimeError(
                f"SAFETY ERROR: Pre-existing fixture organization '{FIXTURE_ORG_ID}' "
                "detected while fail_if_exists=True."
            )
        existing_ds = session.get(UploadedDataset, FIXTURE_DS_ID)
        if existing_ds is None or existing_ds.content_hash != FIXTURE_CSV_SHA256:
            raise RuntimeError(
                f"SAFETY ERROR: Conflicting pre-existing state for dataset '{FIXTURE_DS_ID}'."
            )
        if not csv_path.exists():
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_bytes(FIXTURE_CSV_CONTENT)
        elif csv_path.read_bytes() != FIXTURE_CSV_CONTENT:
            raise RuntimeError(
                f"SAFETY ERROR: Physical CSV content at '{csv_path}' does not match expected fixture content."
            )
        return existing_org, biz, existing_ds, job, csv_path, "already_seeded"

    file_existed_prior = csv_path.exists()
    csv_created_here = False
    if not file_existed_prior:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_bytes(FIXTURE_CSV_CONTENT)
        csv_created_here = True
    elif csv_path.read_bytes() != FIXTURE_CSV_CONTENT:
        csv_path.write_bytes(FIXTURE_CSV_CONTENT)
        # Note: file existed prior; do not mark as created here so rollback preserves it

    try:
        session.add(org)
        session.add(biz)
        session.flush()
        session.add(ds)
        session.add(job)
        session.commit()
    except Exception:
        session.rollback()
        if csv_created_here and csv_path.exists():
            try:
                csv_path.unlink()
            except OSError:
                pass
        raise

    return org, biz, ds, job, csv_path, "seeded_fresh"


def verify_fixture_integrity(session, data_dir: Path) -> dict[str, object]:
    """Verify that all fixture ORM rows and the physical CSV file exist and match exactly."""
    from app.models.tenant import (  # noqa: PLC0415
        Business,
        IngestionJob,
        Organization,
        UploadedDataset,
    )

    org = session.get(Organization, FIXTURE_ORG_ID)
    if not org or org.slug != FIXTURE_ORG_SLUG:
        return {"verified": False, "error": f"Organization '{FIXTURE_ORG_ID}' missing or invalid"}

    biz = session.get(Business, FIXTURE_BIZ_ID)
    if not biz or biz.organization_id != FIXTURE_ORG_ID:
        return {"verified": False, "error": f"Business '{FIXTURE_BIZ_ID}' missing or invalid FK"}

    ds = session.get(UploadedDataset, FIXTURE_DS_ID)
    if not ds or ds.content_hash != FIXTURE_CSV_SHA256 or ds.file_size_bytes != len(FIXTURE_CSV_CONTENT):
        return {"verified": False, "error": f"Dataset '{FIXTURE_DS_ID}' missing or corrupted"}

    job = session.get(IngestionJob, FIXTURE_JOB_ID)
    if not job or job.dataset_id != FIXTURE_DS_ID:
        return {"verified": False, "error": f"IngestionJob '{FIXTURE_JOB_ID}' missing or invalid FK"}

    expected_csv = (
        data_dir
        / "tenants"
        / FIXTURE_ORG_ID
        / FIXTURE_BIZ_ID
        / FIXTURE_DS_ID
        / FIXTURE_CSV_FILENAME
    )
    if not expected_csv.exists():
        return {"verified": False, "error": f"CSV file missing on disk at '{expected_csv}'"}

    actual_bytes = expected_csv.read_bytes()
    if hashlib.sha256(actual_bytes).hexdigest() != FIXTURE_CSV_SHA256:
        return {"verified": False, "error": f"CSV SHA-256 mismatch at '{expected_csv}'"}

    return {
        "verified": True,
        "org_id": org.id,
        "business_id": biz.id,
        "dataset_id": ds.id,
        "job_id": job.id,
        "csv_path": str(expected_csv),
        "file_size_bytes": len(actual_bytes),
        "sha256": FIXTURE_CSV_SHA256,
    }


def main(argv: list[str] | None = None) -> int:
    """Safe CLI runner for fixture seeding and integrity verification."""
    import argparse
    import sys
    from sqlalchemy.engine import make_url  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="NEXUS Phase 3F.25 Fixture Seeder")
    parser.add_argument("--data-dir", type=Path, default=Path("/app/data"), help="Root data directory")
    parser.add_argument("--database-url", type=str, default=None, help="Database connection URL")
    parser.add_argument("--fail-if-exists", action="store_true", help="Fail if fixture data already exists")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing fixture integrity")
    parser.add_argument("--dry-run", action="store_true", help="Print fixture plan and exit 0 without connecting")

    args = parser.parse_args(argv)

    if args.dry_run:
        masked_url = "NOT_SPECIFIED"
        if args.database_url:
            try:
                parsed_dry = make_url(args.database_url)
                masked_url = parsed_dry.render_as_string(hide_password=True)
            except Exception:
                masked_url = "[MALFORMED_URL]"
        print(f"PLAN: Target DB URL: {masked_url}")
        print(f"PLAN: Data directory: {args.data_dir}")
        print(f"PLAN: Fixture Org ID: {FIXTURE_ORG_ID} ({FIXTURE_ORG_SLUG})")
        print(f"PLAN: Fixture Dataset ID: {FIXTURE_DS_ID} ({FIXTURE_CSV_FILENAME})")
        print(f"PLAN: Expected CSV: {args.data_dir}/tenants/{FIXTURE_ORG_ID}/{FIXTURE_BIZ_ID}/{FIXTURE_DS_ID}/{FIXTURE_CSV_FILENAME}")
        return 0

    if not args.database_url:
        print("ERROR: --database-url is required when not in --dry-run mode.", file=sys.stderr)
        return 1

    # Strict isolation gate & driver/scheme validation
    try:
        url = make_url(args.database_url)
    except Exception as exc:
        print(f"SAFETY ERROR: Malformed database URL: {type(exc).__name__}", file=sys.stderr)
        return 1

    if url.drivername not in ALLOWED_POSTGRESQL_DRIVERS:
        print(
            f"SAFETY ERROR: Unauthorized driver '{url.drivername}'. "
            f"Allowed PostgreSQL drivers: {sorted(ALLOWED_POSTGRESQL_DRIVERS)}",
            file=sys.stderr,
        )
        return 1

    db_name = url.database
    allowed_dbs = {FIXTURE_SOURCE_DB, FIXTURE_RESTORE_DB}
    if not db_name or db_name not in allowed_dbs:
        print(
            f"SAFETY ERROR: Target database '{db_name}' is not an authorized fixture database. "
            f"Allowed databases: {allowed_dbs}",
            file=sys.stderr,
        )
        return 1

    from sqlalchemy import create_engine  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    try:
        engine = create_engine(args.database_url)
        with Session(engine) as session:
            if args.verify_only:
                result = verify_fixture_integrity(session, args.data_dir)
                if not result.get("verified"):
                    print(f"VERIFY FAILED: {result.get('error')}", file=sys.stderr)
                    return 1
                print(f"VERIFY PASSED: {result}")
                return 0

            _, _, _, _, csv_path, status = seed_fixture_records(
                session, args.data_dir, fail_if_exists=args.fail_if_exists
            )
            print(f"FIXTURE SEED STATUS: {status} at '{csv_path}'")
            return 0
    except Exception as exc:
        sanitized_target = url.render_as_string(hide_password=True)
        print(
            f"DATABASE ERROR: Failed connecting to or executing against {sanitized_target}: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
