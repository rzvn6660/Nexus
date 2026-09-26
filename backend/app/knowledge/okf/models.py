"""Organizational Knowledge Fabric (OKF) Pydantic Models for NEXUS (Phase 14).

Defines the contract for portable business knowledge bundles:
- Bundle metadata & manifest
- Company profile
- Business concepts
- KPI definitions, formulas, and synonyms
- Operating rules and policies
- Operating calendar & seasonality
- Provenance, verification status, and temporal validity

Architecture Invariants:
1. Business context defines what terms mean, how KPIs are calculated, and what policies apply.
2. Actual business data and deterministic analytics determine what happened.
3. Business context NEVER overrides actual data or evidence.
4. Arbitrary executable code is strictly forbidden.
"""

from datetime import date, datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, field_validator


class OKFItemType(str, Enum):
    """Supported business knowledge entity types."""
    BUNDLE = "bundle"
    COMPANY_PROFILE = "company_profile"
    CONCEPT = "concept"
    KPI = "kpi"
    RULE = "rule"
    POLICY = "policy"
    CALENDAR = "calendar"


class OKFStatus(str, Enum):
    """Lifecycle / verification status of a business knowledge item."""
    VERIFIED = "verified"
    DRAFT = "draft"
    DEPRECATED = "deprecated"


class OKFProvenance(BaseModel):
    """Source provenance and audit trail for an OKF item."""
    source: str = Field(..., description="Document, policy, or executive reference establishing this definition.")
    author: str | None = Field(default=None, description="Author or department originating the definition.")
    verified_by: str | None = Field(default=None, description="Sign-off authority verifying the definition.")
    created_at: datetime | None = Field(default=None, description="Timestamp of definition creation.")
    updated_at: datetime | None = Field(default=None, description="Timestamp of last revision.")
    notes: str | None = Field(default=None, description="Audit or compliance notes.")


