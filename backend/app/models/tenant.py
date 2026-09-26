"""SQLAlchemy ORM models for Multi-Tenant SaaS Identity, Organizations, and Workspaces (Phase 15).

Establishes strict ownership hierarchy:
UserIdentity
  ↓
Organization (Tenant)
  ↓
OrganizationMembership (Role: owner, admin, member)
  ↓
Business (Tenant-Scoped Workspace)
  ↓
UploadedDataset (Tenant-Scoped Files & Readiness)
"""

from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class UserIdentity(Base, TimestampMixin):
    """
    Application user identity.
    Stores authentication credentials, verified status, and linked organization memberships.
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        "OrganizationMembership",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Organization(Base, TimestampMixin):
    """
    Top-level Tenant entity.
    Isolates all organizational users, business workspaces, knowledge, and analytical data.
    """
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active", nullable=False, index=True
    )

    # Relationships
    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        "OrganizationMembership",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    businesses: Mapped[list["Business"]] = relationship(
        "Business",
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class OrganizationMembership(Base, TimestampMixin):
    """
    Links users to organizations with explicit roles:
    - owner: full administrative control, organization lifecycle
    - admin: business configuration, data ingestion, user management
    - member: read & query access to authorized workspaces
    """
    __tablename__ = "organization_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="member"
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="memberships"
    )
    user: Mapped["UserIdentity"] = relationship(
        "UserIdentity", back_populates="memberships"
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", name="uq_org_user_membership"
        ),
        Index("ix_membership_user_org", "user_id", "organization_id"),
    )


class Business(Base, TimestampMixin):
    """
    Tenant-Scoped Business Workspace.
    Every analytical dataset, sales record, customer, inventory item, OKF bundle,
    and analysis run belongs to exactly one Business.
    """
    __tablename__ = "businesses"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Retail & Distribution"
    )
    country: Mapped[str] = mapped_column(
        String(32), nullable=False, default="US"
    )
    currency: Mapped[str] = mapped_column(
        String(10), nullable=False, default="USD"
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC"
    )
    business_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="B2C"
    )
    fiscal_year_start: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active", nullable=False, index=True
    )
    onboarding_step: Mapped[str] = mapped_column(
        String(32), default="completed", nullable=False
    )
    data_readiness_status: Mapped[str] = mapped_column(
        String(32), default="not_ready", nullable=False
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="businesses"
    )
    datasets: Mapped[list["UploadedDataset"]] = relationship(
        "UploadedDataset",
        back_populates="business",
        cascade="all, delete-orphan",
    )


class UploadedDataset(Base, TimestampMixin):
    """
    Tracks uploaded customer files (CSV/XLSX), parsing status, data readiness,
    and storage keys isolated by organization and business.
    """
    __tablename__ = "uploaded_datasets"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    schema_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    quality_report_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    readiness_status: Mapped[str] = mapped_column(
        String(32), default="ready", nullable=False
    )

    # Relationships
    business: Mapped["Business"] = relationship(
        "Business", back_populates="datasets"
    )
