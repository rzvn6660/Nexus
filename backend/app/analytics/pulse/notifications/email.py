"""Email Notification Adapter for NEXUS Pulse (Section 7).

Dispatches executive HTML business intelligence summaries with attached PDF reports
via standard SMTP or configured email providers.
Features:
- Email address syntax validation.
- Responsive executive HTML layout with embedded KPI scorecard.
- Direct PDF report attachment.
- Sandbox/Mock mode when SMTP credentials are unconfigured.
"""

import os
import re
import smtplib
from datetime import UTC, datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from uuid import uuid4

from app.analytics.pulse.notifications.base import (
    BaseNotificationAdapter,
    DeliveryResult,
    NotificationPayload,
)
from app.core.logging import get_logger
from app.schemas.pulse import DeliveryChannel, DeliveryStatus

logger = get_logger(__name__)


class EmailNotificationAdapter(BaseNotificationAdapter):
    """Email notification adapter with HTML templates and PDF attachments."""

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        from_email: str | None = None,
    ) -> None:
        self.smtp_host = smtp_host or os.environ.get("SMTP_HOST")
        self.smtp_port = smtp_port or int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.environ.get("SMTP_USER")
        self.smtp_password = smtp_password or os.environ.get("SMTP_PASSWORD")
        self.from_email = from_email or os.environ.get("PULSE_FROM_EMAIL", "nexus-pulse@nexus.internal")

    @property
    def channel(self) -> DeliveryChannel:
        return DeliveryChannel.EMAIL

    @property
    def is_mailpit(self) -> bool:
        """Return True if configured to use local Mailpit testing server."""
        host = (self.smtp_host or "").strip().lower()
        use_mailpit_env = os.environ.get("USE_MAILPIT", "false").lower() in ("true", "1", "yes")
        return bool(
            use_mailpit_env
            or host in ("mailpit", "127.0.0.1", "localhost")
            or self.smtp_port in (1025, 2525)
        )

    @property
    def is_live_configured(self) -> bool:
        if not self.smtp_host or self.smtp_host.startswith("mock"):
            return False
        if self.is_mailpit:
            return True
        return bool(self.smtp_user and self.smtp_password)

    def validate_email(self, email: str) -> str:
        """Validate email format."""
        em = email.strip()
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", em):
            raise ValueError(f"Invalid email address format: '{email}'.")
        return em

    def send_notification(self, payload: NotificationPayload) -> DeliveryResult:
        """Dispatch HTML email with PDF attachment or mock in sandbox."""
        try:
            recipient_email = self.validate_email(payload.recipient_destination)
        except ValueError as e:
            return DeliveryResult(
                channel=self.channel,
                status=DeliveryStatus.FAILED,
                recipient_destination=payload.recipient_destination,
                error_message=str(e),
                dispatched_at=datetime.now(UTC),
            )

        subject = f"NEXUS Pulse — {payload.report_title} ({payload.period_label})"
        html_content = self._render_html_template(payload)

        # If live SMTP or local Mailpit credentials are configured
        if self.is_live_configured and self.smtp_host:
            try:
                msg = MIMEMultipart("mixed")
                msg["Subject"] = subject
                msg["From"] = self.from_email
                msg["To"] = recipient_email

                # HTML alternative part
                msg.attach(MIMEText(html_content, "html"))

                # PDF attachment
                if payload.pdf_bytes:
                    filename = payload.pdf_filename or f"NEXUS_Pulse_{payload.report_id[:8]}.pdf"
                    part = MIMEApplication(payload.pdf_bytes, Name=filename)
                    part["Content-Disposition"] = f'attachment; filename="{filename}"'
                    msg.attach(part)

                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                    if not self.is_mailpit and self.smtp_user and self.smtp_password:
                        server.starttls()
                        server.login(self.smtp_user or "", self.smtp_password or "")
                    server.send_message(msg)

                msg_id = f"email_{uuid4().hex[:12]}"
                provider_tag = "mailpit_local" if self.is_mailpit else "smtp"
                return DeliveryResult(
                    channel=self.channel,
                    status=DeliveryStatus.SENT,
                    recipient_destination=recipient_email,
                    external_message_id=msg_id,
                    dispatched_at=datetime.now(UTC),
                    metadata={"provider": provider_tag, "live_dispatch": True, "is_test": payload.is_test},
                )
            except Exception as ex:  # noqa: BLE001
                logger.error("Email live dispatch error: %s", ex)
                return DeliveryResult(
                    channel=self.channel,
                    status=DeliveryStatus.FAILED,
                    recipient_destination=recipient_email,
                    error_message=str(ex),
                    dispatched_at=datetime.now(UTC),
                )

        # Sandbox / Mock Mode
        simulated_id = f"email_mock_{uuid4().hex[:12]}"
        logger.info(
            "NEXUS Pulse Sandbox Email dispatch: to=%s, report_id=%s, simulated_id=%s",
            recipient_email,
            payload.report_id,
            simulated_id,
        )
        return DeliveryResult(
            channel=self.channel,
            status=DeliveryStatus.MOCKED,
            recipient_destination=recipient_email,
            external_message_id=simulated_id,
            dispatched_at=datetime.now(UTC),
            delivered_at=datetime.now(UTC),
            metadata={
                "provider": "email_sandbox_mock",
                "subject": subject,
                "pdf_attached": bool(payload.pdf_bytes),
                "is_test": payload.is_test,
                "notice": "Simulated sandbox dispatch. Real email delivery requires active SMTP credentials.",
            },
        )

    def _render_html_template(self, payload: NotificationPayload) -> str:
        """Render responsive executive HTML email."""
        link_btn = (
            f'<div style="margin: 24px 0;"><a href="{payload.report_url}" style="background-color: #2563EB; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block;">Open Interactive Executive Report</a></div>'
            if payload.report_url
            else ""
        )
        summary_html = payload.executive_summary.replace("\n\n", "</p><p style='color: #334155; line-height: 1.6;'>")

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>NEXUS Pulse Executive Report</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F8FAFC; margin: 0; padding: 24px;">
    <table width="100%" border="0" cellspacing="0" cellpadding="0">
        <tr>
            <td align="center">
                <table width="640" border="0" cellspacing="0" cellpadding="0" style="background-color: #ffffff; border-radius: 8px; border: 1px solid #E2E8F0; overflow: hidden;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #0F172A; padding: 24px 32px; border-bottom: 3px solid #2563EB;">
                            <div style="color: #94A3B8; font-size: 12px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px;">NEXUS PULSE | Executive Intelligence</div>
                            <h1 style="color: #ffffff; font-size: 22px; margin: 8px 0 0 0; font-weight: bold;">{payload.report_title}</h1>
                            <div style="color: #CBD5E1; font-size: 13px; margin-top: 4px;">{payload.business_name} &bull; {payload.period_label}</div>
                        </td>
                    </tr>
                    <!-- Content -->
                    <tr>
                        <td style="padding: 32px;">
                            <h2 style="color: #0F172A; font-size: 16px; margin: 0 0 12px 0;">Executive Summary</h2>
                            <p style="color: #334155; line-height: 1.6; font-size: 14px;">{summary_html}</p>
                            {link_btn}
                            <hr style="border: 0; border-top: 1px solid #E2E8F0; margin: 24px 0;">
                            <div style="font-size: 12px; color: #64748B; line-height: 1.5;">
                                <b>Data Governance & Safety:</b> Generated automatically by NEXUS Pulse. Customer retention risk metrics reflect empirical purchase cadence and do not represent contractual cancellations. Action recommendations require human merchant approval before execution.
                            </div>
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #F1F5F9; padding: 16px 32px; font-size: 11px; color: #94A3B8; text-align: center;">
                            Report ID: {payload.report_id} &bull; Confidential &bull; NEXUS Pulse
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
