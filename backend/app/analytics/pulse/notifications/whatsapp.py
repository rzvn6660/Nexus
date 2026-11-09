"""WhatsApp Business Platform / Cloud API Adapter for NEXUS Pulse (Section 7).

Integrates with the official Meta Graph API v18.0 for WhatsApp Business.
Features:
- E.164 phone number validation.
- Structured executive summary messages.
- Secure, expiring report link integration.
- Gated sandbox/mock fallback when live credentials are not configured.
- Zero credential leakage in logs or responses.
"""

import os
import re
from datetime import UTC, datetime
from uuid import uuid4

import requests
from app.analytics.pulse.notifications.base import (
    BaseNotificationAdapter,
    DeliveryResult,
    NotificationPayload,
)
from app.core.logging import get_logger
from app.schemas.pulse import DeliveryChannel, DeliveryStatus

logger = get_logger(__name__)


class WhatsAppNotificationAdapter(BaseNotificationAdapter):
    """Official WhatsApp Business Cloud API notification adapter."""

    def __init__(
        self,
        api_token: str | None = None,
        phone_number_id: str | None = None,
        business_account_id: str | None = None,
    ) -> None:
        self.api_token = api_token or os.environ.get("WHATSAPP_API_TOKEN")
        self.phone_number_id = phone_number_id or os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
        self.business_account_id = business_account_id or os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID")
        self.graph_api_url = f"https://graph.facebook.com/v18.0/{self.phone_number_id}/messages" if self.phone_number_id else None

    @property
    def channel(self) -> DeliveryChannel:
        return DeliveryChannel.WHATSAPP

    @property
    def is_live_configured(self) -> bool:
        """Return True only if real API credentials are provided and non-dummy."""
        return bool(
            self.api_token
            and self.phone_number_id
            and not self.api_token.startswith("dummy_")
            and not self.api_token.startswith("mock_")
        )

    def validate_phone(self, phone: str) -> str:
        """Normalize and validate E.164 phone number format."""
        cleaned = re.sub(r"[\s\-\(\)]", "", phone.strip())
        if not cleaned.startswith("+"):
            cleaned = f"+{cleaned}"
        if not re.match(r"^\+[1-9]\d{6,14}$", cleaned):
            raise ValueError(f"Invalid E.164 phone number format: '{phone}'. Expected e.g. +15551234567.")
        return cleaned

    def send_notification(self, payload: NotificationPayload) -> DeliveryResult:
        """Dispatch WhatsApp business message or execute mock in sandbox."""
        try:
            recipient_phone = self.validate_phone(payload.recipient_destination)
        except ValueError as e:
            return DeliveryResult(
                channel=self.channel,
                status=DeliveryStatus.FAILED,
                recipient_destination=payload.recipient_destination,
                error_message=str(e),
                dispatched_at=datetime.now(UTC),
            )

        # Build message body
        msg_body = payload.messaging_summary
        if payload.report_url and payload.report_url not in msg_body:
            msg_body += f"\n\n📊 *Full Report:* {payload.report_url}"

        # If live credentials exist and live delivery is authorized
        if self.is_live_configured and self.graph_api_url:
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                }
                body_data = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": recipient_phone.replace("+", ""),
                    "type": "text",
                    "text": {"preview_url": True, "body": msg_body},
                }
                resp = requests.post(self.graph_api_url, json=body_data, headers=headers, timeout=10)
                if resp.status_code in {200, 201}:
                    res_json = resp.json()
                    msg_id = res_json.get("messages", [{}])[0].get("id", f"wamid.{uuid4().hex[:16]}")
                    return DeliveryResult(
                        channel=self.channel,
                        status=DeliveryStatus.SENT,
                        recipient_destination=recipient_phone,
                        external_message_id=msg_id,
                        dispatched_at=datetime.now(UTC),
                        metadata={"provider": "meta_whatsapp_cloud_api", "live_dispatch": True},
                    )
                else:
                    return DeliveryResult(
                        channel=self.channel,
                        status=DeliveryStatus.FAILED,
                        recipient_destination=recipient_phone,
                        error_message=f"WhatsApp API HTTP {resp.status_code}: {resp.text}",
                        dispatched_at=datetime.now(UTC),
                    )
            except Exception as ex:  # noqa: BLE001
                logger.error("WhatsApp live dispatch failed: %s", ex)
                return DeliveryResult(
                    channel=self.channel,
                    status=DeliveryStatus.FAILED,
                    recipient_destination=recipient_phone,
                    error_message=str(ex),
                    dispatched_at=datetime.now(UTC),
                )

        # Sandbox / Mock Mode
        simulated_id = f"wamid.mock.{uuid4().hex[:16]}"
        logger.info(
            "NEXUS Pulse Sandbox WhatsApp dispatch: to=%s, report_id=%s, simulated_id=%s",
            recipient_phone,
            payload.report_id,
            simulated_id,
        )
        return DeliveryResult(
            channel=self.channel,
            status=DeliveryStatus.MOCKED,
            recipient_destination=recipient_phone,
            external_message_id=simulated_id,
            dispatched_at=datetime.now(UTC),
            delivered_at=datetime.now(UTC),
            metadata={
                "provider": "whatsapp_sandbox_mock",
                "simulated_text_length": len(msg_body),
                "is_test": payload.is_test,
                "notice": "Simulated sandbox dispatch. Real WhatsApp requires authorized Meta Business credentials.",
            },
        )
