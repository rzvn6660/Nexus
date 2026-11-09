"""
NEXUS Phase 1 End-to-End Production Readiness — Connector and Period-Close Evidence Endpoints.

Provides tenant-scoped API endpoints for:
1. Connector credential management (register, rotate, list status without secret leaks).
2. Sync checkpoint tracking (pagination, cursor recovery, records extracted).
3. Webhook inbox monitoring (events processed, quarantined, replay/retry status).
4. Cross-source reconciliation status.
5. Historical signed period-close package inspection and independent verification.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.auth import get_current_user
from app.models.connector import (
    ConnectorSyncCheckpoint,
    ConnectorWebhookInbox,
    TenantConnectorCredential,
)
from app.models.manifest import ManifestSubmission
from app.models.tenant import Business, OrganizationMembership, UserIdentity
from app.services.historical_evidence_package_service import HistoricalEvidencePackageService
from app.services.source_sync_service import SourceSyncService

router = APIRouter()


# ---------------------------------------------------------------------------
# Authorization Helper
# ---------------------------------------------------------------------------

def _verify_business_access(
    business_id: str,
    user: UserIdentity,
    db: Session,
    require_admin: bool = False,
) -> Business:
    biz = db.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
    if not biz:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business '{business_id}' not found.",
        )

    membership = db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == biz.organization_id,
        )
    ).scalar_one_or_none()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: User is not a member of the owning organization.",
        )

    if require_admin and membership.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Administrator privilege required for connector credential operations.",
        )

    return biz


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ConnectorCredentialRegisterRequest(BaseModel):
    business_id: str
    provider: str
    provider_account_id: str
    credentials: dict[str, Any]
    scopes: list[str] = Field(default_factory=list)
    kms_key_id: str = "local_kms_vault"


class ConnectorCredentialSummary(BaseModel):
    id: str
    business_id: str
    provider: str
    provider_account_id: str
    scopes: list[str]
    kms_key_id: str
    status: str
    created_at: datetime | None
    last_rotated_at: datetime | None
    credentials_masked: str = "***REDACTED***"


class CheckpointSummary(BaseModel):
    id: str
    provider: str
    sync_mode: str
    period_start: datetime
    period_end: datetime
    current_cursor: str | None
    status: str
    records_extracted: int
    worker_id: str | None
    last_attempt_at: datetime | None
    completed_at: datetime | None


class WebhookInboxStatusSummary(BaseModel):
    provider: str
    total_events: int
    completed_events: int
    quarantined_events: int
    pending_or_processing_events: int
    failed_events: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/credentials",
    response_model=list[ConnectorCredentialSummary],
    summary="List connector credential registrations without secret leaks",
)
def list_connector_credentials(
    business_id: str = Query(..., description="Tenant business ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[ConnectorCredentialSummary]:
    _verify_business_access(business_id, current_user, db)

    creds = db.execute(
        select(TenantConnectorCredential)
        .where(TenantConnectorCredential.business_id == business_id)
        .order_by(TenantConnectorCredential.provider.asc())
    ).scalars().all()

    return [
        ConnectorCredentialSummary(
            id=c.id,
            business_id=c.business_id,
            provider=c.provider,
            provider_account_id=c.provider_account_id,
            scopes=c.scopes or [],
            kms_key_id=c.kms_key_id,
            status=c.status,
            created_at=c.created_at,
            last_rotated_at=c.last_rotated_at,
            credentials_masked="***REDACTED***",
        )
        for c in creds
    ]


@router.post(
    "/credentials",
    response_model=ConnectorCredentialSummary,
    summary="Register or rotate connector credentials using envelope encryption",
)
def register_connector_credentials(
    req: ConnectorCredentialRegisterRequest,
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> ConnectorCredentialSummary:
    _verify_business_access(req.business_id, current_user, db, require_admin=True)

    cred = SourceSyncService.register_tenant_credentials(
        session=db,
        business_id=req.business_id,
        provider=req.provider,
        provider_account_id=req.provider_account_id,
        credential_dict=req.credentials,
        scopes=req.scopes,
        kms_key_id=req.kms_key_id,
    )
    db.commit()

    return ConnectorCredentialSummary(
        id=cred.id,
        business_id=cred.business_id,
        provider=cred.provider,
        provider_account_id=cred.provider_account_id,
        scopes=cred.scopes or [],
        kms_key_id=cred.kms_key_id,
        status=cred.status,
        created_at=cred.created_at,
        last_rotated_at=cred.last_rotated_at,
        credentials_masked="***REDACTED***",
    )


@router.get(
    "/checkpoints",
    response_model=list[CheckpointSummary],
    summary="Monitor connector sync checkpoints and pagination progress",
)
def list_sync_checkpoints(
    business_id: str = Query(...),
    provider: str | None = Query(None),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[CheckpointSummary]:
    _verify_business_access(business_id, current_user, db)

    stmt = select(ConnectorSyncCheckpoint).where(ConnectorSyncCheckpoint.business_id == business_id)
    if provider:
        stmt = stmt.where(ConnectorSyncCheckpoint.provider == provider)
    stmt = stmt.order_by(ConnectorSyncCheckpoint.period_start.desc())

    checkpoints = db.execute(stmt).scalars().all()
    return [
        CheckpointSummary(
            id=cp.id,
            provider=cp.provider,
            sync_mode=cp.sync_mode,
            period_start=cp.period_start,
            period_end=cp.period_end,
            current_cursor=cp.current_cursor,
            status=cp.status,
            records_extracted=cp.records_extracted,
            worker_id=cp.worker_id,
            last_attempt_at=cp.last_attempt_at,
            completed_at=cp.completed_at,
        )
        for cp in checkpoints
    ]


@router.get(
    "/webhooks/summary",
    response_model=list[WebhookInboxStatusSummary],
    summary="Summarize durable webhook event counts and quarantine status",
)
def get_webhook_inbox_summary(
    business_id: str = Query(...),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[WebhookInboxStatusSummary]:
    _verify_business_access(business_id, current_user, db)

    providers = db.execute(
        select(ConnectorWebhookInbox.provider)
        .where(ConnectorWebhookInbox.business_id == business_id)
        .distinct()
    ).scalars().all()

    summaries = []
    for prov in providers:
        counts = db.execute(
            select(
                ConnectorWebhookInbox.processing_status,
                func.count(ConnectorWebhookInbox.id),
            )
            .where(
                ConnectorWebhookInbox.business_id == business_id,
                ConnectorWebhookInbox.provider == prov,
            )
            .group_by(ConnectorWebhookInbox.processing_status)
        ).all()

        count_map = {status: count for status, count in counts}
        summaries.append(
            WebhookInboxStatusSummary(
                provider=prov,
                total_events=sum(count_map.values()),
                completed_events=count_map.get("COMPLETED", 0),
                quarantined_events=count_map.get("QUARANTINED", 0),
                pending_or_processing_events=count_map.get("PENDING", 0) + count_map.get("PROCESSING", 0),
                failed_events=count_map.get("FAILED", 0),
            )
        )

    return summaries


@router.get(
    "/period-close/history",
    summary="Inspect historical signed period-close packages and supersession lineage",
)
def get_period_close_history(
    business_id: str = Query(...),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[dict[str, Any]]:
    _verify_business_access(business_id, current_user, db)

    submissions = db.execute(
        select(ManifestSubmission)
        .where(ManifestSubmission.business_id == business_id)
        .order_by(ManifestSubmission.created_at.desc())
    ).scalars().all()

    results = []
    for sub in submissions:
        meta = sub.metadata_json or {}
        results.append({
            "manifest_id": sub.manifest_id,
            "period_start": sub.period_start.isoformat() if sub.period_start else None,
            "period_end": sub.period_end.isoformat() if sub.period_end else None,
            "verification_status": sub.verification_status,
            "signature_valid": sub.signature_valid,
            "dataset_identity_digest": sub.canonical_content_digest,
            "db_reconciled": sub.db_reconciled,
            "db_reconciled_at": sub.db_reconciled_at.isoformat() if sub.db_reconciled_at else None,
            "persisted_row_count": sub.db_persisted_row_count,
            "persisted_gross_total": str(sub.db_persisted_gross_total) if sub.db_persisted_gross_total is not None else None,
            "version_number": meta.get("version_number", 1),
            "supersedes_package_id": meta.get("supersedes_package_id"),
            "superseded_by_package_id": meta.get("superseded_by_package_id"),
            "is_superseded": meta.get("superseded_by_package_id") is not None,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        })

    return results


@router.post(
    "/period-close/{manifest_id}/verify-historical",
    summary="Independently verify historical cryptographic validity and current divergence",
)
def verify_historical_package(
    manifest_id: str,
    business_id: str = Query(...),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _verify_business_access(business_id, current_user, db)

    res = HistoricalEvidencePackageService.verify_historical_package(
        session=db,
        package_id=manifest_id,
        business_id=business_id,
    )

    return {
        "package_id": res.package_id,
        "version_number": res.version_number,
        "historical_signature_valid": res.historical_signature_valid,
        "signing_key_id": res.signing_key_id,
        "key_valid_at_signing": res.key_valid_at_signing,
        "key_status_at_signing": res.key_status_at_signing,
        "current_key_status": res.current_key_status,
        "canonical_digest_matches": res.canonical_digest_matches,
        "current_dataset_diverged": res.current_dataset_diverged,
        "divergence_details": res.divergence_details,
    }
