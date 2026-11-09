"""Telegram Bot API Adapter for NEXUS Pulse (Section 7).

Integrates with the official Telegram Bot API for automated report notifications
and direct PDF document delivery.
Features:
- Chat ID validation.
- Formatted markdown message delivery.
- Direct PDF report document attachments via sendDocument.
- Sandbox/Mock mode when bot token is unconfigured.
"""

import os
from datetime import UTC, datetime
from typing import Any
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


class TelegramNotificationAdapter(BaseNotificationAdapter):
    """Official Telegram Bot API notification adapter."""

    def __init__(self, bot_token: str | None = None) -> None:
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.api_base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None

    @property
    def channel(self) -> DeliveryChannel:
        return DeliveryChannel.TELEGRAM

    @property
    def is_live_configured(self) -> bool:
        return bool(
            self.bot_token
            and not self.bot_token.startswith("dummy_")
            and not self.bot_token.startswith("mock_")
        )

    def verify_bot_token(self) -> dict[str, Any]:
        """Verify bot token with Telegram getMe API."""
        if not self.api_base_url:
            return {"valid": False, "error": "No bot token configured"}
        try:
            resp = requests.get(f"{self.api_base_url}/getMe", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    bot_info = data.get("result", {})
                    return {
                        "valid": True,
                        "bot_id": bot_info.get("id"),
                        "bot_name": bot_info.get("first_name"),
                        "bot_username": f"@{bot_info.get('username')}" if bot_info.get("username") else None,
                    }
            return {"valid": False, "error": f"Telegram API returned HTTP {resp.status_code}"}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def validate_chat_id(self, chat_id: str) -> str:
        """Validate chat ID format."""
        cid = chat_id.strip()
        if not cid:
            raise ValueError("Telegram chat_id cannot be empty.")
        return cid

    def send_notification(self, payload: NotificationPayload) -> DeliveryResult:
        """Dispatch Telegram message and optional document or mock in sandbox."""
        try:
            chat_id = self.validate_chat_id(payload.recipient_destination)
        except ValueError as e:
            return DeliveryResult(
                channel=self.channel,
                status=DeliveryStatus.FAILED,
                recipient_destination=payload.recipient_destination,
                error_message=str(e),
                dispatched_at=datetime.now(UTC),
            )

        msg_body = payload.messaging_summary
        if payload.report_url and payload.report_url not in msg_body:
            msg_body += f"\n\n📊 *Full Web Report:* {payload.report_url}"

        # If live credentials exist
        if self.is_live_configured and self.api_base_url:
            try:
                # 1. Send text message
                text_url = f"{self.api_base_url}/sendMessage"
                text_data = {
                    "chat_id": chat_id,
                    "text": msg_body,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                }
                resp = requests.post(text_url, json=text_data, timeout=10)
                if resp.status_code != 200:
                    return DeliveryResult(
                        channel=self.channel,
                        status=DeliveryStatus.FAILED,
                        recipient_destination=chat_id,
                        error_message=f"Telegram sendMessage HTTP {resp.status_code}: {resp.text}",
                        dispatched_at=datetime.now(UTC),
                    )

                res_json = resp.json()
                msg_id = str(res_json.get("result", {}).get("message_id", uuid4().hex[:12]))

                # 2. Optionally send PDF document if bytes provided
                if payload.pdf_bytes:
                    doc_url = f"{self.api_base_url}/sendDocument"
                    filename = payload.pdf_filename or f"NEXUS_Pulse_Report_{payload.report_id[:8]}.pdf"
                    files = {"document": (filename, payload.pdf_bytes, "application/pdf")}
                    data = {"chat_id": chat_id, "caption": f"📄 Complete PDF: {payload.report_title}"}
                    requests.post(doc_url, data=data, files=files, timeout=15)

                return DeliveryResult(
                    channel=self.channel,
                    status=DeliveryStatus.SENT,
                    recipient_destination=chat_id,
                    external_message_id=msg_id,
                    dispatched_at=datetime.now(UTC),
                    metadata={"provider": "telegram_bot_api", "live_dispatch": True},
                )
            except Exception as ex:  # noqa: BLE001
                logger.error("Telegram live dispatch error: %s", ex)
                return DeliveryResult(
                    channel=self.channel,
                    status=DeliveryStatus.FAILED,
                    recipient_destination=chat_id,
                    error_message=str(ex),
                    dispatched_at=datetime.now(UTC),
                )

        # Sandbox / Mock Mode
        simulated_id = f"tg_mock_{uuid4().hex[:12]}"
        logger.info(
            "NEXUS Pulse Sandbox Telegram dispatch: chat_id=%s, report_id=%s, simulated_id=%s",
            chat_id,
            payload.report_id,
            simulated_id,
        )
        return DeliveryResult(
            channel=self.channel,
            status=DeliveryStatus.MOCKED,
            recipient_destination=chat_id,
            external_message_id=simulated_id,
            dispatched_at=datetime.now(UTC),
            delivered_at=datetime.now(UTC),
            metadata={
                "provider": "telegram_sandbox_mock",
                "simulated_text_length": len(msg_body),
                "pdf_attached": bool(payload.pdf_bytes),
                "is_test": payload.is_test,
                "notice": "Simulated sandbox dispatch. Real Telegram delivery requires authorized bot token.",
            },
        )
