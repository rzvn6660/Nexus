"""Business Onboarding workflow endpoints (Phase 15F).

Steps:
1. Create/Configure Business (name, industry, country, currency, timezone, business type, fiscal year)
2. Optional: Teach NEXUS Your Business (business context / OKF bundle)
3. Connect Your Data (CSV/XLSX file upload, tenant-isolated storage, profiling, data readiness)
"""

from typing import Any
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.auth import get_auth_context, TenantContext
from app.services.tenant_data_service import TenantDataService

router = APIRouter()


class BusinessConfigureRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    industry: str = "Technology"
    country: str = "US"
    currency: str = "USD"
    timezone: str = "UTC"
    business_type: str = "B2B"
    fiscal_year_start: int = Field(1, ge=1, le=12)


class BusinessContextRequest(BaseModel):
    skip: bool = False
    business_summary: str | None = None
    kpi_definitions: list[dict[str, str]] | None = None
    terminology: dict[str, str] | None = None


@router.get("/status")
def get_onboarding_status(
    context: TenantContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Get the onboarding status and data readiness for the current business workspace."""
    readiness = TenantDataService.get_data_readiness(db, context.business_id)
    return {
        "business_id": context.business_id,
        "business_name": context.business.name,
        "onboarding_step": context.business.onboarding_step,
        "data_readiness_status": context.business.data_readiness_status,
        "readiness_report": readiness,
    }


@router.post("/business")
def configure_business_step(
    req: BusinessConfigureRequest,
    context: TenantContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Step 1: Configure business workspace identity and financial settings."""
    biz = context.business
    biz.name = req.name
    biz.industry = req.industry
    biz.country = req.country
    biz.currency = req.currency
    biz.timezone = req.timezone
    biz.business_type = req.business_type
    biz.fiscal_year_start = req.fiscal_year_start
    biz.onboarding_step = "business_configured"

    db.commit()
    db.refresh(biz)

    return {
        "message": "Business configuration saved.",
        "business": {
            "id": biz.id,
            "name": biz.name,
            "industry": biz.industry,
            "currency": biz.currency,
            "timezone": biz.timezone,
            "onboarding_step": biz.onboarding_step,
        },
    }


@router.post("/context")
def configure_context_step(
    req: BusinessContextRequest,
    context: TenantContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Step 2 (Optional): Teach NEXUS your business context or OKF rules. Can be skipped."""
    biz = context.business

    if req.skip:
        biz.onboarding_step = "context_skipped"
        db.commit()
        return {"message": "Business context skipped.", "step": biz.onboarding_step}

    # Store business context if provided
    biz.onboarding_step = "context_configured"
    db.commit()

    return {
        "message": "Business context recorded successfully.",
        "step": biz.onboarding_step,
    }


@router.post("/data")
async def upload_onboarding_data_step(
    file: UploadFile = File(...),
    context: TenantContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Step 3: Connect your data via CSV or XLSX.
    Validates file, saves to tenant-isolated storage, runs data profiling, and assesses readiness.
    """
    biz = context.business
    content = await file.read()

    dataset, report = TenantDataService.save_and_profile_file(
        db=db,
        organization_id=context.organization_id,
        business_id=context.business_id,
        filename=file.filename or "uploaded_data.csv",
        content=content,
        content_type=file.content_type,
    )

    biz.onboarding_step = "completed"
    db.commit()
    db.refresh(biz)

    return {
        "message": "Dataset uploaded and analyzed successfully.",
        "dataset_id": dataset.id,
        "filename": dataset.filename,
        "readiness_status": dataset.readiness_status,
        "profile": report,
        "step": biz.onboarding_step,
    }


@router.post("/complete")
def complete_onboarding(
    context: TenantContext = Depends(get_auth_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Mark onboarding as completed for this business."""
    biz = context.business
    biz.onboarding_step = "completed"
    db.commit()
    return {"message": "Onboarding completed.", "business_id": biz.id, "status": "completed"}
