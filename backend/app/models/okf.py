"""SQLAlchemy ORM models for Business Context Knowledge Fabric (Phase 14D).

Stores portable OKF bundles and individual knowledge items (KPIs, concepts, rules, policies, calendars)
in PostgreSQL with complete audit provenance and version history.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class OKFBundleModel(Base, TimestampMixin):
    """
    SQLAlchemy model for an OKF Knowledge Bundle.
    Acts as a container for related business concepts, policies, and KPI definitions.
    """
    __tablename__ = "okf_bundles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bundle_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="verified", index=True)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    items: Mapped[list["OKFItemModel"]] = relationship(
        "OKFItemModel",
        back_populates="bundle",
        cascade="all, delete-orphan",
        order_by="OKFItemModel.item_id",
    )


class OKFItemModel(Base, TimestampMixin):
    """
    SQLAlchemy model for individual business knowledge items inside an OKF bundle.
    Stores machine-readable specifications, declarative formulas, synonyms, and governance metadata.
    """
    __tablename__ = "okf_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bundle_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("okf_bundles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # kpi, concept, rule, etc.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="verified", index=True)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="general", index=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Declarative computation & resolution
    formula: Mapped[str | None] = mapped_column(String(512), nullable=True)
    synonyms: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    canonical_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    analytics_tool: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metric_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_direction: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Rule / Policy fields
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str | None] = mapped_column(String(128), nullable=True)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True, default=100)

    # Relational & categorization
    related_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Unstructured description / definition
    content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    bundle: Mapped["OKFBundleModel"] = relationship("OKFBundleModel", back_populates="items")

    __table_args__ = (
        UniqueConstraint("bundle_id", "item_id", name="uq_okf_bundle_item"),
        Index("ix_okf_items_bundle_item", "bundle_id", "item_id"),
        Index("ix_okf_items_domain_type", "domain", "item_type"),
    )
