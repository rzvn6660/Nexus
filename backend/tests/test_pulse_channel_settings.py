"""Tests for NEXUS Pulse Channel Settings, Verification & Zero-Cost Mailpit Adapter."""

import os
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from app.analytics.pulse.notifications.base import NotificationPayload
from app.analytics.pulse.notifications.dispatcher import PulseNotificationDispatcher
from app.analytics.pulse.notifications.email import EmailNotificationAdapter
from app.analytics.pulse.notifications.telegram import TelegramNotificationAdapter
from app.analytics.pulse.notifications.whatsapp import WhatsAppNotificationAdapter
from app.analytics.pulse.service import PulseService
from app.models.tenant import Business, Organization
from app.schemas.pulse import (
    DeliveryChannel,
    DeliveryStatus,
    PulseChannelConfigureRequest,
)
from sqlalchemy.orm import Session


@pytest.fixture
def test_biz(db_session: Session) -> Business:
    org = Organization(id=f"org_test_{uuid4().hex[:6]}", name="Channel Test Org", slug=f"channel-test-{uuid4().hex[:6]}")
    db_session.add(org)
    db_session.flush()

    biz = Business(id=f"biz_test_{uuid4().hex[:6]}", organization_id=org.id, name="Channel Test Store", status="active")
    db_session.add(biz)
    db_session.commit()
    return biz


def test_channel_statuses_default(db_session: Session, test_biz: Business):
    """Test initial channel status returns all 3 channels in safe default/mock state."""
    statuses = PulseService.get_channel_statuses(db_session, test_biz.id)
    assert len(statuses) == 3
    channel_map = {s.channel: s for s in statuses}

    assert DeliveryChannel.EMAIL in channel_map
    assert DeliveryChannel.TELEGRAM in channel_map
    assert DeliveryChannel.WHATSAPP in channel_map

    # By default without credentials, WhatsApp is SANDBOX_MOCK
    assert channel_map[DeliveryChannel.WHATSAPP].status == "SANDBOX_MOCK"
    assert channel_map[DeliveryChannel.WHATSAPP].is_live is False


def test_configure_email_mailpit_zero_cost(db_session: Session, test_biz: Business):
    """Test configuring email channel with zero-cost local Mailpit setting."""
    req = PulseChannelConfigureRequest(
        channel=DeliveryChannel.EMAIL,
        use_mailpit=True,
        from_email="manager@nexus.local",
    )
    status_item = PulseService.configure_channel(db_session, test_biz.id, req)
    assert status_item.channel == DeliveryChannel.EMAIL
    assert status_item.status == "LOCAL_MAILPIT"
    assert status_item.is_live is True
    assert "Mailpit" in status_item.destination_hint

    # Verify adapter resolved for this business uses mailpit settings
    dispatcher = PulseNotificationDispatcher()
    adapter = dispatcher.get_adapter(db_session, test_biz.id, DeliveryChannel.EMAIL)
    assert isinstance(adapter, EmailNotificationAdapter)
    assert adapter.is_mailpit is True
    assert adapter.is_live_configured is True
    assert adapter.smtp_port == 1025


def test_configure_email_custom_smtp(db_session: Session, test_biz: Business):
    """Test configuring custom corporate SMTP server."""
    req = PulseChannelConfigureRequest(
        channel=DeliveryChannel.EMAIL,
        smtp_host="smtp.sendgrid.net",
        smtp_port=587,
        smtp_user="apikey",
        smtp_password="test_secret_smtp_password",
        from_email="reports@corporate.com",
        use_mailpit=False,
    )
    status_item = PulseService.configure_channel(db_session, test_biz.id, req)
    assert status_item.status == "LIVE_CONFIGURED"
    assert status_item.is_live is True

    dispatcher = PulseNotificationDispatcher()
    adapter = dispatcher.get_adapter(db_session, test_biz.id, DeliveryChannel.EMAIL)
    assert adapter.is_mailpit is False
    assert adapter.smtp_host == "smtp.sendgrid.net"


