"""Pulse Service Facade for NEXUS Pulse (Management Intelligence & Automated Reporting).

Coordinates dashboard aggregation, ad-hoc and scheduled report generation,
PDF compilation, multi-channel dispatch, and audit logging.
"""

import os
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.analytics.pulse.insights import PulseInsightEngine
from app.analytics.pulse.kpi_catalogue import PulseKPICatalogueEngine
from app.analytics.pulse.notifications.base import NotificationPayload
from app.analytics.pulse.notifications.dispatcher import PulseNotificationDispatcher
from app.analytics.pulse.pdf_generator import PulsePDFGenerator
from app.analytics.pulse.scheduler import PulseScheduler
from app.core.logging import get_logger
from app.models.connector import TenantConnectorCredential
from app.models.pulse import (
    PulseDeliveryLog,
    PulseGeneratedReport,
    PulseRecipientPreference,
    PulseReportSchedule,
)
from app.models.tenant import Business
from app.schemas.pulse import (
    DeliveryChannel,
    DeliveryStatus,
    KPICategory,
    PulseChannelConfigureRequest,
    PulseChannelStatusItem,
    PulseDashboardOverview,
    PulseDeliveryLogItem,
    PulseDestinationVerifyRequest,
    PulseDestinationVerifyResponse,
    PulseInsightItem,
    PulseKPIPayload,
    PulseRecipientConfig,
    PulseRecipientItem,
    PulseRecipientOptRequest,
    PulseReportDetail,
    PulseReportListItem,
    PulseScheduleCreateRequest,
    PulseScheduleResponse,
    PulseScheduleUpdateRequest,
    PulseTestDispatchRequest,
    RecipientOptStatus,
    ReportFrequency,
    ReportType,
)
from app.services.source_sync_service import SourceSyncService
from app.services.watermark_service import WatermarkService
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

logger = get_logger(__name__)


