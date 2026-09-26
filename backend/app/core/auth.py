"""Tenant authorization context and FastAPI authentication dependencies (Phase 15E & 15I).

Enforces server-side authorization:
- Extracts and verifies JWT credentials from Authorization: Bearer <token>
- Resolves authenticated UserIdentity
- Validates OrganizationMembership and Business ownership
- Strictly prevents Insecure Direct Object Reference (IDOR) attacks
"""

from dataclasses import dataclass
from typing import Any
from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.config import settings
from app.models.tenant import (
    Business,
    Organization,
    OrganizationMembership,
    UserIdentity,
)
from app.services.auth_service import AuthService

bearer_security = HTTPBearer(auto_error=False)


@dataclass
class TenantContext:
    """Authenticated user context with verified organization and business workspace."""
    user: UserIdentity
    organization: Organization
    business: Business
    role: str

    @property
    def organization_id(self) -> str:
        return self.organization.id

    @property
    def business_id(self) -> str:
        return self.business.id

    @property
    def user_id(self) -> str:
        return self.user.id


def get_current_user(
    bearer_creds: HTTPAuthorizationCredentials | None = Security(bearer_security),
    db: Session = Depends(get_db_session),
) -> UserIdentity:
    """
    Authenticate request via JWT Bearer token.
    Raises HTTP 401 if token is missing, expired, or invalid.
    """
    if not bearer_creds or not bearer_creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided. Include 'Authorization: Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = AuthService.decode_access_token(bearer_creds.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token: missing user ID subject.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.execute(
        select(UserIdentity).where(UserIdentity.id == user_id)
    ).scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account associated with this token was not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    return user


def get_auth_context(
    request: Request,
    current_user: UserIdentity = Depends(get_current_user),
    x_business_id: str | None = Header(default=None, alias="X-Business-ID"),
    db: Session = Depends(get_db_session),
) -> TenantContext:
    """
    Resolve tenant boundary and verify authorization for requested business workspace.
    
    Guarantees:
    - Resolves organization membership for current_user
    - Validates business ownership
    - Throws HTTP 403 if user attempts to access a business outside their organizations (IDOR defense)
    - Never accepts organization_id or business_id blindly from client
    """
    # Check requested business_id from header or query param
    target_business_id = x_business_id or request.query_params.get("business_id")

    # Fetch user memberships
    stmt = (
        select(OrganizationMembership, Organization)
        .join(Organization, OrganizationMembership.organization_id == Organization.id)
        .where(OrganizationMembership.user_id == current_user.id)
        .where(Organization.status == "active")
    )
    results = db.execute(stmt).all()

    if not results:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any active organization.",
        )

    user_org_ids = [org.id for _, org in results]
    memberships_by_org = {org.id: (m, org) for m, org in results}

    if target_business_id:
        # User explicitly requested a specific business workspace
        biz = db.execute(
            select(Business).where(Business.id == target_business_id)
        ).scalar_one_or_none()

        if not biz:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Business workspace '{target_business_id}' does not exist.",
            )

        # IDOR Defense: Check if business belongs to one of user's organizations
        if biz.organization_id not in user_org_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not have permission to access this business workspace.",
            )

        membership, org = memberships_by_org[biz.organization_id]
        return TenantContext(
            user=current_user,
            organization=org,
            business=biz,
            role=membership.role,
        )

    # If no specific business requested, pick user's primary/first available business
    biz_stmt = (
        select(Business)
        .where(Business.organization_id.in_(user_org_ids))
        .where(Business.status == "active")
        .order_by(Business.created_at.asc())
    )
    primary_biz = db.execute(biz_stmt).scalars().first()

    if not primary_biz:
        # Fallback to any business under user's orgs (e.g. during onboarding)
        primary_biz = db.execute(
            select(Business).where(Business.organization_id.in_(user_org_ids))
        ).scalars().first()

    if not primary_biz:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No business workspace configured for user's organization. Please complete onboarding.",
        )

    membership, org = memberships_by_org[primary_biz.organization_id]
    return TenantContext(
        user=current_user,
        organization=org,
        business=primary_biz,
        role=membership.role,
    )
