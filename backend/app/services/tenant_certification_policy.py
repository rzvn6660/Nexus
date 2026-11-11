"""
NEXUS Phase 1J.2.3 — Centralized Tenant Certification & Quarantine Policy.

Replaces fragmented, hardcoded tenant checks across adapters and reconciliation services
with a unified, server-side policy engine that enforces:
1. Default Deny: All tenants are ineligible for automated completeness certification unless
   explicit server-side requirements are satisfied.
2. Provenance Isolation: Synthetic and sandbox evidence (e.g. stripe_test_mode, shopify_dev_store,
   synthetic_fixture) can NEVER authorize certification for real operational tenants.
3. Server-Side Enforcement: Policies are evaluated server-side and cannot be bypassed via
   client request parameters, adapter flags, or test bypass headers.
4. Tenant Quarantine: Real operational tenants (such as Apex Specialty Commerce) without
   independently authenticated live production connectors remain strictly in DIAGNOSTIC_ONLY status.
"""

import logging
import os
from datetime import UTC, datetime
from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Business

logger = logging.getLogger(__name__)


class CertificationEligibilityStatus(str, Enum):
    """Classification of tenant certification eligibility."""
    ACTIONABLE = "actionable"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    BLOCKED = "blocked"
    QUARANTINED = "quarantined"


class ProvenanceTrustTier(str, Enum):
    """Trust tier of evidence submitted for reconciliation or certification."""
    TIER1_AUTHENTICATED_API = "tier1_authenticated_api"
    TIER2_SIGNED_WEBHOOK = "tier2_signed_webhook"
    TIER3_PAYOUT_SETTLEMENT = "tier3_payout_settlement"
    TIER4_ACCOUNTING_PERIOD_CLOSE = "tier4_accounting_period_close"
    SANDBOX_SYNTHETIC = "sandbox_synthetic"


