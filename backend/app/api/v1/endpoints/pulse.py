"""FastAPI endpoints for NEXUS Pulse: Management Intelligence & Automated Reporting."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.pulse.service import PulseService
from app.api.deps import get_db_session
from app.api.v1.endpoints.analytics import get_analytics_business_id
from app.core.auth import get_optional_current_user
from app.models.tenant import UserIdentity
from app.schemas.pulse import (
    DeliveryChannel,
    PulseChannelConfigureRequest,
    PulseChannelStatusItem,
    PulseDashboardOverview,
    PulseDeliveryLogItem,
    PulseDestinationVerifyRequest,
    PulseDestinationVerifyResponse,
    PulseGenerateReportRequest,
    PulseRecipientItem,
    PulseRecipientOptRequest,
    PulseReportDetail,
    PulseScheduleCreateRequest,
    PulseScheduleResponse,
    PulseScheduleUpdateRequest,
    PulseTestDispatchRequest,
)

router = APIRouter()


def _require_biz_id(biz_id: str | None) -> str:
    if not biz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context is required. Provide X-Business-ID header.",
        )
    return biz_id


# ==============================================================================
# 1. EXECUTIVE DASHBOARD OVERVIEW
# ==============================================================================

@router.get("/dashboard", response_model=PulseDashboardOverview, summary="Executive business intelligence dashboard")
def get_pulse_dashboard(
    date_from: datetime | None = Query(None, description="Start date (ISO 8601)"),
    date_to: datetime | None = Query(None, description="End date (ISO 8601)"),
    comparison_date_from: datetime | None = Query(None),
    comparison_date_to: datetime | None = Query(None),
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    return PulseService.get_dashboard_overview(
        session=db,
        business_id=valid_biz_id,
        date_from=date_from,
        date_to=date_to,
        comparison_date_from=comparison_date_from,
        comparison_date_to=comparison_date_to,
    )


# ==============================================================================
# 2. REPORT GENERATION & HISTORY
# ==============================================================================

@router.post("/reports/generate", summary="Ad-hoc executive report generation")
def generate_pulse_report(
    payload: PulseGenerateReportRequest,
    current_user: UserIdentity | None = Depends(get_optional_current_user),
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    creator = current_user.email if current_user else "Manager"
    try:
        report = PulseService.generate_report(
            session=db,
            business_id=valid_biz_id,
            report_type=payload.report_type,
            period_start=payload.date_from,
            period_end=payload.date_to,
            comparison_period_start=payload.comparison_date_from,
            comparison_period_end=payload.comparison_date_to,
            report_title=payload.report_title,
            created_by=creator,
            force_regenerate=payload.force_regenerate,
            idempotency_key=payload.idempotency_key,
        )
        return {
            "success": True,
            "data": {
                "report_id": report.id,
                "report_title": report.report_title,
                "report_type": report.report_type,
                "access_token": report.access_token,
                "token_expires_at": report.token_expires_at.isoformat(),
                "created_at": report.created_at.isoformat() if report.created_at else None,
            },
        }
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))


@router.get("/reports", summary="List generated reports history")
def list_pulse_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    items, total = PulseService.list_reports(db, valid_biz_id, page, page_size)
    return {"success": True, "data": {"items": items, "total_count": total, "page": page, "page_size": page_size}}


@router.get("/reports/{report_id}", response_model=PulseReportDetail, summary="Get full report detail")
def get_pulse_report(
    report_id: str,
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    try:
        return PulseService.get_report(db, report_id=report_id, business_id=valid_biz_id)
    except PermissionError as ex:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(ex))
    except FileNotFoundError as ex:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))
    except ValueError as ex:
        err_msg = str(ex).lower()
        if "expired" in err_msg:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(ex))
        if "access denied" in err_msg or "permission" in err_msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(ex))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))


@router.get("/reports/{report_id}/pdf", summary="Download PDF document for report")
def download_pulse_report_pdf(
    report_id: str,
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    try:
        pdf_bytes, filename = PulseService.get_report_pdf(db, report_id=report_id, business_id=valid_biz_id)
        import re
        clean_filename = re.sub(r"[^\x20-\x7E]+", "_", filename)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{clean_filename}"'},
        )
    except PermissionError as ex:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(ex))
    except FileNotFoundError as ex:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))
    except ValueError as ex:
        err_msg = str(ex).lower()
        if "expired" in err_msg:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(ex))
        if "access denied" in err_msg or "permission" in err_msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(ex))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))


@router.get("/public/reports/{token}", response_model=PulseReportDetail, summary="Token-authorized public report view")
def get_public_pulse_report(
    token: str,
    db: Session = Depends(get_db_session),
):
    """Secure, tenant-authorized, expiring report access without requiring session login."""
    try:
        return PulseService.get_public_report_by_token(db, token)
    except PermissionError as ex:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(ex))
    except FileNotFoundError as ex:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))
    except ValueError as ex:
        err_msg = str(ex).lower()
        if "expired" in err_msg:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(ex))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))


@router.get("/public/reports/{token}/pdf", summary="Token-authorized public report PDF download")
def download_public_pulse_report_pdf(
    token: str,
    db: Session = Depends(get_db_session),
):
    """Download PDF document using secure unguessable expiring token without session login."""
    try:
        report = PulseService.get_public_report_by_token(db, token)
        pdf_bytes, filename = PulseService.get_report_pdf(db, report_id=report.id, access_token=token)
        import re
        clean_filename = re.sub(r"[^\x20-\x7E]+", "_", filename)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{clean_filename}"'},
        )
    except PermissionError as ex:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(ex))
    except FileNotFoundError as ex:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))
    except ValueError as ex:
        err_msg = str(ex).lower()
        if "expired" in err_msg:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(ex))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))


# ==============================================================================
# 3. SCHEDULE MANAGEMENT
# ==============================================================================

@router.get("/schedules", response_model=list[PulseScheduleResponse], summary="List automated report schedules")
def list_pulse_schedules(
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    return PulseService.list_schedules(db, valid_biz_id)


@router.post("/schedules", response_model=PulseScheduleResponse, summary="Create automated report schedule")
def create_pulse_schedule(
    payload: PulseScheduleCreateRequest,
    current_user: UserIdentity | None = Depends(get_optional_current_user),
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    creator = current_user.email if current_user else "Manager"
    try:
        return PulseService.create_schedule(db, valid_biz_id, payload, created_by=creator)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))


@router.put("/schedules/{schedule_id}", response_model=PulseScheduleResponse, summary="Update automated report schedule")
def update_pulse_schedule(
    schedule_id: int,
    payload: PulseScheduleUpdateRequest,
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    try:
        return PulseService.update_schedule(db, valid_biz_id, schedule_id, payload)
    except ValueError as ex:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))


@router.delete("/schedules/{schedule_id}", summary="Delete automated report schedule")
def delete_pulse_schedule(
    schedule_id: int,
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    try:
        PulseService.delete_schedule(db, valid_biz_id, schedule_id)
        return {"success": True, "message": f"Schedule {schedule_id} deleted."}
    except ValueError as ex:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))


# ==============================================================================
# 4. DISPATCH, RECIPIENTS & DELIVERY LOGS
# ==============================================================================

@router.post("/dispatch/test", response_model=PulseDeliveryLogItem, summary="Send test report notification")
def send_test_dispatch(
    payload: PulseTestDispatchRequest,
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    try:
        return PulseService.dispatch_test_report(db, valid_biz_id, payload)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))


@router.get("/deliveries", summary="List delivery audit logs")
def list_pulse_deliveries(
    report_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    items, total = PulseService.list_delivery_logs(db, valid_biz_id, report_id, page, page_size)
    return {"success": True, "data": {"items": items, "total_count": total, "page": page, "page_size": page_size}}


@router.post("/deliveries/{delivery_id}/retry", response_model=PulseDeliveryLogItem, summary="Retry failed delivery")
def retry_pulse_delivery(
    delivery_id: int,
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    try:
        return PulseService.retry_delivery(db, valid_biz_id, delivery_id)
    except ValueError as ex:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))


@router.get("/recipients", response_model=list[PulseRecipientItem], summary="List registered report recipients")
def list_pulse_recipients(
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    return PulseService.list_recipients(db, valid_biz_id)


@router.post("/recipients/opt", response_model=PulseRecipientItem, summary="Register or update recipient opt status")
def update_recipient_opt_status(
    payload: PulseRecipientOptRequest,
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    try:
        return PulseService.register_or_update_recipient(db, valid_biz_id, payload)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))


# ==============================================================================
# 5. CHANNEL SETTINGS & CREDENTIAL CONFIGURATION
# ==============================================================================

@router.get(
    "/channels/status",
    response_model=list[PulseChannelStatusItem],
    summary="Get multi-channel readiness and connection statuses",
)
def get_pulse_channel_statuses(
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    return PulseService.get_channel_statuses(db, valid_biz_id)


@router.post(
    "/channels/configure",
    response_model=PulseChannelStatusItem,
    summary="Configure credentials or mode for a notification channel",
)
def configure_pulse_channel(
    payload: PulseChannelConfigureRequest,
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    try:
        return PulseService.configure_channel(db, valid_biz_id, payload)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))


@router.post(
    "/channels/disconnect",
    response_model=PulseChannelStatusItem,
    summary="Disconnect channel and return to safe rehearsal sandbox",
)
def disconnect_pulse_channel(
    channel: DeliveryChannel = Query(...),
    biz_id: str | None = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    valid_biz_id = _require_biz_id(biz_id)
    return PulseService.disconnect_channel(db, valid_biz_id, channel)


@router.post(
    "/channels/verify-destination",
    response_model=PulseDestinationVerifyResponse,
    summary="Validate syntax and reachable structure of a recipient destination",
)
def verify_pulse_destination(
    payload: PulseDestinationVerifyRequest,
):
    return PulseService.verify_destination(payload.channel, payload.destination)