class PulseService:
    """Primary facade managing all executive intelligence and reporting operations."""

    @classmethod
    def get_dashboard_overview(
        cls,
        session: Session,
        business_id: str,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        comparison_date_from: datetime | None = None,
        comparison_date_to: datetime | None = None,
        base_url: str = "https://nexus.internal",
    ) -> PulseDashboardOverview:
        """Produce the aggregated executive intelligence dashboard telemetry."""
        # 1. Resolve tenant data readiness and normalize time boundaries
        from app.services.tenant_readiness_service import TenantReadinessService
        readiness = TenantReadinessService.get_tenant_readiness(session=session, business_id=business_id)

        now_utc = datetime.now(UTC)
        if date_to is None and readiness.latest_observed_date:
            latest_utc = readiness.latest_observed_date
            if (now_utc - latest_utc).days > 30:
                p_end = latest_utc
                p_start = p_end - timedelta(days=30)
            else:
                p_end = now_utc
                p_start = p_end - timedelta(days=30)
        else:
            p_end = cls._normalize_dt(date_to, default=now_utc)
            p_start = cls._normalize_dt(date_from, default=p_end - timedelta(days=30))

        if comparison_date_from and comparison_date_to:
            c_start = cls._normalize_dt(comparison_date_from)
            c_end = cls._normalize_dt(comparison_date_to)
        else:
            window_len = p_end - p_start
            c_end = p_start
            c_start = p_start - window_len

        # 1. Compute complete KPI payload
        kpis = PulseKPICatalogueEngine.compute_all_kpis(
            session=session,
            business_id=business_id,
            period_start=p_start,
            period_end=p_end,
            comparison_period_start=c_start,
            comparison_period_end=c_end,
        )

        # 2. Resolve business name and generate insights
        biz = session.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        biz_name = biz.name if biz else "Merchant Workspace"

        period_label = f"{p_start.strftime('%b %d, %Y')} to {p_end.strftime('%b %d, %Y')}"
        insights, _, _ = PulseInsightEngine.generate_insights_and_summaries(
            kpi_payload=kpis,
            business_name=biz_name,
            period_label=period_label,
            report_url=None,
        )

        # 3. Resolve operational & safety telemetry via TenantReadinessService
        wm_status = readiness.readiness_status.value
        is_actionable = readiness.is_actionable

        freshness_hrs = None
        eff_dt = readiness.effective_complete_through_dt or readiness.latest_observed_date
        if eff_dt:
            freshness_hrs = round(max(0.0, (now_utc - eff_dt).total_seconds() / 3600.0), 1)

        # Extract churn & retention indicators
        churn = kpis.churn
        crit_val = churn.get("critical_risk_customers")
        crit_count = int(crit_val.value) if crit_val and isinstance(crit_val.value, (int, float)) else 0
        rev_risk_val = churn.get("revenue_at_risk")
        rev_at_risk = float(rev_risk_val.value) if rev_risk_val and isinstance(rev_risk_val.value, (int, float)) else 0.0

        ret = kpis.retention
        pend_val = ret.get("retention_actions_pending")
        pend_count = int(pend_val.value) if pend_val and isinstance(pend_val.value, (int, float)) else 0

        # Check alert count
        scheduler = PulseScheduler()
        active_alerts = scheduler.check_and_trigger_event_alerts(session, business_id, now_utc)

        return PulseDashboardOverview(
            as_of_date=now_utc.isoformat(),
            period_start=p_start.isoformat(),
            period_end=p_end.isoformat(),
            comparison_period_start=c_start.isoformat() if c_start else None,
            comparison_period_end=c_end.isoformat() if c_end else None,
            kpi_payload=kpis,
            insights=insights,
            active_alerts_count=len(active_alerts),
            critical_risk_count=crit_count,
            revenue_at_risk_usd=rev_at_risk,
            retention_pending_count=pend_count,
            watermark_status=wm_status,
            is_actionable=is_actionable,
            data_freshness_hours=freshness_hrs,
        )

    @classmethod
    def generate_report(
        cls,
        session: Session,
        business_id: str,
        report_type: ReportType = ReportType.MONTHLY_EXECUTIVE,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        comparison_period_start: datetime | None = None,
        comparison_period_end: datetime | None = None,
        report_title: str | None = None,
        schedule_id: int | None = None,
        created_by: str = "User",
        base_url: str = "https://nexus.internal",
        force_regenerate: bool = False,
        idempotency_key: str | None = None,
    ) -> PulseGeneratedReport:
        """Compile and persist an immutable executive business intelligence report with PDF."""
        now_utc = datetime.now(UTC)
        p_end = cls._normalize_dt(period_end, default=now_utc)
        p_start = cls._normalize_dt(period_start, default=p_end - timedelta(days=30))

        if comparison_period_start and comparison_period_end:
            c_start = cls._normalize_dt(comparison_period_start)
            c_end = cls._normalize_dt(comparison_period_end)
        else:
            w_len = p_end - p_start
            c_end = p_start
            c_start = p_start - w_len

        biz = session.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        if not biz:
            raise ValueError(f"Business '{business_id}' not found.")

        # Duplicate Prevention / Idempotency Check:
        if not force_regenerate:
            # Check 1: matching client-supplied idempotency key
            if idempotency_key:
                candidates = session.execute(
                    select(PulseGeneratedReport).where(
                        PulseGeneratedReport.business_id == business_id,
                        PulseGeneratedReport.created_at >= now_utc - timedelta(hours=24),
                    ).order_by(desc(PulseGeneratedReport.created_at))
                ).scalars().all()
                for cand in candidates:
                    if cand.data_provenance_json and cand.data_provenance_json.get("idempotency_key") == idempotency_key:
                        logger.info("PulseService: Returning existing report %s matching idempotency key %s", cand.id, idempotency_key)
                        return cand

            # Check 2: identical parameters generated within recent de-duplication window (5 mins)
            recent_dup = session.execute(
                select(PulseGeneratedReport).where(
                    PulseGeneratedReport.business_id == business_id,
                    PulseGeneratedReport.report_type == report_type.value,
                    PulseGeneratedReport.period_start == p_start,
                    PulseGeneratedReport.period_end == p_end,
                    PulseGeneratedReport.created_at >= now_utc - timedelta(minutes=5),
                ).order_by(desc(PulseGeneratedReport.created_at))
            ).scalars().first()

            if recent_dup:
                logger.info(
                    "PulseService: Returning existing report %s (created %s) to prevent duplicate creation",
                    recent_dup.id,
                    recent_dup.created_at,
                )
                return recent_dup

        # 1. Compute full KPI framework
        kpis = PulseKPICatalogueEngine.compute_all_kpis(
            session=session,
            business_id=business_id,
            period_start=p_start,
            period_end=p_end,
            comparison_period_start=c_start,
            comparison_period_end=c_end,
        )

        # 2. Watermark status & provenance via TenantReadinessService (evaluated before text synthesis)
        from app.services.tenant_readiness_service import TenantReadinessService
        readiness = TenantReadinessService.get_tenant_readiness(session=session, business_id=business_id)

        # 3. Synthesize insights & executive text with explicit provenance
        period_label = f"{p_start.strftime('%b %d')} - {p_end.strftime('%b %d, %Y')}"
        title = report_title or f"Executive {report_type.value.replace('_', ' ').title()} ({period_label})"
        if readiness.is_synthetic and not title.startswith("[DEMO SYNTHETIC]"):
            title = f"[DEMO SYNTHETIC] {title}"

        report_id = str(uuid4())
        access_token = uuid4().hex
        report_url = f"{base_url}/pulse/reports/{report_id}?token={access_token}"

        insights, exec_summary, msg_summary = PulseInsightEngine.generate_insights_and_summaries(
            kpi_payload=kpis,
            business_name=biz.name,
            period_label=period_label,
            report_url=report_url,
            watermark_status=readiness.readiness_status.value,
            is_synthetic=readiness.is_synthetic,
        )

        # 4. Generate PDF publication
        pdf_bytes, pdf_hash = PulsePDFGenerator.generate_pdf_report(
            report_id=report_id,
            business_name=biz.name,
            period_label=period_label,
            kpi_payload=kpis,
            insights=insights,
            executive_summary=exec_summary,
            watermark_status=readiness.readiness_status.value,
            currency=biz.currency or "USD",
        )

        token_expiry = now_utc + timedelta(days=30)  # Secure link valid 30 days

        # 5. Persist Report Entity
        report = PulseGeneratedReport(
            id=report_id,
            business_id=business_id,
            organization_id=biz.organization_id,
            schedule_id=schedule_id,
            report_title=title,
            report_type=report_type.value,
            period_start=p_start,
            period_end=p_end,
            comparison_period_start=c_start,
            comparison_period_end=c_end,
            kpi_payload=kpis.model_dump(),
            insights_json=[ins.model_dump() for ins in insights],
            executive_summary=exec_summary,
            messaging_summary=msg_summary,
            pdf_storage_key=f"reports/{business_id}/{report_id}.pdf",
            pdf_sha256=pdf_hash,
            pdf_file_bytes=pdf_bytes,
            watermark_status=readiness.readiness_status.value,
            data_provenance_json={
                "watermark_cutoff": (
                    readiness.effective_complete_through_dt.isoformat()
                    if readiness.effective_complete_through_dt
                    else (readiness.latest_observed_date.isoformat() if readiness.latest_observed_date else None)
                ),
                "readiness_status": readiness.readiness_status.value,
                "is_synthetic": readiness.is_synthetic,
                "verified": readiness.is_actionable,
                "created_by": created_by,
                "generated_at": now_utc.isoformat(),
                "idempotency_key": idempotency_key,
            },
            access_token=access_token,
            token_expires_at=token_expiry,
        )
        session.add(report)
        session.commit()
        return report

    @classmethod
    def get_report(
        cls,
        session: Session,
        report_id: str,
        business_id: str | None = None,
        access_token: str | None = None,
    ) -> PulseReportDetail:
        """Retrieve full report detail by id, with tenant boundary or secure token check."""
        report = session.execute(
            select(PulseGeneratedReport).where(PulseGeneratedReport.id == report_id)
        ).scalar_one_or_none()
        if not report:
            raise FileNotFoundError(f"Report '{report_id}' does not exist.")

        if not business_id and not access_token:
            raise PermissionError("Authorization required: either business_id or access_token must be provided.")

        if business_id and report.business_id != business_id:
            raise PermissionError(f"Access denied: You do not have permission to access report '{report_id}'.")

        if access_token:
            if report.access_token != access_token:
                raise PermissionError("Access denied: Invalid report access token.")
            now_utc = datetime.now(UTC)
            if report.token_expires_at:
                exp = report.token_expires_at if report.token_expires_at.tzinfo else report.token_expires_at.replace(tzinfo=UTC)
                if exp < now_utc:
                    raise ValueError("Report access token has expired.")

        deliv_count = session.execute(
            select(func.count(PulseDeliveryLog.id)).where(PulseDeliveryLog.report_id == report.id)
        ).scalar() or 0

        return PulseReportDetail(
            id=report.id,
            business_id=report.business_id,
            report_title=report.report_title,
            report_type=ReportType(report.report_type),
            period_start=report.period_start.isoformat(),
            period_end=report.period_end.isoformat(),
            comparison_period_start=report.comparison_period_start.isoformat() if report.comparison_period_start else None,
            comparison_period_end=report.comparison_period_end.isoformat() if report.comparison_period_end else None,
            kpi_payload=PulseKPIPayload(**report.kpi_payload),
            insights=[PulseInsightItem(**item) for item in report.insights_json],
            executive_summary=report.executive_summary,
            messaging_summary=report.messaging_summary,
            pdf_available=bool(report.pdf_file_bytes),
            pdf_sha256=report.pdf_sha256,
            watermark_status=report.watermark_status,
            access_token=report.access_token,
            token_expires_at=report.token_expires_at.isoformat(),
            created_at=report.created_at.isoformat() if report.created_at else "",
            deliveries_count=deliv_count,
        )

    @classmethod
    def get_public_report_by_token(cls, session: Session, token: str) -> PulseReportDetail:
        """Retrieve report using secure unguessable expiring token."""
        report = session.execute(
            select(PulseGeneratedReport).where(PulseGeneratedReport.access_token == token)
        ).scalar_one_or_none()
        if not report:
            raise FileNotFoundError("Report not found for token.")
        now_utc = datetime.now(UTC)
        if report.token_expires_at:
            exp = report.token_expires_at if report.token_expires_at.tzinfo else report.token_expires_at.replace(tzinfo=UTC)
            if exp < now_utc:
                raise ValueError("Report access token has expired.")
        return cls.get_report(session, report_id=report.id, access_token=token)

    get_public_report = get_public_report_by_token

    @classmethod
    def get_report_pdf(
        cls,
        session: Session,
        report_id: str,
        business_id: str | None = None,
        access_token: str | None = None,
    ) -> tuple[bytes, str]:
        """Download raw PDF bytes and filename for report with strict tenant isolation and error differentiation."""
        report = session.execute(
            select(PulseGeneratedReport).where(PulseGeneratedReport.id == report_id)
        ).scalar_one_or_none()
        if not report:
            raise FileNotFoundError(f"Report '{report_id}' does not exist.")

        if not business_id and not access_token:
            raise PermissionError("Authorization required: either business_id or access_token must be provided.")

        if business_id and report.business_id != business_id:
            raise PermissionError(f"Access denied: You do not have permission to access report '{report_id}'.")

        if access_token:
            if report.access_token != access_token:
                raise PermissionError("Access denied: Invalid report access token.")
            now_utc = datetime.now(UTC)
            if report.token_expires_at:
                exp = report.token_expires_at if report.token_expires_at.tzinfo else report.token_expires_at.replace(tzinfo=UTC)
                if exp < now_utc:
                    raise ValueError("Report access token has expired.")

        if not report.pdf_file_bytes:
            raise FileNotFoundError(f"PDF artifact for report '{report_id}' is missing or not generated.")

        import re
        safe_title = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", report.report_title.replace("—", "-"))
        filename = f"NEXUS_Pulse_{safe_title}.pdf"
        return report.pdf_file_bytes, filename

    @classmethod
    def list_reports(
        cls,
        session: Session,
        business_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PulseReportListItem], int]:
        """List generated reports history for tenant."""
        count_stmt = select(func.count(PulseGeneratedReport.id)).where(PulseGeneratedReport.business_id == business_id)
        total = session.execute(count_stmt).scalar() or 0

        stmt = (
            select(PulseGeneratedReport)
            .where(PulseGeneratedReport.business_id == business_id)
            .order_by(desc(PulseGeneratedReport.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        reports = session.execute(stmt).scalars().all()

        items = []
        for r in reports:
            deliv_count = session.execute(
                select(func.count(PulseDeliveryLog.id)).where(PulseDeliveryLog.report_id == r.id)
            ).scalar() or 0
            items.append(
                PulseReportListItem(
                    id=r.id,
                    report_title=r.report_title,
                    report_type=ReportType(r.report_type),
                    period_start=r.period_start.isoformat(),
                    period_end=r.period_end.isoformat(),
                    created_at=r.created_at.isoformat() if r.created_at else "",
                    watermark_status=r.watermark_status,
                    pdf_available=bool(r.pdf_file_bytes),
                    access_token=r.access_token,
                    token_expires_at=r.token_expires_at.isoformat(),
                    deliveries_count=deliv_count,
                )
            )
        return items, total

    # --------------------------------------------------------------------------
    # SCHEDULE MANAGEMENT
    # --------------------------------------------------------------------------

    @classmethod
    def create_schedule(
        cls,
        session: Session,
        business_id: str,
        data: PulseScheduleCreateRequest,
        created_by: str = "User",
    ) -> PulseScheduleResponse:
        """Create a new reporting automation schedule."""
        biz = session.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        if not biz:
            raise ValueError(f"Business '{business_id}' does not exist.")

        next_run = PulseScheduler.calculate_next_run(
            frequency=data.frequency,
            time_of_day=data.time_of_day,
            timezone_str=data.timezone,
            day_of_month=data.day_of_month,
            day_of_week=data.day_of_week,
        )

        sched = PulseReportSchedule(
            business_id=business_id,
            organization_id=biz.organization_id,
            schedule_name=data.schedule_name,
            report_type=data.report_type.value,
            frequency=data.frequency.value,
            day_of_month=data.day_of_month,
            day_of_week=data.day_of_week,
            time_of_day=data.time_of_day,
            timezone=data.timezone,
            is_enabled=data.is_enabled,
            channel_types=[ch.value for ch in data.channel_types],
            recipients_json=[r.model_dump() for r in data.recipients],
            kpi_categories=[cat.value for cat in data.kpi_categories],
            alert_triggers=data.alert_triggers,
            next_run_at=next_run,
            created_by=created_by,
        )
        session.add(sched)
        session.commit()
        return cls._to_schedule_response(sched)

    @classmethod
    def update_schedule(
        cls,
        session: Session,
        business_id: str,
        schedule_id: int,
        data: PulseScheduleUpdateRequest,
    ) -> PulseScheduleResponse:
        """Update an existing reporting schedule."""
        sched = session.execute(
            select(PulseReportSchedule).where(
                PulseReportSchedule.id == schedule_id, PulseReportSchedule.business_id == business_id
            )
        ).scalar_one_or_none()
        if not sched:
            raise ValueError(f"Schedule {schedule_id} not found in business '{business_id}'.")

        if data.schedule_name is not None:
            sched.schedule_name = data.schedule_name
        if data.report_type is not None:
            sched.report_type = data.report_type.value
        if data.frequency is not None:
            sched.frequency = data.frequency.value
        if data.day_of_month is not None:
            sched.day_of_month = data.day_of_month
        if data.day_of_week is not None:
            sched.day_of_week = data.day_of_week
        if data.time_of_day is not None:
            sched.time_of_day = data.time_of_day
        if data.timezone is not None:
            sched.timezone = data.timezone
        if data.is_enabled is not None:
            sched.is_enabled = data.is_enabled
        if data.channel_types is not None:
            sched.channel_types = [ch.value for ch in data.channel_types]
        if data.recipients is not None:
            sched.recipients_json = [r.model_dump() for r in data.recipients]
        if data.kpi_categories is not None:
            sched.kpi_categories = [cat.value for cat in data.kpi_categories]
        if data.alert_triggers is not None:
            sched.alert_triggers = data.alert_triggers

        sched.next_run_at = PulseScheduler.calculate_next_run(
            frequency=sched.frequency,
            time_of_day=sched.time_of_day,
            timezone_str=sched.timezone,
            day_of_month=sched.day_of_month,
            day_of_week=sched.day_of_week,
        )
        session.commit()
        return cls._to_schedule_response(sched)

    @classmethod
    def delete_schedule(cls, session: Session, business_id: str, schedule_id: int) -> None:
        """Cancel and delete a schedule."""
        sched = session.execute(
            select(PulseReportSchedule).where(
                PulseReportSchedule.id == schedule_id, PulseReportSchedule.business_id == business_id
            )
        ).scalar_one_or_none()
        if not sched:
            raise ValueError(f"Schedule {schedule_id} not found in business '{business_id}'.")
        session.delete(sched)
        session.commit()

    @classmethod
    def list_schedules(cls, session: Session, business_id: str) -> list[PulseScheduleResponse]:
        """List all configured schedules for tenant."""
        stmt = (
            select(PulseReportSchedule)
            .where(PulseReportSchedule.business_id == business_id)
            .order_by(PulseReportSchedule.id.asc())
        )
        rows = session.execute(stmt).scalars().all()
        return [cls._to_schedule_response(s) for s in rows]

    # --------------------------------------------------------------------------
    # DISPATCH & AUDIT LOGS
    # --------------------------------------------------------------------------

    @classmethod
    def dispatch_test_report(
        cls,
        session: Session,
        business_id: str,
        data: PulseTestDispatchRequest,
        base_url: str = "https://nexus.internal",
    ) -> PulseDeliveryLogItem:
        """Send a test report notification to an authorized recipient."""
        report = session.execute(
            select(PulseGeneratedReport).where(
                PulseGeneratedReport.id == data.report_id,
                PulseGeneratedReport.business_id == business_id,
            )
        ).scalar_one_or_none()
        if not report:
            raise ValueError(f"Report '{data.report_id}' not found in business '{business_id}'.")

        biz = session.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        biz_name = biz.name if biz else "Business"

        report_url = f"{base_url}/pulse/reports/{report.id}?token={report.access_token}"
        payload = NotificationPayload(
            report_id=report.id,
            business_id=business_id,
            business_name=biz_name,
            report_title=f"[TEST] {report.report_title}",
            period_label=f"{report.period_start.strftime('%b %d')} - {report.period_end.strftime('%b %d, %Y')}",
            messaging_summary=f"🧪 *[TEST DISPATCH]*\n{report.messaging_summary}",
            executive_summary=report.executive_summary,
            report_url=report_url,
            pdf_bytes=report.pdf_file_bytes,
            pdf_filename=f"NEXUS_Pulse_{biz_name.replace(' ', '_')}_{report.id[:8]}.pdf",
            recipient_name=data.recipient_name,
            recipient_destination=data.destination,
            is_test=True,
            metadata={"organization_id": report.organization_id, "test_dispatch": True},
        )

        dispatcher = PulseNotificationDispatcher()
        _ = dispatcher.dispatch(session, payload, data.channel)

        # Retrieve the newly written log row
        log_entry = session.execute(
            select(PulseDeliveryLog).where(
                PulseDeliveryLog.report_id == report.id,
                PulseDeliveryLog.channel == data.channel.value,
                PulseDeliveryLog.recipient_destination == data.destination,
            ).order_by(desc(PulseDeliveryLog.id))
        ).scalars().first()

        if not log_entry:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve delivery log record after dispatch.",
            )
        return cls._to_delivery_log_item(log_entry)

    @classmethod
    def list_delivery_logs(
        cls,
        session: Session,
        business_id: str,
        report_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[PulseDeliveryLogItem], int]:
        """List delivery history audit trail."""
        count_stmt = select(func.count(PulseDeliveryLog.id)).where(PulseDeliveryLog.business_id == business_id)
        if report_id:
            count_stmt = count_stmt.where(PulseDeliveryLog.report_id == report_id)
        total = session.execute(count_stmt).scalar() or 0

        stmt = select(PulseDeliveryLog).where(PulseDeliveryLog.business_id == business_id)
        if report_id:
            stmt = stmt.where(PulseDeliveryLog.report_id == report_id)
        stmt = stmt.order_by(desc(PulseDeliveryLog.id)).offset((page - 1) * page_size).limit(page_size)

        rows = session.execute(stmt).scalars().all()
        return [cls._to_delivery_log_item(r) for r in rows], total

    @classmethod
    def retry_delivery(
        cls,
        session: Session,
        business_id: str,
        delivery_id: int,
        base_url: str = "https://nexus.internal",
    ) -> PulseDeliveryLogItem:
        """Retry a failed delivery attempt."""
        log_entry = session.execute(
            select(PulseDeliveryLog).where(
                PulseDeliveryLog.id == delivery_id, PulseDeliveryLog.business_id == business_id
            )
        ).scalar_one_or_none()
        if not log_entry:
            raise ValueError(f"Delivery log {delivery_id} not found in business '{business_id}'.")

        report = session.execute(
            select(PulseGeneratedReport).where(PulseGeneratedReport.id == log_entry.report_id)
        ).scalar_one_or_none()
        if not report:
            raise ValueError(f"Report '{log_entry.report_id}' not found.")

        biz = session.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        biz_name = biz.name if biz else "Business"

        report_url = f"{base_url}/pulse/reports/{report.id}?token={report.access_token}"
        channel = DeliveryChannel(log_entry.channel)

        payload = NotificationPayload(
            report_id=report.id,
            business_id=business_id,
            business_name=biz_name,
            report_title=f"[RETRY] {report.report_title}",
            period_label=f"{report.period_start.strftime('%b %d')} - {report.period_end.strftime('%b %d, %Y')}",
            messaging_summary=report.messaging_summary,
            executive_summary=report.executive_summary,
            report_url=report_url,
            pdf_bytes=report.pdf_file_bytes,
            pdf_filename=f"NEXUS_Pulse_{biz_name.replace(' ', '_')}_{report.id[:8]}.pdf",
            recipient_name=log_entry.recipient_name or "Manager",
            recipient_destination=log_entry.recipient_destination,
            is_test=False,
            metadata={"retry_of_delivery_id": delivery_id},
        )

        dispatcher = PulseNotificationDispatcher()
        res = dispatcher.dispatch(session, payload, channel)

        log_entry.attempts += 1
        log_entry.status = res.status.value
        log_entry.external_message_id = res.external_message_id
        log_entry.error_message = res.error_message
        log_entry.dispatched_at = res.dispatched_at
        log_entry.delivered_at = res.delivered_at
        session.commit()
        if not log_entry:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve delivery log record after dispatch.",
            )
        return cls._to_delivery_log_item(log_entry)

    # --------------------------------------------------------------------------
    # RECIPIENT PREFERENCES & OPT STATUS
    # --------------------------------------------------------------------------

    @classmethod
    def register_or_update_recipient(
        cls,
        session: Session,
        business_id: str,
        data: PulseRecipientOptRequest,
    ) -> PulseRecipientItem:
        """Register or update recipient opt status."""
        biz = session.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        if not biz:
            raise ValueError(f"Business '{business_id}' does not exist.")

        pref = session.execute(
            select(PulseRecipientPreference).where(
                PulseRecipientPreference.business_id == business_id,
                PulseRecipientPreference.channel == data.channel.value,
                PulseRecipientPreference.destination == data.destination,
            )
        ).scalar_one_or_none()

        if pref:
            pref.recipient_name = data.recipient_name
            pref.role = data.role
            pref.opt_status = data.opt_status.value
            pref.opt_out_reason = data.opt_out_reason
            pref.opted_at = datetime.now(UTC)
        else:
            pref = PulseRecipientPreference(
                business_id=business_id,
                organization_id=biz.organization_id,
                recipient_name=data.recipient_name,
                channel=data.channel.value,
                destination=data.destination,
                role=data.role,
                opt_status=data.opt_status.value,
                opt_out_reason=data.opt_out_reason,
            )
            session.add(pref)

        session.commit()
        return PulseRecipientItem(
            id=pref.id,
            recipient_name=pref.recipient_name,
            channel=DeliveryChannel(pref.channel),
            destination=pref.destination,
            role=pref.role,
            opt_status=RecipientOptStatus(pref.opt_status),
            opted_at=pref.opted_at.isoformat(),
            opt_out_reason=pref.opt_out_reason,
        )

    @classmethod
    def list_recipients(cls, session: Session, business_id: str) -> list[PulseRecipientItem]:
        """List registered recipients for tenant."""
        stmt = (
            select(PulseRecipientPreference)
            .where(PulseRecipientPreference.business_id == business_id)
            .order_by(PulseRecipientPreference.id.asc())
        )
        rows = session.execute(stmt).scalars().all()
        return [
            PulseRecipientItem(
                id=p.id,
                recipient_name=p.recipient_name,
                channel=DeliveryChannel(p.channel),
                destination=p.destination,
                role=p.role,
                opt_status=RecipientOptStatus(p.opt_status),
                opted_at=p.opted_at.isoformat(),
                opt_out_reason=p.opt_out_reason,
            )
            for p in rows
        ]

    # --------------------------------------------------------------------------
    # CHANNEL CONFIGURATION & SETTINGS
    # --------------------------------------------------------------------------

    @classmethod
    def get_channel_statuses(
        cls,
        session: Session,
        business_id: str,
    ) -> list[PulseChannelStatusItem]:
        """
        Inspect connection and readiness status across all 3 notification channels.
        Checks tenant-bound encrypted credentials and active environment settings.
        """
        from app.analytics.pulse.notifications.email import EmailNotificationAdapter
        from app.analytics.pulse.notifications.telegram import TelegramNotificationAdapter
        from app.analytics.pulse.notifications.whatsapp import WhatsAppNotificationAdapter
        from app.core.kms import EnvelopeEncryptionEngine, get_kms_provider

        kms = get_kms_provider()
        dispatcher = PulseNotificationDispatcher()
        statuses: list[PulseChannelStatusItem] = []

        # 1. EMAIL
        email_adapter = dispatcher.get_adapter(session, business_id, DeliveryChannel.EMAIL)
        is_email_live = email_adapter.is_live_configured
        email_cred = session.execute(
            select(TenantConnectorCredential).where(
                TenantConnectorCredential.business_id == business_id,
                TenantConnectorCredential.provider == "pulse_email",
                TenantConnectorCredential.status == "ACTIVE",
            )
        ).scalar_one_or_none()

        email_details: dict[str, Any] = {}
        if email_cred:
            try:
                decrypted = EnvelopeEncryptionEngine.decrypt_credentials(
                    envelope_str=email_cred.encrypted_credentials,
                    business_id=business_id,
                    provider="pulse_email",
                    provider_account_id=email_cred.provider_account_id,
                    kms_provider=kms,
                )
                email_details = {
                    "smtp_host": decrypted.get("smtp_host"),
                    "smtp_port": decrypted.get("smtp_port"),
                    "from_email": decrypted.get("from_email"),
                    "use_mailpit": decrypted.get("use_mailpit", False),
                }
            except Exception:
                email_details = {"error": "Failed to decrypt credentials"}

        if getattr(email_adapter, "is_mailpit", False):
            email_status = "LOCAL_MAILPIT"
            hint = f"Local Mailpit SMTP ({getattr(email_adapter, 'smtp_host', 'localhost')}:{getattr(email_adapter, 'smtp_port', 1025)}) — Zero Cost"
        elif is_email_live:
            email_status = "LIVE_CONFIGURED"
            hint = f"Live Corporate SMTP ({getattr(email_adapter, 'smtp_host', 'localhost')}:{getattr(email_adapter, 'smtp_port', 587)})"
        else:
            email_status = "SANDBOX_MOCK"
            hint = "Safe Simulated Rehearsal Mock"

        statuses.append(
            PulseChannelStatusItem(
                channel=DeliveryChannel.EMAIL,
                status=email_status,
                is_live=is_email_live,
                destination_hint=hint,
                provider_details=email_details,
                setup_guide="For zero cost, use Mailpit on port 1025 (Web UI at http://localhost:8025) or configure standard corporate SMTP.",
            )
        )

        # 2. TELEGRAM
        telegram_adapter = dispatcher.get_adapter(session, business_id, DeliveryChannel.TELEGRAM)
        is_tg_live = telegram_adapter.is_live_configured
        tg_cred = session.execute(
            select(TenantConnectorCredential).where(
                TenantConnectorCredential.business_id == business_id,
                TenantConnectorCredential.provider == "pulse_telegram",
                TenantConnectorCredential.status == "ACTIVE",
            )
        ).scalar_one_or_none()

        tg_details: dict[str, Any] = {}
        if tg_cred:
            try:
                decrypted = EnvelopeEncryptionEngine.decrypt_credentials(
                    envelope_str=tg_cred.encrypted_credentials,
                    business_id=business_id,
                    provider="pulse_telegram",
                    provider_account_id=tg_cred.provider_account_id,
                    kms_provider=kms,
                )
                raw_token = decrypted.get("bot_token", "")
                masked = f"***{raw_token[-6:]}" if len(raw_token) > 6 else "***"
                tg_details = {"bot_token_masked": masked, "tenant_configured": True}
            except Exception:
                tg_details = {"error": "Failed to decrypt credentials"}

        if is_tg_live:
            tg_status = "LIVE_CONFIGURED"
            tg_hint = "Telegram Bot Token Connected"
        else:
            tg_status = "SANDBOX_MOCK"
            tg_hint = "Safe Rehearsal Mock (Unconfigured)"

        statuses.append(
            PulseChannelStatusItem(
                channel=DeliveryChannel.TELEGRAM,
                status=tg_status,
                is_live=is_tg_live,
                destination_hint=tg_hint,
                provider_details=tg_details,
                setup_guide="Create a free bot with @BotFather on Telegram, paste the Bot Token, and start a chat with your bot to receive direct PDF reports.",
            )
        )

        # 3. WHATSAPP
        wa_adapter = dispatcher.get_adapter(session, business_id, DeliveryChannel.WHATSAPP)
        is_wa_live = wa_adapter.is_live_configured
        wa_cred = session.execute(
            select(TenantConnectorCredential).where(
                TenantConnectorCredential.business_id == business_id,
                TenantConnectorCredential.provider == "pulse_whatsapp",
                TenantConnectorCredential.status == "ACTIVE",
            )
        ).scalar_one_or_none()

        wa_details: dict[str, Any] = {}
        if wa_cred:
            try:
                decrypted = EnvelopeEncryptionEngine.decrypt_credentials(
                    envelope_str=wa_cred.encrypted_credentials,
                    business_id=business_id,
                    provider="pulse_whatsapp",
                    provider_account_id=wa_cred.provider_account_id,
                    kms_provider=kms,
                )
                wa_details = {
                    "phone_number_id": decrypted.get("phone_number_id"),
                    "business_account_id": decrypted.get("business_account_id"),
                    "tenant_configured": True,
                }
            except Exception:
                wa_details = {"error": "Failed to decrypt credentials"}

        if is_wa_live:
            wa_status = "LIVE_CONFIGURED"
            wa_hint = f"Meta WhatsApp Cloud API (Phone ID: {getattr(wa_adapter, 'phone_number_id', 'configured')})"
        else:
            wa_status = "SANDBOX_MOCK"
            wa_hint = "Safe Rehearsal Mock (Zero Cost)"

        statuses.append(
            PulseChannelStatusItem(
                channel=DeliveryChannel.WHATSAPP,
                status=wa_status,
                is_live=is_wa_live,
                destination_hint=wa_hint,
                provider_details=wa_details,
                setup_guide="Official Meta WhatsApp Business Cloud API requires verified Meta business account credentials. In local testing, Safe Rehearsal Mock runs at zero cost.",
            )
        )

        return statuses

    @classmethod
    def configure_channel(
        cls,
        session: Session,
        business_id: str,
        data: PulseChannelConfigureRequest,
    ) -> PulseChannelStatusItem:
        """
        Securely configure channel credentials for this tenant using AES-256-GCM envelope encryption.
        """
        from app.analytics.pulse.notifications.email import EmailNotificationAdapter
        from app.analytics.pulse.notifications.telegram import TelegramNotificationAdapter
        from app.analytics.pulse.notifications.whatsapp import WhatsAppNotificationAdapter

        provider_name = f"pulse_{data.channel.value.lower()}"
        account_id = f"{data.channel.value.lower()}_{business_id}"

        if data.channel == DeliveryChannel.EMAIL:
            if data.use_mailpit:
                mailpit_host = data.smtp_host.strip() if data.smtp_host else os.environ.get("SMTP_HOST", "nexus_mailpit_local")
                creds = {
                    "smtp_host": mailpit_host,
                    "smtp_port": data.smtp_port or int(os.environ.get("SMTP_PORT", "1025")),
                    "smtp_user": None,
                    "smtp_password": None,
                    "from_email": data.from_email or "pulse@nexus.local",
                    "use_mailpit": True,
                }
            else:
                if not data.smtp_host:
                    raise ValueError("SMTP host is required when not using Mailpit.")
                creds = {
                    "smtp_host": data.smtp_host.strip(),
                    "smtp_port": data.smtp_port or 587,
                    "smtp_user": data.smtp_user,
                    "smtp_password": data.smtp_password,
                    "from_email": data.from_email or "nexus-pulse@nexus.internal",
                    "use_mailpit": False,
                }
        elif data.channel == DeliveryChannel.TELEGRAM:
            if not data.bot_token or not data.bot_token.strip():
                raise ValueError("Telegram Bot Token is required.")
            raw_token = data.bot_token.strip()
            # Verify bot token with Telegram getMe API
            adapter = TelegramNotificationAdapter(bot_token=raw_token)
            verify_res = adapter.verify_bot_token()
            creds = {"bot_token": raw_token, "verification": verify_res}
        elif data.channel == DeliveryChannel.WHATSAPP:
            if not data.whatsapp_phone_number_id or not data.whatsapp_api_token:
                raise ValueError("WhatsApp Phone Number ID and API Token are required.")
            creds = {
                "phone_number_id": data.whatsapp_phone_number_id.strip(),
                "api_token": data.whatsapp_api_token.strip(),
                "business_account_id": data.whatsapp_business_account_id.strip() if data.whatsapp_business_account_id else None,
            }
        else:
            raise ValueError(f"Unsupported channel: {data.channel}")

        SourceSyncService.register_tenant_credentials(
            session=session,
            business_id=business_id,
            provider=provider_name,
            provider_account_id=account_id,
            credential_dict=creds,
            scopes=["pulse_notifications"],
        )
        session.commit()

        # Return updated status for this channel
        all_statuses = cls.get_channel_statuses(session, business_id)
        for s in all_statuses:
            if s.channel == data.channel:
                return s
        return all_statuses[0]

    @classmethod
    def disconnect_channel(
        cls,
        session: Session,
        business_id: str,
        channel: DeliveryChannel,
    ) -> PulseChannelStatusItem:
        """
        Disconnect a notification channel, revoking stored credentials and returning to sandbox mock.
        """
        provider_name = f"pulse_{channel.value.lower()}"
        existing = session.execute(
            select(TenantConnectorCredential).where(
                TenantConnectorCredential.business_id == business_id,
                TenantConnectorCredential.provider == provider_name,
            )
        ).scalar_one_or_none()

        if existing:
            session.delete(existing)
            session.commit()

        all_statuses = cls.get_channel_statuses(session, business_id)
        for s in all_statuses:
            if s.channel == channel:
                return s
        return all_statuses[0]

    @classmethod
    def verify_destination(
        cls,
        channel: DeliveryChannel,
        destination: str,
    ) -> PulseDestinationVerifyResponse:
        """Validate destination formatting without dispatching messages."""
        from app.analytics.pulse.notifications.email import EmailNotificationAdapter
        from app.analytics.pulse.notifications.telegram import TelegramNotificationAdapter
        from app.analytics.pulse.notifications.whatsapp import WhatsAppNotificationAdapter

        dest = destination.strip()
        if not dest:
            return PulseDestinationVerifyResponse(
                valid=False,
                channel=channel,
                destination=destination,
                error="Destination cannot be empty.",
            )

        try:
            if channel == DeliveryChannel.EMAIL:
                normalized = EmailNotificationAdapter().validate_email(dest)
                return PulseDestinationVerifyResponse(
                    valid=True,
                    channel=channel,
                    destination=dest,
                    normalized_destination=normalized,
                    metadata={"provider": "email_rfc822"},
                )
            elif channel == DeliveryChannel.TELEGRAM:
                normalized = TelegramNotificationAdapter().validate_chat_id(dest)
                return PulseDestinationVerifyResponse(
                    valid=True,
                    channel=channel,
                    destination=dest,
                    normalized_destination=normalized,
                    metadata={"provider": "telegram_chat_id"},
                )
            elif channel == DeliveryChannel.WHATSAPP:
                normalized = WhatsAppNotificationAdapter().validate_phone(dest)
                return PulseDestinationVerifyResponse(
                    valid=True,
                    channel=channel,
                    destination=dest,
                    normalized_destination=normalized,
                    metadata={"provider": "whatsapp_e164"},
                )
        except Exception as e:
            return PulseDestinationVerifyResponse(
                valid=False,
                channel=channel,
                destination=dest,
                error=str(e),
            )

        return PulseDestinationVerifyResponse(
            valid=False,
            channel=channel,
            destination=dest,
            error=f"Unknown channel: {channel}",
        )

    # --------------------------------------------------------------------------
    # SERIALIZATION HELPERS
    # --------------------------------------------------------------------------

    @classmethod
    def _to_schedule_response(cls, sched: PulseReportSchedule) -> PulseScheduleResponse:
        channels = [DeliveryChannel(ch) for ch in (sched.channel_types or [])]
        recipients = [PulseRecipientConfig(**r) for r in (sched.recipients_json or [])]
        cats = [KPICategory(c) for c in (sched.kpi_categories or [])]

        return PulseScheduleResponse(
            id=sched.id,
            business_id=sched.business_id,
            schedule_name=sched.schedule_name,
            report_type=ReportType(sched.report_type),
            frequency=ReportFrequency(sched.frequency),
            day_of_month=sched.day_of_month,
            day_of_week=sched.day_of_week,
            time_of_day=sched.time_of_day,
            timezone=sched.timezone,
            is_enabled=sched.is_enabled,
            channel_types=channels,
            recipients=recipients,
            kpi_categories=cats,
            alert_triggers=sched.alert_triggers or {},
            last_run_at=sched.last_run_at.isoformat() if sched.last_run_at else None,
            next_run_at=sched.next_run_at.isoformat() if sched.next_run_at else None,
            created_at=sched.created_at.isoformat() if sched.created_at else "",
        )

    @classmethod
    def _to_delivery_log_item(cls, log: PulseDeliveryLog) -> PulseDeliveryLogItem:
        return PulseDeliveryLogItem(
            id=log.id,
            report_id=log.report_id,
            channel=DeliveryChannel(log.channel),
            recipient_destination=log.recipient_destination,
            recipient_name=log.recipient_name,
            status=DeliveryStatus(log.status),
            external_message_id=log.external_message_id,
            error_message=log.error_message,
            attempts=log.attempts,
            dispatched_at=log.dispatched_at.isoformat() if log.dispatched_at else None,
            delivered_at=log.delivered_at.isoformat() if log.delivered_at else None,
            created_at=log.created_at.isoformat() if log.created_at else "",
        )

    @staticmethod
    def _normalize_dt(dt: datetime | date | None, default: datetime | None = None) -> datetime:
        if dt is None:
            return default or datetime.now(UTC)
        if isinstance(dt, date) and not isinstance(dt, datetime):
            return datetime.combine(dt, datetime.min.time(), tzinfo=UTC)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
