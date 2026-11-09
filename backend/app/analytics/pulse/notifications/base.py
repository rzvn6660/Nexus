"""Base contracts and interfaces for NEXUS Pulse Notification Channels."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.schemas.pulse import DeliveryChannel, DeliveryStatus


@dataclass
class NotificationPayload:
    """Payload delivered to notification channel adapters."""
    report_id: str
    business_id: str
    business_name: str
    report_title: str
    period_label: str
    messaging_summary: str
    executive_summary: str
    report_url: str | None = None
    pdf_bytes: bytes | None = None
    pdf_filename: str | None = None
    recipient_name: str = "Manager"
    recipient_destination: str = ""  # Phone, Chat ID, Email
    is_test: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeliveryResult:
    """Standardized delivery result across all notification adapters."""
    channel: DeliveryChannel
    status: DeliveryStatus
    recipient_destination: str
    external_message_id: str | None = None
    error_message: str | None = None
    dispatched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    delivered_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseNotificationAdapter(ABC):
    """Abstract interface implemented by all channel providers."""

    @property
    @abstractmethod
    def channel(self) -> DeliveryChannel:
        """Return the delivery channel type."""
        ...

    @property
    @abstractmethod
    def is_live_configured(self) -> bool:
        """Return True if real production provider credentials and authorization are active."""
        ...

    @abstractmethod
    def send_notification(self, payload: NotificationPayload) -> DeliveryResult:
        """Dispatch notification or mock delivery in sandbox mode."""
        ...
