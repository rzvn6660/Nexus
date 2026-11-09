"""Pulse notifications module."""

from app.analytics.pulse.notifications.base import (
    BaseNotificationAdapter,
    DeliveryResult,
    NotificationPayload,
)
from app.analytics.pulse.notifications.dispatcher import PulseNotificationDispatcher
from app.analytics.pulse.notifications.email import EmailNotificationAdapter
from app.analytics.pulse.notifications.telegram import TelegramNotificationAdapter
from app.analytics.pulse.notifications.whatsapp import WhatsAppNotificationAdapter

__all__ = [
    "BaseNotificationAdapter",
    "DeliveryResult",
    "EmailNotificationAdapter",
    "NotificationPayload",
    "PulseNotificationDispatcher",
    "TelegramNotificationAdapter",
    "WhatsAppNotificationAdapter",
]
