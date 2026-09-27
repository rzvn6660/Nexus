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

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
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
    semantic_status: Mapped[str] = mapped_column(
        String(32), default="NOT_ACTIVATED", nullable=False
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
    semantic_models: Mapped[list["TenantSemanticModel"]] = relationship(
        "TenantSemanticModel",
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
    content_hash: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True, doc="SHA-256 content fingerprint for idempotency"
    )
    schema_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    quality_report_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    readiness_status: Mapped[str] = mapped_column(
        String(32), default="ready", nullable=False
    )

    # Relationships
    business: Mapped["Business"] = relationship(
        "Business", back_populates="datasets"
    )
    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship(
        "IngestionJob", back_populates="dataset", cascade="all, delete-orphan"
    )


class IngestionJob(Base, TimestampMixin):
    """
    Durable tracking of data ingestion lifecycle jobs.
    Lifecycle states: PENDING, PROCESSING, COMPLETED, FAILED, REQUIRES_REVIEW.
    """
    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("uploaded_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", nullable=False, index=True
    )  # PENDING, PROCESSING, COMPLETED, FAILED, REQUIRES_REVIEW
    target_entity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rows_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Relationships
    dataset: Mapped["UploadedDataset"] = relationship(
        "UploadedDataset", back_populates="ingestion_jobs"
    )


class TenantSemanticModel(Base, TimestampMixin):
    """
    Persistent, tenant-specific Business Understanding and Semantic Model (Phase 17).

    Binds raw customer data and mapped domain entities to:
    - Entity and field inventories
    - Tenant-specific metric availability (AVAILABLE, REQUIRES_COST_DATA, INSUFFICIENT_HISTORY)
    - Custom business synonyms and terminology mappings
    - Detected ambiguities requiring user clarification
    - Deterministic business data summaries
    - Versioned configuration history for reproducible analytical explanations
    """
    __tablename__ = "tenant_semantic_models"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(32), default="ACTIVE", nullable=False, index=True
    )  # NOT_ACTIVATED, ACTIVATING, ACTIVE, REQUIRES_REVIEW, FAILED
    source_dataset_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("uploaded_datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    entities_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    dimensions_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    synonyms_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ambiguous_terms_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    business_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    conflicts_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    business: Mapped["Business"] = relationship(
        "Business", back_populates="semantic_models"
    )
    source_dataset: Mapped["UploadedDataset | None"] = relationship(
        "UploadedDataset"
    )

    __table_args__ = (
        UniqueConstraint(
            "business_id", "version", name="uq_business_semantic_version"
        ),
        Index("ix_tenant_semantic_business_status", "business_id", "status"),
    )