class OKFItem(BaseModel):
    """
    Base portable unit of business knowledge.
    Separates definition, formula/computation, provenance, status, and temporal validity.
    """
    id: str = Field(..., description="Stable machine-readable slug identifier (e.g. kpi_gross_profit).")
    name: str = Field(..., description="Human-readable title or display name.")
    type: OKFItemType = Field(..., description="Item type.")
    version: int = Field(default=1, ge=1, description="Integer version of this item definition.")
    status: OKFStatus = Field(default=OKFStatus.VERIFIED, description="Verification status.")
    source: str = Field(..., description="Source reference or document provenance.")
    author: str | None = Field(default=None, description="Authoring role or user.")
    verified_by: str | None = Field(default=None, description="Role or user who verified this definition.")
    domain: str = Field(default="general", description="Business domain (finance, inventory, customers, merchandising, etc.).")
    effective_from: date | datetime | None = Field(default=None, description="Start date of validity.")
    effective_to: date | datetime | None = Field(default=None, description="End date of validity.")
    related_to: list[str] = Field(default_factory=list, description="IDs of related concepts, KPIs, or policies.")
    tags: list[str] = Field(default_factory=list, description="Categorization tags.")
    description: str = Field(default="", description="Markdown body explaining definition and business rationale.")

    # KPI-specific fields
    formula: str | None = Field(default=None, description="Declarative computation formula string (no executable code).")
    synonyms: list[str] = Field(default_factory=list, description="Internal colloquialisms and abbreviations (e.g. GP, GM).")
    canonical_intent: str | None = Field(default=None, description="Phase 13 canonical intent mapping if applicable.")
    analytics_tool: str | None = Field(default=None, description="Phase 3 deterministic analytics tool name.")
    metric_field: str | None = Field(default=None, description="Result field from analytics tool.")
    unit: str | None = Field(default=None, description="Unit of measurement (currency, percentage, count, ratio, days).")
    target_direction: str | None = Field(default=None, description="Target direction: increase, decrease, or neutral.")

    # Rule / Policy specific fields
    condition: str | None = Field(default=None, description="Declarative condition for policy/rule.")
    action: str | None = Field(default=None, description="Prescribed action or consequence.")
    scope: str | None = Field(default=None, description="Business scope of applicability.")
    priority: int = Field(default=100, description="Rule evaluation priority (lower executes earlier).")

    # Calendar / Seasonality specific fields
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12, description="Fiscal year starting month (1-12).")
    quarter_definitions: dict[str, str] | None = Field(default=None, description="Custom quarter mapping.")
    peak_seasons: list[dict[str, Any]] | None = Field(default=None, description="Known promotional or seasonal peak windows.")
    blackout_dates: list[str] | None = Field(default=None, description="Blackout dates or freeze periods.")

    # Company Profile specific fields
    legal_name: str | None = Field(default=None, description="Company legal name.")
    operating_currency: str | None = Field(default="USD", description="Base operational currency.")
    industry: str | None = Field(default=None, description="Industry sector.")
    reporting_timezone: str | None = Field(default="UTC", description="Reporting timezone.")

    # Additional unstructured metadata
    metadata: dict[str, Any] = Field(default_factory=dict, description="Custom domain-specific metadata.")

    @field_validator("id")
    @classmethod
    def validate_id_slug(cls, v: str) -> str:
        clean = v.strip().lower()
        if not clean:
            raise ValueError("ID cannot be empty.")
        import re
        if not re.match(r"^[a-z0-9][a-z0-9_-]{1,63}$", clean):
            raise ValueError(
                f"Invalid ID '{clean}'. Must be 2-64 characters alphanumeric, hyphen, or underscore, starting with alphanumeric."
            )
        return clean

    @field_validator("formula")
    @classmethod
    def validate_safe_formula(cls, v: str | None) -> str | None:
        if v is None:
            return None
        # Disallow executable / dangerous keywords
        v_clean = v.strip()
        dangerous = [
            "__", "import", "exec", "eval", "os.", "sys.", "subprocess",
            "shutil", "compile", "open(", "globals", "locals", "builtins",
            "<script", "javascript:", ";", "drop table", "select *", "delete from"
        ]
        lower_v = v_clean.lower()
        for d in dangerous:
            if d in lower_v:
                raise ValueError(f"Prohibited pattern '{d}' detected in formula: '{v_clean}'")
        return v_clean


class OKFBundle(BaseModel):
    """
    A cohesive, portable package of business context definitions.
    Can be serialized as a multi-document Markdown file or archive.
    """
    id: str = Field(..., description="Machine-readable bundle identifier.")
    name: str = Field(..., description="Human-readable title of the business context bundle.")
    version: int = Field(default=1, ge=1, description="Bundle version integer.")
    description: str = Field(default="", description="Bundle scope and overview.")
    status: OKFStatus = Field(default=OKFStatus.VERIFIED, description="Verification status.")
    author: str = Field(..., description="Organization or department authoring this bundle.")
    created_at: datetime | None = Field(default=None, description="Creation timestamp.")
    items: list[OKFItem] = Field(default_factory=list, description="List of knowledge items.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Bundle-level metadata.")

    @field_validator("id")
    @classmethod
    def validate_bundle_id(cls, v: str) -> str:
        clean = v.strip().lower()
        if not clean:
            raise ValueError("Bundle ID cannot be empty.")
        import re
        if not re.match(r"^[a-z0-9][a-z0-9_-]{1,63}$", clean):
            raise ValueError(f"Invalid bundle ID '{clean}'. Must be a valid slug.")
        return clean


class OKFValidationError(BaseModel):
    """Specific error found during OKF validation."""
    item_id: str | None = None
    field: str | None = None
    error_type: str
    message: str


class OKFValidationReport(BaseModel):
    """Deterministic validation summary for an OKF bundle or item."""
    is_valid: bool
    bundle_id: str | None = None
    item_count: int = 0
    errors: list[OKFValidationError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
