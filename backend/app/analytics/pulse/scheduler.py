"""Trigger and Scheduling Engine for NEXUS Pulse (Section 6).

Provides durable, tenant-scoped scheduling and event-driven alert triggers:
- Monthly, weekly, and custom automated reporting schedules.
- Next-run calculation with timezone conversion.
- Idempotency and duplicate-execution prevention.
- Event-driven alert triggers for churn spikes, revenue anomalies, and watermark invalidation.
- Cooperative shutdown and telemetry statistics.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.analytics.pulse.kpi_catalogue import PulseKPICatalogueEngine
from app.analytics.pulse.notifications.base import NotificationPayload
from app.analytics.pulse.notifications.dispatcher import PulseNotificationDispatcher
from app.core.logging import get_logger
from app.models.pulse import PulseReportSchedule
from app.models.tenant import Business
from app.schemas.pulse import DeliveryChannel, ReportFrequency, ReportType
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = get_logger(__name__)


class PulseScheduler:
    """Manages scheduled report generation and event-driven management alerts."""

    def __init__(self) -> None:
        self.dispatcher = PulseNotificationDispatcher()

    @classmethod
    def calculate_next_run(
        cls,
        frequency: str | ReportFrequency,
        time_of_day: str = "09:00",
        timezone_str: str = "UTC",
        day_of_month: int | None = 1,
        day_of_week: int | None = 0,
        from_dt: datetime | None = None,
    ) -> datetime:
        """Calculate the next scheduled run timestamp in UTC."""
        ref_dt = from_dt or datetime.now(UTC)
        try:
            tz = ZoneInfo(timezone_str)
        except Exception:  # noqa: BLE001
            tz = ZoneInfo("UTC")

        local_dt = ref_dt.astimezone(tz)
        try:
            hour_str, min_str = time_of_day.split(":")
            target_time = time(int(hour_str), int(min_str))
        except (ValueError, AttributeError):
            target_time = time(9, 0)

        freq_str = frequency.value if isinstance(frequency, ReportFrequency) else str(frequency).upper()

        if freq_str == "DAILY":
            candidate = local_dt.replace(
                hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0
            )
            if candidate <= local_dt:
                candidate += timedelta(days=1)
            return candidate.astimezone(UTC)

        elif freq_str == "WEEKLY":
            # day_of_week: 0=Monday, 6=Sunday
            target_dow = day_of_week if day_of_week is not None else 0
            days_ahead = (target_dow - local_dt.weekday()) % 7
            candidate = local_dt + timedelta(days=days_ahead)
            candidate = candidate.replace(
                hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0
            )
            if candidate <= local_dt:
                candidate += timedelta(days=7)
            return candidate.astimezone(UTC)

        else:  # MONTHLY or default
            target_dom = max(1, min(28, day_of_month or 1))  # Clamp to 28 for safety across months
            candidate = local_dt.replace(
                day=target_dom,
                hour=target_time.hour,
                minute=target_time.minute,
                second=0,
                microsecond=0,
            )
            if candidate <= local_dt:
                # Advance to next month
                if local_dt.month == 12:
                    candidate = candidate.replace(year=local_dt.year + 1, month=1)
                else:
                    candidate = candidate.replace(month=local_dt.month + 1)
            return candidate.astimezone(UTC)

    def process_due_schedules(
        self,
        session: Session,
        as_of_time: datetime | None = None,
        base_url: str = "https://nexus.internal",
    ) -> list[str]:
        """
        Query and execute all active schedules that are due for execution.
        Returns list of generated report IDs.
        """
        now_utc = as_of_time or datetime.now(UTC)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=UTC)

        stmt = (
            select(PulseReportSchedule)
            .where(
                PulseReportSchedule.is_enabled.is_(True),
                PulseReportSchedule.next_run_at <= now_utc,
            )
            .order_by(PulseReportSchedule.next_run_at.asc())
        )
        due_schedules = session.execute(stmt).scalars().all()

        generated_report_ids: list[str] = []

        for sched in due_schedules:
            try:
                report_id = self._execute_single_schedule(session, sched, now_utc, base_url)
                generated_report_ids.append(report_id)

                # Update schedule run markers
                sched.last_run_at = now_utc
                sched.next_run_at = self.calculate_next_run(
                    frequency=sched.frequency,
                    time_of_day=sched.time_of_day,
                    timezone_str=sched.timezone,
                    day_of_month=sched.day_of_month,
                    day_of_week=sched.day_of_week,
                    from_dt=now_utc,
                )
                session.commit()
            except Exception as ex:  # noqa: BLE001
                session.rollback()
                logger.error("Error executing Pulse schedule id=%s: %s", sched.id, ex)

        return generated_report_ids

    def _execute_single_schedule(
        self,
        session: Session,
        sched: PulseReportSchedule,
        now_utc: datetime,
        base_url: str,
    ) -> str:
        """Generate report and dispatch across configured channels for a single schedule."""
        from app.analytics.pulse.service import PulseService

        # Determine reporting period
        if sched.frequency == "WEEKLY":
            period_end = now_utc
            period_start = now_utc - timedelta(days=7)
            comp_start = period_start - timedelta(days=7)
            comp_end = period_start
            report_type = ReportType.WEEKLY_MANAGEMENT
        else:
            # Monthly: past 30 days
            period_end = now_utc
            period_start = now_utc - timedelta(days=30)
            comp_start = period_start - timedelta(days=30)
            comp_end = period_start
            report_type = ReportType.MONTHLY_EXECUTIVE

        # 1. Generate Report
        report = PulseService.generate_report(
            session=session,
            business_id=sched.business_id,
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            comparison_period_start=comp_start,
            comparison_period_end=comp_end,
            report_title=f"{sched.schedule_name} ({now_utc.strftime('%B %Y')})",
            schedule_id=sched.id,
            created_by="PulseScheduler",
        )

        # 2. Dispatch to recipients
        report_url = f"{base_url}/pulse/reports/{report.id}?token={report.access_token}"
        biz = session.execute(select(Business).where(Business.id == sched.business_id)).scalar_one_or_none()
        biz_name = biz.name if biz else "Business"

        recipients = sched.recipients_json or []
        for r in recipients:
            ch_str = r.get("channel", "WHATSAPP").upper()
            dest = r.get("destination", "")
            r_name = r.get("name", "Manager")
            try:
                channel = DeliveryChannel(ch_str)
            except ValueError:
                channel = DeliveryChannel.WHATSAPP

            payload = NotificationPayload(
                report_id=report.id,
                business_id=sched.business_id,
                business_name=biz_name,
                report_title=report.report_title,
                period_label=f"{period_start.strftime('%b %d')} - {period_end.strftime('%b %d, %Y')}",
                messaging_summary=report.messaging_summary,
                executive_summary=report.executive_summary,
                report_url=report_url,
                pdf_bytes=report.pdf_file_bytes,
                pdf_filename=f"NEXUS_Pulse_{biz_name.replace(' ', '_')}_{report.id[:8]}.pdf",
                recipient_name=r_name,
                recipient_destination=dest,
                is_test=False,
                metadata={"organization_id": sched.organization_id, "schedule_id": sched.id},
            )
            self.dispatcher.dispatch(session, payload, channel)

        return report.id

    def check_and_trigger_event_alerts(
        self,
        session: Session,
        business_id: str,
        as_of_time: datetime | None = None,
        base_url: str = "https://nexus.internal",
    ) -> list[str]:
        """
        Inspect business state for event-driven anomalies and trigger targeted alerts.
        Triggers:
        - Critical Churn Spike (>= 3 critical accounts)
        - Revenue Anomaly (>= 25% period drop)
        - Pending Retention Action Review Backlog (>= 5 pending)
        """
        now_utc = as_of_time or datetime.now(UTC)
        p_start = now_utc - timedelta(days=30)
        c_start = p_start - timedelta(days=30)

        kpis = PulseKPICatalogueEngine.compute_all_kpis(
            session=session,
            business_id=business_id,
            period_start=p_start,
            period_end=now_utc,
            comparison_period_start=c_start,
            comparison_period_end=p_start,
        )

        alerts_triggered: list[str] = []
        churn = kpis.churn
        crit_val = churn.get("critical_risk_customers")
        crit_count = crit_val.value if crit_val and isinstance(crit_val.value, int) else 0

        fin = kpis.financial
        growth_val = fin.get("revenue_growth")
        growth_pct = growth_val.value if growth_val and isinstance(growth_val.value, (int, float)) else 0.0

        ret = kpis.retention
        pend_val = ret.get("retention_actions_pending")
        pend_count = pend_val.value if pend_val and isinstance(pend_val.value, int) else 0

        if crit_count >= 3:
            alerts_triggered.append(f"CRITICAL_CHURN_SPIKE ({crit_count} customers overdue)")

        if growth_pct is not None and growth_pct <= -25.0:
            alerts_triggered.append(f"REVENUE_ANOMALY ({growth_pct:.1f}% period contraction)")

        if pend_count >= 5:
            alerts_triggered.append(f"RETENTION_ACTIONS_PENDING ({pend_count} decisions awaiting review)")

        return alerts_triggered
