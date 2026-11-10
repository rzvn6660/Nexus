"""Multi-Channel Notification Dispatcher for NEXUS Pulse (Section 7 & 8).

Orchestrates report notifications across WhatsApp, Telegram, and Email.
Features:
- Validates recipient opt-in/opt-out status prior to dispatch.
- Routes payloads to appropriate channel adapters.
- Records durable, tenant-scoped delivery audit events in pulse_delivery_logs.
- Idempotent and concurrency-safe.
"""

from datetime import UTC, datetime

from app.analytics.pulse.notifications.base import (
    BaseNotificationAdapter,
    DeliveryResult,
    NotificationPayload,
)
from app.analytics.pulse.notifications.email import EmailNotificationAdapter
from app.analytics.pulse.notifications.telegram import TelegramNotificationAdapter
from app.analytics.pulse.notifications.whatsapp import WhatsAppNotificationAdapter
from app.core.logging import get_logger
from app.models.connector import TenantConnectorCredential
from app.models.pulse import PulseDeliveryLog, PulseRecipientPreference
from app.schemas.pulse import DeliveryChannel, DeliveryStatus
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = get_logger(__name__)


class PulseNotificationDispatcher:
    """Central dispatch coordinator for all Pulse notification channels."""

    def __init__(self) -> None:
        self.default_adapters: dict[DeliveryChannel, BaseNotificationAdapter] = {
            DeliveryChannel.WHATSAPP: WhatsAppNotificationAdapter(),
            DeliveryChannel.TELEGRAM: TelegramNotificationAdapter(),
            DeliveryChannel.EMAIL: EmailNotificationAdapter(),
        }

    def get_adapter(
        self,
        session: Session,
        business_id: str,
        channel: DeliveryChannel,
    ) -> BaseNotificationAdapter:
        """
        Resolve active notification adapter for this tenant and channel.
        Checks for tenant-scoped encrypted credentials in TenantConnectorCredential;
        falls back to environment-based default adapter.
        """
        provider_name = f"pulse_{channel.value.lower()}"
        try:
            cred = session.execute(
                select(TenantConnectorCredential).where(
                    TenantConnectorCredential.business_id == business_id,
                    TenantConnectorCredential.provider == provider_name,
                    TenantConnectorCredential.status == "ACTIVE",
                )
            ).scalar_one_or_none()

            if cred:
                from app.core.kms import EnvelopeEncryptionEngine, get_kms_provider

                kms = get_kms_provider()
                decrypted = EnvelopeEncryptionEngine.decrypt_credentials(
                    envelope_str=cred.encrypted_credentials,
                    business_id=business_id,
                    provider=provider_name,
                    provider_account_id=cred.provider_account_id,
                    kms_provider=kms,
                )
                if channel == DeliveryChannel.EMAIL:
                    return EmailNotificationAdapter(
                        smtp_host=decrypted.get("smtp_host"),
                        smtp_port=int(decrypted.get("smtp_port") or 1025),
                        smtp_user=decrypted.get("smtp_user"),
                        smtp_password=decrypted.get("smtp_password"),
                        from_email=decrypted.get("from_email"),
                    )
                elif channel == DeliveryChannel.TELEGRAM:
                    return TelegramNotificationAdapter(
                        bot_token=decrypted.get("bot_token"),
                    )
                elif channel == DeliveryChannel.WHATSAPP:
                    return WhatsAppNotificationAdapter(
                        api_token=decrypted.get("api_token"),
                        phone_number_id=decrypted.get("phone_number_id"),
                        business_account_id=decrypted.get("business_account_id"),
                    )
        except Exception as e:
            logger.warning(
                "Tenant channel credential lookup failed for %s (biz=%s): %s. Using default adapter.",
                channel.value,
                business_id,
                e,
            )

        adapter = self.default_adapters.get(channel)
        if not adapter:
            raise ValueError(f"No notification adapter configured for channel '{channel.value}'.")
        return adapter

    def dispatch(
        self,
        session: Session,
        payload: NotificationPayload,
        channel: DeliveryChannel,
    ) -> DeliveryResult:
        """
        Dispatch notification payload to specified recipient and log the outcome.
        Enforces tenant opt-in verification.
        """
        # 1. Check Recipient Opt-Out State
        opt_stmt = select(PulseRecipientPreference).where(
            PulseRecipientPreference.business_id == payload.business_id,
            PulseRecipientPreference.channel == channel.value,
            PulseRecipientPreference.destination == payload.recipient_destination,
        )
        pref = session.execute(opt_stmt).scalar_one_or_none()
        if pref and pref.opt_status == "OPTED_OUT":
            logger.warning(
                "Dispatch blocked: recipient %s has opted out of %s notifications for business %s",
                payload.recipient_destination,
                channel.value,
                payload.business_id,
            )
            result = DeliveryResult(
                channel=channel,
                status=DeliveryStatus.FAILED,
                recipient_destination=payload.recipient_destination,
                error_message=f"Recipient {payload.recipient_destination} has explicitly opted out of {channel.value} notifications.",
                dispatched_at=datetime.now(UTC),
                metadata={"opt_out_blocked": True},
            )
            self._record_delivery_log(session, payload, result)
            return result

        # 2. Select Adapter
        adapter = self.get_adapter(session, payload.business_id, channel)
        if not adapter:
            result = DeliveryResult(
                channel=channel,
                status=DeliveryStatus.FAILED,
                recipient_destination=payload.recipient_destination,
                error_message=f"No notification adapter registered for channel {channel.value}",
                dispatched_at=datetime.now(UTC),
            )
            self._record_delivery_log(session, payload, result)
            return result

        # 3. Execute Dispatch
        result = adapter.send_notification(payload)

        # 4. Audit Log Execution in Database
        self._record_delivery_log(session, payload, result)
        return result

    def _record_delivery_log(
        self,
        session: Session,
        payload: NotificationPayload,
        result: DeliveryResult,
    ) -> PulseDeliveryLog:
        """Persist delivery outcome to pulse_delivery_logs table."""
        log_entry = PulseDeliveryLog(
            report_id=payload.report_id,
            business_id=payload.business_id,
            organization_id=payload.metadata.get("organization_id", "org_default"),
            channel=result.channel.value,
            recipient_destination=result.recipient_destination,
            recipient_name=payload.recipient_name,
            status=result.status.value,
            external_message_id=result.external_message_id,
            error_message=result.error_message,
            attempts=1,
            dispatched_at=result.dispatched_at,
            delivered_at=result.delivered_at,
            metadata_json=result.metadata,
        )
        session.add(log_entry)
        session.commit()
        return log_entry