def test_configure_and_disconnect_telegram(db_session: Session, test_biz: Business):
    """Test Telegram bot token configuration, envelope encryption, and disconnect."""
    req = PulseChannelConfigureRequest(
        channel=DeliveryChannel.TELEGRAM,
        bot_token="123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456",
    )
    status_item = PulseService.configure_channel(db_session, test_biz.id, req)
    assert status_item.channel == DeliveryChannel.TELEGRAM
    assert status_item.status == "LIVE_CONFIGURED"
    assert status_item.is_live is True

    # Test disconnect reverts to mock
    disc_item = PulseService.disconnect_channel(db_session, test_biz.id, DeliveryChannel.TELEGRAM)
    assert disc_item.status == "SANDBOX_MOCK"
    assert disc_item.is_live is False


def test_configure_and_disconnect_whatsapp(db_session: Session, test_biz: Business):
    """Test WhatsApp Meta Cloud API configuration and disconnect."""
    req = PulseChannelConfigureRequest(
        channel=DeliveryChannel.WHATSAPP,
        whatsapp_phone_number_id="1092837465",
        whatsapp_api_token="EAAB1234567890MetaTokenExample",
        whatsapp_business_account_id="9988776655",
    )
    status_item = PulseService.configure_channel(db_session, test_biz.id, req)
    assert status_item.channel == DeliveryChannel.WHATSAPP
    assert status_item.status == "LIVE_CONFIGURED"
    assert status_item.is_live is True

    # Disconnect
    disc_item = PulseService.disconnect_channel(db_session, test_biz.id, DeliveryChannel.WHATSAPP)
    assert disc_item.status == "SANDBOX_MOCK"


def test_destination_validation():
    """Test format verification for email, phone, and telegram chat id."""
    # Email
    v_email = PulseService.verify_destination(DeliveryChannel.EMAIL, "  owner@store.com  ")
    assert v_email.valid is True
    assert v_email.normalized_destination == "owner@store.com"

    v_bad_email = PulseService.verify_destination(DeliveryChannel.EMAIL, "not-an-email")
    assert v_bad_email.valid is False

    # WhatsApp (E.164)
    v_wa = PulseService.verify_destination(DeliveryChannel.WHATSAPP, "+1 (415) 555-2671")
    assert v_wa.valid is True
    assert v_wa.normalized_destination == "+14155552671"

    v_bad_wa = PulseService.verify_destination(DeliveryChannel.WHATSAPP, "invalid")
    assert v_bad_wa.valid is False

    # Telegram
    v_tg = PulseService.verify_destination(DeliveryChannel.TELEGRAM, "  123456789  ")
    assert v_tg.valid is True
    assert v_tg.normalized_destination == "123456789"


@patch("smtplib.SMTP")
def test_mailpit_dispatch_mocked_smtp(mock_smtp_cls):
    """Verify that when Mailpit is active, email dispatch does not call starttls or login."""
    mock_server = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_server

    adapter = EmailNotificationAdapter(
        smtp_host="127.0.0.1",
        smtp_port=1025,
        from_email="pulse@nexus.local",
    )
    assert adapter.is_mailpit is True

    payload = NotificationPayload(
        report_id="rep_test_mailpit",
        business_id="biz_1",
        business_name="Test Store",
        report_title="Mailpit Test Report",
        period_label="Oct 2026",
        messaging_summary="Mailpit test delivery",
        executive_summary="Executive summary body",
        report_url="https://nexus.local/pulse/reports/1",
        recipient_destination="manager@nexus.local",
        is_test=True,
    )

    result = adapter.send_notification(payload)
    assert result.status == DeliveryStatus.SENT
    assert result.metadata.get("provider") == "mailpit_local"

    # Verify SMTP was called without login or starttls
    mock_server.starttls.assert_not_called()
    mock_server.login.assert_not_called()
    mock_server.send_message.assert_called_once()
