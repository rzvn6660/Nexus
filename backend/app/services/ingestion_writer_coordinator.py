"""
NEXUS Phase 1J.3.2 — Ingestion Writer Coordinator Service.

Provides explicit, database-enforced writer coordination between concurrent
ingestion writers (sync adapters, webhook handlers, backfill workers) and
period-close snapshot generators/certifiers.

Uses PostgreSQL transaction-level advisory locks (pg_advisory_xact_lock)
and row-level checkpoint locks (SELECT ... FOR UPDATE) to establish an
unbypassable mutual exclusion boundary:

1. Ingestion Writers:
   Acquire shared transaction locks (pg_advisory_xact_lock_shared) for the period.
   Multiple ingestion workers can write concurrently across different streams,
   but are blocked whenever an exclusive period-close lock is active.

2. Period-Close Snapshot & Certification:
   Acquires exclusive transaction locks (pg_advisory_xact_lock) for the period.
   Completely excludes concurrent ingestion and backfill writes while evidence is
   being assembled, reconciled, signed, and certified.

3. Concurrency Mutation Detection:
   Enforces pre-signing and post-signing dataset identity verification. If any
   unauthorized mutation bypasses locks or commits concurrently, the process
   fails closed with SNAPSHOT_CONCURRENCY_MUTATION_DETECTED.
"""

import hashlib
import logging
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.connector import ConnectorSyncCheckpoint

logger = logging.getLogger(__name__)


class IngestionWriterCoordinator:
    """
    Database-level writer coordinator enforcing transactional isolation and mutual
    exclusion between ingestion pipelines and period-close evidence generation.
    """

    @classmethod
    def derive_lock_key(
        cls,
        business_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> int:
        """
        Derive a deterministic 64-bit signed integer lock key for PostgreSQL advisory locks.
        Enforces tenant isolation and period boundary validation.
        """
        if not business_id or not business_id.strip():
            raise ValueError("business_id cannot be empty or blank.")
        if period_end <= period_start:
            raise ValueError(
                f"period_end ({period_end.isoformat()}) must be strictly after period_start ({period_start.isoformat()})."
            )

        utc_start = (
            period_start if period_start.tzinfo is not None else period_start.replace(tzinfo=UTC)
        ).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        utc_end = (
            period_end if period_end.tzinfo is not None else period_end.replace(tzinfo=UTC)
        ).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        raw = f"nexus:period_close:{business_id.strip()}:{utc_start}:{utc_end}".encode()
        digest = hashlib.sha256(raw).digest()
        # 64-bit signed integer (-2^63 to 2^63 - 1)
        return int.from_bytes(digest[:8], byteorder="big", signed=True)

    @classmethod
    def acquire_period_close_lock(
        cls,
        session: Session,
        business_id: str,
        period_start: datetime,
        period_end: datetime,
        blocking: bool = True,
    ) -> bool:
        """
        Acquire exclusive transaction-level lock for period-close generation.
        Blocks concurrent ingestion and backfill writers for this period.
        """
        bind = session.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            # Fallback for non-PostgreSQL dialects (e.g. SQLite unit tests)
            return True

        lock_key = cls.derive_lock_key(business_id, period_start, period_end)
        if blocking:
            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": lock_key},
            )
            return True
        else:
            result = session.execute(
                text("SELECT pg_try_advisory_xact_lock(:key)"),
                {"key": lock_key},
            ).scalar()
            if not result:
                raise RuntimeError(
                    f"CONCURRENT_PERIOD_CLOSE_LOCKED: Exclusive lock could not be acquired for "
                    f"tenant '{business_id}' and period [{period_start.isoformat()} - {period_end.isoformat()}]. "
                    "Another worker or period-close process is active."
                )
            return bool(result)

    @classmethod
    def acquire_ingestion_lock(
        cls,
        session: Session,
        business_id: str,
        period_start: datetime,
        period_end: datetime,
        blocking: bool = True,
    ) -> bool:
        """
        Acquire shared transaction-level lock for source record ingestion / backfill.
        Permits concurrent ingestion across workers, but waits if exclusive period close is running.
        """
        bind = session.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return True

        lock_key = cls.derive_lock_key(business_id, period_start, period_end)
        if blocking:
            session.execute(
                text("SELECT pg_advisory_xact_lock_shared(:key)"),
                {"key": lock_key},
            )
            return True
        else:
            result = session.execute(
                text("SELECT pg_try_advisory_xact_lock_shared(:key)"),
                {"key": lock_key},
            ).scalar()
            if not result:
                raise RuntimeError(
                    f"PERIOD_CLOSE_IN_PROGRESS: Ingestion write locked for tenant '{business_id}' "
                    f"because period close is currently in progress."
                )
            return bool(result)

    @classmethod
    def lock_checkpoints_for_update(
        cls,
        session: Session,
        business_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> list[ConnectorSyncCheckpoint]:
        """
        Acquire row-level exclusive locks (SELECT ... FOR UPDATE) on all sync checkpoints
        intersecting the accounting period.
        """
        session.expire_all()
        checkpoints = session.execute(
            select(ConnectorSyncCheckpoint)
            .where(
                ConnectorSyncCheckpoint.business_id == business_id,
                ConnectorSyncCheckpoint.period_start <= period_end,
                ConnectorSyncCheckpoint.period_end >= period_start,
            )
            .with_for_update()
        ).scalars().all()
        return list(checkpoints)

    @classmethod
    def verify_snapshot_integrity(
        cls,
        initial_dataset_digest: str,
        current_dataset_digest: str,
    ) -> None:
        """
        Assert that the dataset digest computed during evidence generation matches the digest
        immediately before signing or certification.
        """
        if initial_dataset_digest != current_dataset_digest:
            raise RuntimeError(
                f"SNAPSHOT_CONCURRENCY_MUTATION_DETECTED: Dataset content was mutated concurrently. "
                f"Initial digest '{initial_dataset_digest}' != Current digest '{current_dataset_digest}'. "
                "Signing aborted to prevent inconsistent evidence generation."
            )

    @classmethod
    @contextmanager
    def coordinate_period_close(
        cls,
        session: Session,
        business_id: str,
        period_start: datetime,
        period_end: datetime,
        blocking: bool = True,
    ) -> Generator[None, None, None]:
        """
        Context manager that holds exclusive transaction advisory locks for the period.
        """
        cls.acquire_period_close_lock(
            session=session,
            business_id=business_id,
            period_start=period_start,
            period_end=period_end,
            blocking=blocking,
        )
        try:
            yield
        finally:
            # pg_advisory_xact_lock automatically releases on transaction commit/rollback
            pass

    @classmethod
    @contextmanager
    def coordinate_ingestion_write(
        cls,
        session: Session,
        business_id: str,
        period_start: datetime,
        period_end: datetime,
        blocking: bool = True,
    ) -> Generator[None, None, None]:
        """
        Context manager that holds shared transaction advisory locks during ingestion.
        """
        cls.acquire_ingestion_lock(
            session=session,
            business_id=business_id,
            period_start=period_start,
            period_end=period_end,
            blocking=blocking,
        )
        try:
            yield
        finally:
            pass
