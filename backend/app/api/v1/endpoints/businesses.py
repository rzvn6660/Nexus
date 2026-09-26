"""Business Workspace management endpoints (Phase 15C & 15E).

Enforces server-side authorization and strict IDOR prevention:
- Only organization members with appropriate roles can access or modify businesses.
- Cross-tenant requests are strictly forbidden (HTTP 403).
"""

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.auth import get_auth_context, get_current_user, TenantContext
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity

router = APIRouter()


class BusinessCreateRequest(BaseModel):
    organization_id: str | None = None
    name: str = Field(..., min_length=2, max_length=255)
    industry: str = "Technology"
    country: str = "US"
    currency: str = "USD"
    timezone: str = "UTC"
    business_type: str = "B2B"
    fiscal_year_start: int = Field(1, ge=1, le=12)


class BusinessUpdateRequest(BaseModel):
    name: str | None = None
    industry: str | None = None
    country: str | None = None
    currency: str | None = None
    timezone: str | None = None
    business_type: str | None = None
    fiscal_year_start: int | None = Field(None, ge=1, le=12)
    onboarding_step: str | None = None


def _serialize_business(b: Business) -> dict[str, Any]:
    return {
        "id": b.id,
        "organization_id": b.organization_id,
        "name": b.name,
        "industry": b.industry,
        "country": b.country,
        "currency": b.currency,
        "timezone": b.timezone,
        "business_type": b.business_type,
        "fiscal_year_start": b.fiscal_year_start,
        "status": b.status,
        "onboarding_step": b.onboarding_step,
        "data_readiness_status": b.data_readiness_status,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "updated_at": b.updated_at.isoformat() if b.updated_at else None,
    }


@router.get("")
def list_businesses(
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """List all business workspaces across organizations the user belongs to."""
    user_org_ids = db.execute(
        select(OrganizationMembership.organization_id).where(
            OrganizationMembership.user_id == current_user.id
        )
    ).scalars().all()

    if not user_org_ids:
        return []

    businesses = db.execute(
        select(Business).where(Business.organization_id.in_(user_org_ids)).order_by(Business.name.asc())
    ).scalars().all()

    return [_serialize_business(b) for b in businesses]


@router.get("/{business_id}")
def get_business(
    business_id: str,
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Get business details with strict IDOR verification."""
    biz = db.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
    if not biz:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business '{business_id}' does not exist.",
        )

    # Verify user belongs to the owning organization
    membership = db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == current_user.id,
            OrganizationMembership.organization_id == biz.organization_id,
        )
    ).scalar_one_or_none()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to access this business workspace.",
        )

    return _serialize_business(biz)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_business(
    req: BusinessCreateRequest,
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Create a new business workspace under the user's organization."""
    # If organization_id is not provided, choose the user's primary organization
    target_org_id = req.organization_id
    if not target_org_id:
        membership = db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == current_user.id
            ).order_by(OrganizationMembership.created_at.asc())
        ).scalars().first()
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User does not belong to any organization.",
            )
        target_org_id = membership.organization_id

    # Check permission (owner or admin required)
    membership = db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == current_user.id,
            OrganizationMembership.organization_id == target_org_id,
        )
    ).scalar_one_or_none()

    if not membership or membership.role not in ["owner", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization owners and admins can create business workspaces.",
        )

    biz = Business(
        organization_id=target_org_id,
        name=req.name,
        industry=req.industry,
        country=req.country,
        currency=req.currency,
        timezone=req.timezone,
        business_type=req.business_type,
        fiscal_year_start=req.fiscal_year_start,
        status="active",
        onboarding_step="business_created",
    )
    db.add(biz)
    db.commit()
    db.refresh(biz)
    return _serialize_business(biz)


@router.patch("/{business_id}")
def update_business(
    business_id: str,
    req: BusinessUpdateRequest,
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Update business workspace settings with IDOR defense and role verification."""
    biz = db.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
    if not biz:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business '{business_id}' does not exist.",
        )

    membership = db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == current_user.id,
            OrganizationMembership.organization_id == biz.organization_id,
        )
    ).scalar_one_or_none()

    if not membership or membership.role not in ["owner", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization owners and admins can modify business workspace settings.",
        )

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(biz, key):
            setattr(biz, key, value)

    db.commit()
    db.refresh(biz)
    return _serialize_business(biz)


@router.delete("/{business_id}", status_code=status.HTTP_200_OK)
def delete_business(
    business_id: str,
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Delete a business workspace (Owner role required, strict IDOR prevention)."""
    biz = db.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
    if not biz:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business '{business_id}' does not exist.",
        )

    membership = db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == current_user.id,
            OrganizationMembership.organization_id == biz.organization_id,
        )
    ).scalar_one_or_none()

    if not membership or membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization owners can delete a business workspace.",
        )

    db.delete(biz)
    db.commit()
    return {"message": f"Business workspace '{business_id}' successfully deleted."}

