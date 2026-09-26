"""Authentication and Identity endpoints (Phase 15B).

Supports:
- POST /api/v1/auth/signup
- POST /api/v1/auth/login
- GET /api/v1/auth/me
- POST /api/v1/auth/refresh
"""

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.auth import get_current_user
from app.models.tenant import UserIdentity
from app.services.auth_service import AuthService

router = APIRouter()

EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SignupRequest(BaseModel):
    email: str = Field(..., pattern=EMAIL_REGEX, description="Valid email address")
    password: str = Field(..., min_length=8, description="Minimum 8 characters")
    full_name: str | None = None
    organization_name: str | None = None
    business_name: str | None = None


class LoginRequest(BaseModel):
    email: str = Field(..., pattern=EMAIL_REGEX, description="Valid email address")
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]
    organization: dict[str, Any] | None = None
    business: dict[str, Any] | None = None


class UserProfileResponse(BaseModel):
    user: dict[str, Any]
    tenants: list[dict[str, Any]]


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(req: SignupRequest, db: Session = Depends(get_db_session)) -> TokenResponse:
    """Create a new user account, organization, and primary business workspace."""
    try:
        user, org, biz = AuthService.signup(
            db=db,
            email=req.email,
            password=req.password,
            full_name=req.full_name,
            organization_name=req.organization_name,
            business_name=req.business_name,
        )
        token = AuthService.create_access_token(
            user_id=user.id,
            email=user.email,
            organization_id=org.id,
            business_id=biz.id,
        )
        return TokenResponse(
            access_token=token,
            user={
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
            },
            organization={
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
            },
            business={
                "id": biz.id,
                "name": biz.name,
                "industry": biz.industry,
                "currency": biz.currency,
                "onboarding_step": biz.onboarding_step,
                "data_readiness_status": biz.data_readiness_status,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db_session)) -> TokenResponse:
    """Authenticate with email and password, returning a signed JWT access token."""
    user = AuthService.authenticate(db=db, email=req.email, password=req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tenants = AuthService.get_user_tenants(db=db, user_id=user.id)
    primary_org = tenants[0]["organization"] if tenants else None
    primary_biz = tenants[0]["businesses"][0] if tenants and tenants[0]["businesses"] else None

    token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        organization_id=primary_org["id"] if primary_org else None,
        business_id=primary_biz["id"] if primary_biz else None,
    )

    return TokenResponse(
        access_token=token,
        user={
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
        },
        organization=primary_org,
        business=primary_biz,
    )


@router.get("/me", response_model=UserProfileResponse)
def get_current_user_profile(
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> UserProfileResponse:
    """Return authenticated user profile and all authorized organizations and business workspaces."""
    tenants = AuthService.get_user_tenants(db=db, user_id=current_user.id)
    return UserProfileResponse(
        user={
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "is_active": current_user.is_active,
            "is_verified": current_user.is_verified,
            "created_at": current_user.created_at.isoformat(),
        },
        tenants=tenants,
    )
