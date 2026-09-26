"""Authentication and Identity Service for NEXUS Multi-Tenant SaaS (Phase 15B).

Provides:
- Cryptographic password hashing & constant-time verification (PBKDF2-HMAC-SHA256)
- Production-grade JWT token signing & verification (PyJWT)
- User signup with automatic Organization, Owner Membership, and Business provisioning
- User login and session credential issuance
- Multi-organization membership resolution
"""

import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tenant import (
    Business,
    Organization,
    OrganizationMembership,
    UserIdentity,
)


class AuthService:
    """Service handling identity lifecycle, password hashing, and JWT tokens."""

    SALT_BYTES = 16
    PBKDF2_ITERATIONS = 100_000
    MAX_PASSWORD_LENGTH = 128
    _revoked_tokens: set[str] = set()
    _dummy_hash: str = "00" * 16 + "$" + "00" * 32

    @classmethod
    def hash_password(cls, password: str) -> str:
        """Hash a plaintext password using salted PBKDF2-HMAC-SHA256."""
        if not password or len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if len(password) > cls.MAX_PASSWORD_LENGTH:
            raise ValueError(f"Password exceeds maximum allowable length of {cls.MAX_PASSWORD_LENGTH} characters.")
        if not password.strip():
            raise ValueError("Password cannot consist entirely of whitespace.")
        salt = os.urandom(cls.SALT_BYTES)
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            cls.PBKDF2_ITERATIONS,
        )
        return f"{salt.hex()}${derived.hex()}"

    @classmethod
    def verify_password(cls, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against stored salt and hash in constant time."""
        if not plain_password or not hashed_password or "$" not in hashed_password:
            return False
        parts = hashed_password.split("$", 1)
        if len(parts) != 2:
            return False
        salt_hex, expected_hash_hex = parts
        try:
            salt = bytes.fromhex(salt_hex)
            expected_hash = bytes.fromhex(expected_hash_hex)
        except ValueError:
            return False

        actual_hash = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt,
            cls.PBKDF2_ITERATIONS,
        )
        return hmac.compare_digest(actual_hash, expected_hash)

    @classmethod
    def revoke_token(cls, token_or_jti: str) -> None:
        """Revoke a token by its jti identifier or raw JWT string."""
        if "." in token_or_jti:
            try:
                unverified = jwt.decode(token_or_jti, options={"verify_signature": False})
                jti = unverified.get("jti")
                if jti:
                    cls._revoked_tokens.add(jti)
            except Exception:
                pass
        else:
            cls._revoked_tokens.add(token_or_jti)

    @classmethod
    def is_token_revoked(cls, jti: str | None) -> bool:
        """Check if token jti has been marked revoked."""
        if not jti:
            return False
        return jti in cls._revoked_tokens

    @classmethod
    def create_access_token(
        cls,
        user_id: str,
        email: str,
        full_name: str | None = None,
        organization_id: str | None = None,
        business_id: str | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        """Issue a signed JWT access token for an authenticated user."""
        now = datetime.now(timezone.utc)
        delta = expires_delta or timedelta(minutes=settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {
            "sub": user_id,
            "email": email.lower().strip(),
            "full_name": full_name or "",
            "org_id": organization_id,
            "biz_id": business_id,
            "iat": now,
            "exp": now + delta,
            "iss": "nexus-saas",
            "jti": str(uuid4()),
        }
        return jwt.encode(
            payload,
            settings.AUTH_JWT_SECRET,
            algorithm=settings.AUTH_JWT_ALGORITHM,
        )

    @classmethod
    def decode_access_token(cls, token: str) -> dict[str, Any]:
        """Decode and verify a JWT access token, enforcing expiration and signature."""
        try:
            payload = jwt.decode(
                token,
                settings.AUTH_JWT_SECRET,
                algorithms=[settings.AUTH_JWT_ALGORITHM],
                options={"verify_exp": True, "require": ["sub", "exp", "iat"]},
                issuer="nexus-saas",
            )
            if cls.is_token_revoked(payload.get("jti")):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication token has been revoked. Please log in again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return payload
        except HTTPException:
            raise
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has expired. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid authentication token: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @classmethod
    def signup(
        cls,
        email: str,
        password: str,
        full_name: str | None = None,
        organization_name: str | None = None,
        business_name: str | None = None,
        session: Session | None = None,
        db: Session | None = None,
    ) -> tuple[UserIdentity, Organization, Business, str]:
        """
        Register a new user, create their root Organization, grant Owner role,
        and provision an initial Business workspace.
        """
        s = session or db
        if not s:
            raise ValueError("Database session must be provided.")
        clean_email = email.lower().strip()
        name = full_name.strip() if full_name and full_name.strip() else "User"
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", clean_email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email format.",
            )

        # Check existing user
        existing_user = s.execute(
            select(UserIdentity).where(UserIdentity.email == clean_email)
        ).scalar_one_or_none()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )

        # 1. Create User
        pwd_hash = cls.hash_password(password)
        user = UserIdentity(
            id=str(uuid4()),
            email=clean_email,
            password_hash=pwd_hash,
            full_name=name,
            is_active=True,
            is_verified=True,
        )
        s.add(user)
        s.flush()

        # 2. Create Organization
        org_name = organization_name.strip() if organization_name and organization_name.strip() else f"{name}'s Org"
        slug_base = re.sub(r"[^a-z0-9]+", "-", org_name.lower()).strip("-") or "org"
        slug = f"{slug_base}-{str(uuid4())[:8]}"

        org = Organization(
            id=str(uuid4()),
            name=org_name,
            slug=slug,
            status="active",
        )
        s.add(org)
        s.flush()

        # 3. Create Owner Membership
        membership = OrganizationMembership(
            organization_id=org.id,
            user_id=user.id,
            role="owner",
        )
        s.add(membership)
        s.flush()

        # 4. Create Default Business Workspace
        primary_biz_name = business_name.strip() if business_name and business_name.strip() else f"{org_name} Primary"
        biz = Business(
            id=str(uuid4()),
            organization_id=org.id,
            name=primary_biz_name,
            industry="Retail & Distribution",
            country="US",
            currency="USD",
            timezone="UTC",
            business_type="B2C",
            fiscal_year_start=1,
            status="active",
            onboarding_step="completed",
            data_readiness_status="ready",
        )
        s.add(biz)
        s.commit()
        s.refresh(user)
        s.refresh(org)
        s.refresh(biz)

        return user, org, biz

    @classmethod
    def authenticate(
        cls,
        email: str,
        password: str,
        session: Session | None = None,
        db: Session | None = None,
    ) -> UserIdentity | None:
        """Verify user credentials and return UserIdentity if valid, else None."""
        s = session or db
        if not s:
            raise ValueError("Database session must be provided.")
        clean_email = email.lower().strip()
        user = s.execute(
            select(UserIdentity).where(UserIdentity.email == clean_email)
        ).scalar_one_or_none()

        if not user:
            # Perform dummy PBKDF2 calculation to prevent timing-based account enumeration
            cls.verify_password(password, cls._dummy_hash)
            return None

        if not cls.verify_password(password, user.password_hash):
            return None

        if not user.is_active:
            return None

        return user

    @classmethod
    def login(
        cls,
        email: str,
        password: str,
        session: Session | None = None,
        db: Session | None = None,
    ) -> tuple[UserIdentity, str]:
        """Authenticate user credentials and issue an access token."""
        user = cls.authenticate(email=email, password=password, session=session, db=db)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = cls.create_access_token(user_id=user.id, email=user.email, full_name=user.full_name)
        return user, token

    @classmethod
    def get_user_tenants(
        cls,
        user_id: str,
        session: Session | None = None,
        db: Session | None = None,
    ) -> list[dict[str, Any]]:
        """Return list of organizations and businesses accessible to user."""
        s = session or db
        if not s:
            raise ValueError("Database session must be provided.")
        memberships = s.execute(
            select(OrganizationMembership).where(OrganizationMembership.user_id == user_id)
        ).scalars().all()

        tenants = []
        for m in memberships:
            org = m.organization
            businesses = s.execute(
                select(Business).where(Business.organization_id == org.id)
            ).scalars().all()

            tenants.append({
                "organization_id": org.id,
                "organization_name": org.name,
                "organization_slug": org.slug,
                "role": m.role,
                "businesses": [
                    {
                        "id": b.id,
                        "name": b.name,
                        "industry": b.industry,
                        "currency": b.currency,
                        "status": b.status,
                        "data_readiness_status": b.data_readiness_status,
                        "onboarding_step": b.onboarding_step,
                    }
                    for b in businesses
                ],
            })
        return tenants
