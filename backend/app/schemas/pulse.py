"""Pydantic schemas and data contracts for NEXUS Pulse: Management Intelligence & Automated Reporting."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class KPICategory(str, Enum):
    FINANCIAL = "FINANCIAL"
    CUSTOMER = "CUSTOMER"
    CHURN = "CHURN"
    RETENTION = "RETENTION"
    PRODUCT = "PRODUCT"
    OPERATIONAL = "OPERATIONAL"


class ReportFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    WEEKLY = "WEEKLY"
    DAILY = "DAILY"
    EVENT_DRIVEN = "EVENT_DRIVEN"


class ReportType(str, Enum):
    MONTHLY_EXECUTIVE = "MONTHLY_EXECUTIVE"
    WEEKLY_MANAGEMENT = "WEEKLY_MANAGEMENT"
    CUSTOM = "CUSTOM"


class DeliveryChannel(str, Enum):
    WHATSAPP = "WHATSAPP"
    TELEGRAM = "TELEGRAM"
    EMAIL = "EMAIL"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    MOCKED = "MOCKED"


class RecipientOptStatus(str, Enum):
    OPTED_IN = "OPTED_IN"
    OPTED_OUT = "OPTED_OUT"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"


class InsightType(str, Enum):
    OBSERVED_FACT = "OBSERVED_FACT"
    CALCULATED_KPI = "CALCULATED_KPI"
    STATISTICAL_OBSERVATION = "STATISTICAL_OBSERVATION"
    MODEL_INTERPRETATION = "MODEL_INTERPRETATION"
    RECOMMENDED_ACTION = "RECOMMENDED_ACTION"


class InsightSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"
    POSITIVE = "POSITIVE"


class PulseInsightItem(BaseModel):
    """Structured insight item distinguishing facts from models and recommendations."""
    insight_id: str
    type: InsightType
    category: KPICategory
    severity: InsightSeverity
    title: str
    description: str
    evidence_kpis: list[str] = Field(default_factory=list)
    action_suggestion: str | None = None


class PulseKPIDefinition(BaseModel):
    """Documented KPI entry with strict calculation metadata and limitations."""
    key: str
    name: str
    category: KPICategory
    value: float | int | str | None
    unit: str
    formatted_value: str
    baseline_value: float | None = None
    delta: float | None = None
    pct_change: float | None = None
    definition: str
    calculation: str
    source: str
    time_window: str
    limitations: str


class PulseKPIPayload(BaseModel):
    """Comprehensive KPI payload for executive dashboards and generated reports."""
    financial: dict[str, PulseKPIDefinition] = Field(default_factory=dict)
    customer: dict[str, PulseKPIDefinition] = Field(default_factory=dict)
    churn: dict[str, PulseKPIDefinition] = Field(default_factory=dict)
    retention: dict[str, PulseKPIDefinition] = Field(default_factory=dict)
    product: dict[str, PulseKPIDefinition] = Field(default_factory=dict)
    operational: dict[str, PulseKPIDefinition] = Field(default_factory=dict)
    top_products: list[dict[str, Any]] = Field(default_factory=list)
    category_performance: list[dict[str, Any]] = Field(default_factory=list)
    risk_distribution: dict[str, int] = Field(default_factory=dict)
    urgency_distribution: dict[str, int] = Field(default_factory=dict)
    revenue_trend: list[dict[str, Any]] = Field(default_factory=list)


class PulseReportDetail(BaseModel):
    """Full detail of a generated executive report."""
    id: str
    business_id: str
    report_title: str
    report_type: ReportType
    period_start: str
    period_end: str
    comparison_period_start: str | None = None
    comparison_period_end: str | None = None
    kpi_payload: PulseKPIPayload
    insights: list[PulseInsightItem] = Field(default_factory=list)
    executive_summary: str
    messaging_summary: str
    pdf_available: bool = False
    pdf_sha256: str | None = None
    watermark_status: str
    access_token: str
    token_expires_at: str
    created_at: str
    deliveries_count: int = 0


class PulseReportListItem(BaseModel):
    """Summary item for report history table."""
    id: str
    report_title: str
    report_type: ReportType
    period_start: str
    period_end: str
    created_at: str
    watermark_status: str
    pdf_available: bool
    access_token: str
    token_expires_at: str
    deliveries_count: int = 0


class PulseRecipientConfig(BaseModel):
    """Recipient contact specification."""
    name: str
    channel: DeliveryChannel
    destination: str
    role: str = "Executive"


class PulseScheduleCreateRequest(BaseModel):
    """Request specification for creating a report schedule."""
    schedule_name: str
    report_type: ReportType = ReportType.MONTHLY_EXECUTIVE
    frequency: ReportFrequency = ReportFrequency.MONTHLY
    day_of_month: int | None = 1
    day_of_week: int | None = None
    time_of_day: str = "09:00"
    timezone: str = "UTC"
    is_enabled: bool = True
    channel_types: list[DeliveryChannel] = Field(default_factory=lambda: [DeliveryChannel.WHATSAPP])
    recipients: list[PulseRecipientConfig] = Field(default_factory=list)
    kpi_categories: list[KPICategory] = Field(default_factory=lambda: list(KPICategory))
    alert_triggers: dict[str, bool] = Field(default_factory=lambda: {
        "critical_churn_spike": True,
        "revenue_anomaly": True,
        "watermark_invalid": True,
        "retention_attention_required": True,
    })


class PulseScheduleUpdateRequest(BaseModel):
    """Request specification for updating an existing schedule."""
    schedule_name: str | None = None
    report_type: ReportType | None = None
    frequency: ReportFrequency | None = None
    day_of_month: int | None = None
    day_of_week: int | None = None
    time_of_day: str | None = None
    timezone: str | None = None
    is_enabled: bool | None = None
    channel_types: list[DeliveryChannel] | None = None
    recipients: list[PulseRecipientConfig] | None = None
    kpi_categories: list[KPICategory] | None = None
    alert_triggers: dict[str, bool] | None = None


class PulseScheduleResponse(BaseModel):
    """Schedule response representation."""
    id: int
    business_id: str
    schedule_name: str
    report_type: ReportType
    frequency: ReportFrequency
    day_of_month: int | None
    day_of_week: int | None
    time_of_day: str
    timezone: str
    is_enabled: bool
    channel_types: list[DeliveryChannel]
    recipients: list[PulseRecipientConfig]
    kpi_categories: list[KPICategory]
    alert_triggers: dict[str, Any]
    last_run_at: str | None
    next_run_at: str | None
    created_at: str


class PulseGenerateReportRequest(BaseModel):
    """Manual trigger request to generate a report on demand."""
    report_type: ReportType = ReportType.MONTHLY_EXECUTIVE
    date_from: datetime
    date_to: datetime
    comparison_date_from: datetime | None = None
    comparison_date_to: datetime | None = None
    report_title: str | None = None
    force_regenerate: bool = False
    idempotency_key: str | None = None


class PulseTestDispatchRequest(BaseModel):
    """Request to send a test report to an authorized test destination."""
    report_id: str
    channel: DeliveryChannel
    destination: str
    recipient_name: str = "Test Recipient"


class PulseDeliveryLogItem(BaseModel):
    """Delivery log record item."""
    id: int
    report_id: str
    channel: DeliveryChannel
    recipient_destination: str
    recipient_name: str | None
    status: DeliveryStatus
    external_message_id: str | None
    error_message: str | None
    attempts: int
    dispatched_at: str | None
    delivered_at: str | None
    created_at: str


class PulseRecipientOptRequest(BaseModel):
    """Request to manage recipient opt status."""
    recipient_name: str
    channel: DeliveryChannel
    destination: str
    role: str = "Executive"
    opt_status: RecipientOptStatus = RecipientOptStatus.OPTED_IN
    opt_out_reason: str | None = None


class PulseRecipientItem(BaseModel):
    """Registered recipient representation."""
    id: int
    recipient_name: str
    channel: DeliveryChannel
    destination: str
    role: str
    opt_status: RecipientOptStatus
    opted_at: str
    opt_out_reason: str | None


class PulseDashboardOverview(BaseModel):
    """Management dashboard aggregated payload."""
    as_of_date: str
    period_start: str
    period_end: str
    comparison_period_start: str | None
    comparison_period_end: str | None
    kpi_payload: PulseKPIPayload
    insights: list[PulseInsightItem]
    active_alerts_count: int
    critical_risk_count: int
    revenue_at_risk_usd: float
    retention_pending_count: int
    watermark_status: str
    is_actionable: bool
    data_freshness_hours: float | None


# ==============================================================================
# CHANNEL SETTINGS & CREDENTIAL CONFIGURATION CONTRACTS
# ==============================================================================

class PulseChannelStatusItem(BaseModel):
    """Channel connection status and configuration summary."""
    channel: DeliveryChannel
    status: str  # LIVE_CONFIGURED, LOCAL_MAILPIT, SANDBOX_MOCK, DISCONNECTED
    is_live: bool
    destination_hint: str | None = None
    provider_details: dict[str, Any] = Field(default_factory=dict)
    setup_guide: str


class PulseChannelConfigureRequest(BaseModel):
    """Manager request to configure credentials or mode for a notification channel."""
    channel: DeliveryChannel
    # Email options
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    from_email: str | None = None
    use_mailpit: bool = False
    # Telegram options
    bot_token: str | None = None
    # WhatsApp options
    whatsapp_api_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_business_account_id: str | None = None


class PulseDestinationVerifyRequest(BaseModel):
    """Request to validate recipient destination syntax and reachable structure."""
    channel: DeliveryChannel
    destination: str


class PulseDestinationVerifyResponse(BaseModel):
    """Validation response for recipient destination."""
    valid: bool
    channel: DeliveryChannel
    destination: str
    normalized_destination: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