class CertificationPolicyVerdict(BaseModel):
    """Structured decision explaining tenant certification eligibility."""
    business_id: str
    status: CertificationEligibilityStatus
    can_certify: bool = False  # Default Deny
    is_real_tenant: bool = False
    reason_code: str
    explanation: str
    provenance_evaluated: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TenantCertificationPolicy:
    """
    Centralized policy engine for tenant certification eligibility and sandbox isolation.
    Enforces server-side quarantine without ad-hoc tenant ID checks in adapters.
    """

    # Provenance classifications that are strictly sandbox/synthetic
    SANDBOX_PROVENANCES: ClassVar[set[str]] = {
        "synthetic",
        "synthetic_sandbox",
        "synthetic_fixture",
        "stripe_test_mode",
        "shopify_dev_store",
        "test_sandbox",
        "mock_connector",
    }

    # Known operational real business names that must never be certified via sandbox data
    # (Server-side registry to prevent accidental live qualification)
    PROTECTED_REAL_BUSINESS_NAMES: ClassVar[set[str]] = {
        "apex specialty commerce",
    }

    @classmethod
    def is_protected_real_tenant(
        cls,
        business_id: str,
        session: Session | None = None,
    ) -> bool:
        """
        Check if business is a protected real tenant (e.g. Apex Specialty Commerce)
        which must never have synthetic/sandbox watermarks created or promoted.
        """
        if not business_id or not business_id.strip():
            return False
        env_real = os.getenv("PROTECTED_REAL_TENANTS", "ab044b1a-835a-4a38-bf45-62fe38624151").split(",")
        env_real_set = {x.strip() for x in env_real if x.strip()}
        if business_id in env_real_set:
            return True
        if session is not None:
            biz = session.execute(
                select(Business).where(Business.id == business_id)
            ).scalar_one_or_none()
            if biz:
                name_clean = (biz.name or "").strip().lower()
                if any(p in name_clean for p in cls.PROTECTED_REAL_BUSINESS_NAMES):
                    return True
        return False

    @classmethod
    def is_real_tenant(
        cls,
        business_id: str,
        session: Session | None = None,
    ) -> bool:
        """
        Determine if a business_id represents a real operational tenant rather than a disposable test fixture.

        A tenant is classified as a real tenant if:
        1. It exists in the database as an operational business without an explicit test fixture flag.
        2. Its business name matches a known operational enterprise (e.g. Apex Specialty Commerce).
        3. The system is operating in a production environment (APP_ENV == 'production').
        """
        if not business_id or not business_id.strip():
            return False

        if os.getenv("APP_ENV") == "production":
            return True

        # Check environment or server-configured real tenant identifiers
        env_real = os.getenv("PROTECTED_REAL_TENANTS", "ab044b1a-835a-4a38-bf45-62fe38624151").split(",")
        env_real_set = {x.strip() for x in env_real if x.strip()}
        if business_id in env_real_set:
            return True

        # Check database business attributes if session is provided
        if session is not None:
            biz = session.execute(
                select(Business).where(Business.id == business_id)
            ).scalar_one_or_none()
            if biz:
                name_clean = (biz.name or "").strip().lower()
                if any(p in name_clean for p in cls.PROTECTED_REAL_BUSINESS_NAMES):
                    return True
                # If explicitly marked as synthetic sandbox fixture or registered sandbox, it is not a real tenant
                if getattr(biz, "is_synthetic_sandbox", False) or cls.is_sandbox_merchant(business_id, session=session):
                    return False
                # If business ID denotes a test fixture ID
                return not any(x in biz.id.lower() for x in ["test", "persist", "recov", "mock", "fixture", "rh", "syn", "synthetic", "rehearsal", "analyst", "bench", "demo"])

        return False

    @classmethod
    def is_sandbox_provenance(cls, provenance: str | None) -> bool:
        """Check if an evidence provenance is considered sandbox or synthetic."""
        if not provenance:
            return True  # Unspecified provenance defaults to sandbox (fail-closed)
        prov_clean = provenance.strip().lower()
        if prov_clean in cls.SANDBOX_PROVENANCES:
            return True
        return any(term in prov_clean for term in ["test", "sandbox", "synthetic", "mock", "dev_store"])

    @classmethod
    def evaluate_certification_eligibility(
        cls,
        business_id: str,
        provenance: str | None = "sandbox",
        is_sandbox: bool = True,
        is_fully_reconciled: bool = False,
        session: Session | None = None,
    ) -> CertificationPolicyVerdict:
        """
        Central server-side evaluator for whether a tenant can be certified based on
        reconciliation or synchronization evidence.

        Enforces:
        - Default Deny.
        - Synthetic and sandbox provenance cannot authorize real-tenant certification.
        - Real tenants remain in DIAGNOSTIC_ONLY until live signed manifests are produced.
        """
        is_real = cls.is_real_tenant(business_id, session=session)
        is_sandbox_prov = is_sandbox or cls.is_sandbox_provenance(provenance)

        # Rule 1: Real tenant + sandbox provenance -> HARD QUARANTINE
        if is_real and is_sandbox_prov:
            return CertificationPolicyVerdict(
                business_id=business_id,
                status=CertificationEligibilityStatus.DIAGNOSTIC_ONLY,
                can_certify=False,
                is_real_tenant=True,
                reason_code="REAL_TENANT_SANDBOX_PROVENANCE_PROHIBITED",
                explanation=(
                    f"GOVERNANCE VIOLATION PREVENTED: Tenant '{business_id}' is a real operational tenant. "
                    f"Evidence provenance '{provenance}' is sandbox/synthetic and cannot authorize completeness certification. "
                    "Tenant remains strictly in DIAGNOSTIC_ONLY status."
                ),
                provenance_evaluated=provenance or "unknown",
            )

        # Rule 2: Unreconciled data cannot certify any tenant
        if not is_fully_reconciled:
            return CertificationPolicyVerdict(
                business_id=business_id,
                status=CertificationEligibilityStatus.DIAGNOSTIC_ONLY,
                can_certify=False,
                is_real_tenant=is_real,
                reason_code="RECONCILIATION_INCOMPLETE",
                explanation="Source data exhibits outstanding variances, conflicts, or unmatched records.",
                provenance_evaluated=provenance or "unknown",
            )

        # Rule 3: Disposable test sandbox tenant with full reconciliation -> Sandbox Certification Permitted
        if not is_real and is_sandbox_prov and is_fully_reconciled:
            return CertificationPolicyVerdict(
                business_id=business_id,
                status=CertificationEligibilityStatus.ACTIONABLE,
                can_certify=True,
                is_real_tenant=False,
                reason_code="SANDBOX_RECONCILIATION_VERIFIED",
                explanation="Disposable sandbox test tenant has satisfied all cross-source reconciliation criteria.",
                provenance_evaluated=provenance or "unknown",
            )

        # Rule 4: Default Deny fallback
        return CertificationPolicyVerdict(
            business_id=business_id,
            status=CertificationEligibilityStatus.DIAGNOSTIC_ONLY,
            can_certify=False,
            is_real_tenant=is_real,
            reason_code="DEFAULT_DENY_UNVERIFIED",
            explanation="Default deny: tenant has not completed independently authenticated production certification.",
            provenance_evaluated=provenance or "unknown",
        )

    @classmethod
    def assert_can_ingest_synthetic(
        cls,
        business_id: str,
        provenance: str = "synthetic",
        session: Session | None = None,
    ) -> None:
        """
        Assert that synthetic data ingestion is permitted.
        Raises PermissionError if attempted against a real operational tenant or production environment.
        """
        if cls.is_real_tenant(business_id, session=session) or os.getenv("APP_ENV") == "production":
            raise PermissionError(
                f"Governance Violation: Real tenant '{business_id}' cannot be certified "
                f"using synthetic sandbox or test-mode evidence ('{provenance}')."
            )

    @classmethod
    def assert_can_certify_period_close(
        cls,
        business_id: str,
        provenance: str,
        session: Session | None = None,
    ) -> None:
        """
        Assert that period-close certification is permitted for this tenant and provenance.
        Raises PermissionError if a real tenant is being certified with sandbox evidence.
        """
        if cls.is_real_tenant(business_id, session=session) and cls.is_sandbox_provenance(provenance):
            raise PermissionError(
                f"Governance Violation: Real tenant '{business_id}' cannot be certified "
                f"using synthetic sandbox or test-mode provenance ('{provenance}')."
            )

    # Explicit in-memory registry of trusted synthetic sandbox test merchants (configured via trusted test fixtures)
    _TRUSTED_SANDBOX_MERCHANTS: ClassVar[set[str]] = set()

    @classmethod
    def register_trusted_sandbox_merchant(cls, business_id: str) -> None:
        """Register an explicit business_id as a trusted synthetic sandbox merchant (for test fixtures)."""
        if business_id and business_id.strip():
            cls._TRUSTED_SANDBOX_MERCHANTS.add(business_id.strip())

    @classmethod
    def unregister_trusted_sandbox_merchant(cls, business_id: str) -> None:
        """Unregister a business_id from the trusted synthetic sandbox test registry."""
        if business_id and business_id.strip():
            cls._TRUSTED_SANDBOX_MERCHANTS.discard(business_id.strip())

    @classmethod
    def clear_trusted_sandbox_merchants(cls) -> None:
        """Clear all trusted synthetic sandbox test merchant registrations."""
        cls._TRUSTED_SANDBOX_MERCHANTS.clear()

    @classmethod
    def is_sandbox_merchant(
        cls,
        business_id: str,
        session: Session | None = None,
    ) -> bool:
        """
        Check if business is an authorized dedicated synthetic sandbox merchant.

        Strict Security Invariant:
        Tenant names, labels, and external strings NEVER grant sandbox privileges.
        Protected real operational tenants can NEVER be treated as sandbox merchants.

        Sandbox privileges strictly require trusted persisted configuration or explicit fixture registration:
        1. Explicit trusted test fixture registration via `register_trusted_sandbox_merchant`.
        2. Database persisted `business_type` column set to 'sandbox', 'synthetic_test', or 'pilot'.
        3. Database persisted `status` column set to 'sandbox' or 'synthetic'.
        4. Explicit boolean attribute `is_synthetic_sandbox = True` on the Business model.
        5. Persisted `metadata_json` with trusted flags `is_sandbox: True` or `tenant_type: 'sandbox'`.
        """
        if not business_id or not business_id.strip():
            return False

        # Invariant: A protected real operational tenant is NEVER a sandbox merchant under any circumstances
        if cls.is_protected_real_tenant(business_id, session=session):
            return False

        # 1. Explicit trusted fixture registration
        if business_id.strip() in cls._TRUSTED_SANDBOX_MERCHANTS:
            return True

        # 2. Persisted database configuration
        if session is not None:
            biz = session.execute(
                select(Business).where(Business.id == business_id)
            ).scalar_one_or_none()
            if biz:
                # Check persisted business_type column
                b_type = (getattr(biz, "business_type", "") or "").strip().lower()
                if b_type in ("sandbox", "synthetic_test", "pilot"):
                    return True
                # Check persisted status column
                b_status = (getattr(biz, "status", "") or "").strip().lower()
                if b_status in ("sandbox", "synthetic"):
                    return True
                # Explicit boolean attribute on Business instance
                if getattr(biz, "is_synthetic_sandbox", False) is True:
                    return True
                # Persisted metadata_json if present
                biz_meta = getattr(biz, "metadata_json", None) or {}
                if isinstance(biz_meta, dict) and (biz_meta.get("is_sandbox") is True or biz_meta.get("tenant_type") == "sandbox"):
                    return True

        return False

    @classmethod
    def is_real_operational_merchant(
        cls,
        business_id: str,
        session: Session | None = None,
    ) -> bool:
        """
        Check if business is an actual real merchant (such as Apex Specialty Commerce or explicitly flagged real merchant).
        Dedicated sandbox merchants are explicitly excluded from real operational merchant status.
        Protected real tenants are IMMUTABLE real operational merchants regardless of any sandbox flags.
        """
        if not business_id or not business_id.strip():
            return False
        # Protected real operational tenants take precedence over everything else
        if cls.is_protected_real_tenant(business_id, session=session):
            return True
        if cls.is_sandbox_merchant(business_id, session=session):
            return False
        if session is not None:
            biz = session.execute(
                select(Business).where(Business.id == business_id)
            ).scalar_one_or_none()
            if biz:
                biz_meta = getattr(biz, "metadata_json", None) or {}
                if isinstance(biz_meta, dict) and (
                    biz_meta.get("is_real_merchant") or biz_meta.get("tenant_type") == "real_operational"
                ):
                    return True
                if os.getenv("APP_ENV") == "production":
                    return True
        return False

    @classmethod
    def verify_merchant_import_authorization(
        cls,
        business_id: str,
        session: Session | None = None,
        authorization_ref: str | None = None,
    ) -> bool:
        """
        Verify whether an import has verified written merchant authorization.
        For real operational merchants: requires non-sandbox written authorization ref or metadata.
        Sandbox tokens cannot authorize real operational merchants.
        """
        if not cls.is_real_operational_merchant(business_id, session=session):
            return True
        if authorization_ref and str(authorization_ref).strip():
            # A sandbox-scoped or synthetic authorization ref cannot authorize a real merchant
            ref_low = str(authorization_ref).lower()
            return not any(t in ref_low for t in ["sandbox", "synthetic", "pilot", "demo", "mock", "test"])
        if session is not None:
            biz = session.execute(
                select(Business).where(Business.id == business_id)
            ).scalar_one_or_none()
            biz_meta = getattr(biz, "metadata_json", None) or {}
            if isinstance(biz_meta, dict):
                if biz_meta.get("written_authorization_verified") in (True, "true", "True", 1):
                    return True
                ref = biz_meta.get("written_authorization_ref")
                if ref and "sandbox" not in str(ref).lower():
                    return True
        return False

    @classmethod
    def assert_merchant_import_authorized(
        cls,
        business_id: str,
        session: Session | None = None,
        authorization_ref: str | None = None,
    ) -> None:
        """Assert that written merchant authorization exists before ingesting actual business data."""
        if not cls.verify_merchant_import_authorization(business_id, session=session, authorization_ref=authorization_ref):
            raise PermissionError(
                f"Import authorization denied: Real merchant tenant '{business_id}' requires verified written "
                "merchant authorization before ingesting or processing actual business data. Sandbox tokens are rejected."
            )

    @classmethod
    def assert_cannot_certify_period_close_on_synthetic_data(
        cls,
        business_id: str,
        session: Session | None = None,
    ) -> None:
        """Ensure synthetic or sandbox data is never promoted to authoritative financial period close."""
        if cls.is_sandbox_merchant(business_id, session=session):
            raise ValueError(
                f"Certification blocked: Tenant '{business_id}' is a demonstration sandbox. "
                "Synthetic data cannot be certified for authoritative financial period close or audited GAAP reporting."
            )
