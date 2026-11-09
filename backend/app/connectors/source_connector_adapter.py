"""
NEXUS Phase 1J.1 — Provider-Neutral Source Connector Adapter Interface.

Defines the abstract base class and typed contracts for all upstream commercial data source connectors.
Follows the Authoritative Source Completeness Contract (Phase 1J.0 Architecture).
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
from typing import Any, Dict, Iterator, List, Optional

from app.schemas.source_sync import (
    ConnectionHealth,
    ConnectorAuthStatus,
    ExtractionPage,
    ExtractedRecord,
    PeriodCloseEvidence,
    SourceMetadata,
    SyncCheckpoint,
)


class SourceConnectorAdapter(ABC):
    """
    Abstract base class for all upstream data source connectors in NEXUS.

    Enforces uniform authentication, pagination verification, cursor hash chaining,
    period-close evidence extraction, and webhook signature verification.
    """

    def __init__(self, tenant_credentials: Dict[str, Any], business_id: str):
        """
        Initialize the connector adapter with tenant credentials and tenant isolation boundary.
        Credentials must be validated before executing data operations.
        """
        self.credentials = tenant_credentials
        self.business_id = business_id

    @abstractmethod
    def get_auth_status(self) -> ConnectorAuthStatus:
        """
        Query and verify the current authentication status and granted scopes.
        Does not mutate remote state.
        """
        pass

    @abstractmethod
    def validate_connection(self) -> bool:
        """
        Verify that the source platform is reachable, credentials are valid,
        and required permission scopes are present.
        """
        pass

    @abstractmethod
    def get_metadata(self) -> SourceMetadata:
        """
        Retrieve provider discovery metadata, supported sync modes, settlement type,
        default currency, and timezone.
        """
        pass

    @abstractmethod
    def check_health(self) -> ConnectionHealth:
        """
        Perform a live lightweight health check against the upstream platform.
        Measures latency, checks quota/rate limits, and classifies errors.
        """
        pass

    @abstractmethod
    def fetch_transactions_page(
        self,
        period_start: datetime,
        period_end: datetime,
        cursor: Optional[str] = None,
        page_size: int = 100,
        previous_chain_hash: Optional[str] = None,
    ) -> ExtractionPage:
        """
        Fetch a single deterministic paginated page of transactions within the period.
        Must return an ExtractionPage containing records, next_cursor, has_more, and cursor_chain_hash.
        """
        pass

    @abstractmethod
    def stream_historical(
        self,
        period_start: datetime,
        period_end: datetime,
        checkpoint: Optional[SyncCheckpoint] = None,
    ) -> Iterator[ExtractedRecord]:
        """
        Stream all historical transactions within [period_start, period_end] sequentially.
        Must handle cursor progression and update checkpoint state.
        """
        pass

    @abstractmethod
    def stream_incremental(
        self,
        since: datetime,
        checkpoint: Optional[SyncCheckpoint] = None,
    ) -> Iterator[ExtractedRecord]:
        """
        Stream transactions updated or created since the given timestamp.
        """
        pass

    @abstractmethod
    def fetch_period_close_evidence(
        self,
        period_identifier: str,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> Optional[PeriodCloseEvidence]:
        """
        Retrieve independently authenticated period-close or settlement evidence
        from the upstream platform (e.g. Stripe Payout, QBO ClosingDate, or synthetic close).
        Returns None if the source does not support period-close locks.
        """
        pass

    @abstractmethod
    def verify_event_signature(
        self,
        headers: Dict[str, str],
        body_bytes: bytes,
        secret: str,
    ) -> bool:
        """
        Verify provider webhook or event signature using timing-safe comparison.
        Returns True if authentic and within tolerance window, False otherwise.
        """
        pass

    @abstractmethod
    def refresh_credentials(self) -> Optional[Dict[str, Any]]:
        """
        Perform automated OAuth token refresh if access token is near expiration.
        Returns updated credential dictionary for secure re-encryption, or None if unchanged.
        """
        pass

    @staticmethod
    def compute_cursor_chain_hash(previous_chain_hash: str, current_cursor: Optional[str]) -> str:
        """
        Compute the deterministic rolling SHA-256 cursor chain hash:
        H_0 = sha256("ROOT"), H_k = sha256(H_{k-1} || cursor)
        """
        cursor_token = current_cursor or "TERMINAL_PAGE"
        combined = f"{previous_chain_hash}||{cursor_token}".encode("utf-8")
        return hashlib.sha256(combined).hexdigest()

    @staticmethod
    def compute_transaction_set_digest(transaction_ids: List[str]) -> str:
        """
        Compute deterministic SHA-256 digest of lexicographically sorted transaction IDs:
        sha256("||".join(sorted(ids)))
        """
        sorted_ids = sorted(transaction_ids)
        content = "||".join(sorted_ids).encode("utf-8")
        return hashlib.sha256(content).hexdigest()
