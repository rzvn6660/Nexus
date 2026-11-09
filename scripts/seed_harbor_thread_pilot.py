"""Seed and Provision Harbor & Thread Synthetic Merchant Pilot on PostgreSQL.

Provides deterministic seeding of:
- Harbor & Thread merchant tenant (Dubai, UAE, AED, 5% VAT)
- Daniel Morgan manager account
- 1,200 synthetic customers across 10 Dubai neighborhoods
- 180 luxury catalog products with explicitly labeled synthetic COGS
- 7,808 sales transactions and 16,264 line items passing exact VAT invariants
- Simulated consent governance record
- Provisional watermark
- Human-in-the-Loop decision audit events (1 Approved, 1 Rejected)
- October 2026 Executive Pulse Report in AED with ReportLab PDF
"""

import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

# Database URL pointing to live staging postgres container on localhost:5433 or DATABASE_URL
STAGING_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://nexus_staging_user:local_dev_password@localhost:5433/nexus_staging_db",
)
engine = create_engine(STAGING_DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

from app.analytics.analyst.models import ExecutionContext
from app.analytics.analyst.skills.commercial import GrossMarginAnalysisSkill, RevenuePerformanceSkill
from app.analytics.analyst.skills.customer import RepeatPurchaseSkill, RFMSegmentationSkill
from app.analytics.analyst.skills.diagnostic import RevenueVarianceSkill
from app.analytics.analyst.skills.discovery import DataProfilingSkill
from app.analytics.analyst.skills.predictive import ChurnPredictionSkill, SeasonalityAnalysisSkill, TimeSeriesForecastingSkill
from app.analytics.analyst.skills.quality import ReconciliationAuditSkill, SchemaValidationSkill
from app.analytics.analyst.skills.reporting import ExecutiveSummarySkill
from app.analytics.analyst.skills.retention import RetentionOpportunitySkill
from app.analytics.customer.retention import CustomerRetentionService
from app.analytics.onboarding.harbor_thread_generator import (
    HARBOR_THREAD_AUTH_REF,
    HARBOR_THREAD_CONSENT_REF,
    HARBOR_THREAD_CURRENCY,
    HARBOR_THREAD_MANAGER_EMAIL,
    HARBOR_THREAD_MANAGER_NAME,
    HARBOR_THREAD_MANAGER_PASSWORD,
    HARBOR_THREAD_TENANT_NAME,
    get_synthetic_catalog_definitions,
    get_synthetic_customer_definitions,
    generate_synthetic_transactions,
    provision_harbor_thread_tenant,
)
from app.analytics.pulse.pdf_generator import PulsePDFGenerator
from app.analytics.pulse.service import PulseService
from app.models.customer import Customer
from app.models.history import DecisionAuditEvent, DecisionRecord
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, UploadedDataset
from app.models.watermark import TenantIngestionWatermark
from app.schemas.pulse import ReportType
from app.services.auth_service import AuthService
from app.services.tenant_certification_policy import TenantCertificationPolicy

def main():
    print("=" * 80)
    print("NEXUS — HARBOR & THREAD LIVE STAGING SEEDING & PILOT SIMULATION")
    print("=" * 80)

    with SessionLocal() as db:
        # Step 1: Provision Tenant
        print("\n[Step 1] Provisioning Harbor & Thread Synthetic Pilot Tenant...")
        user, org, biz = provision_harbor_thread_tenant(db)
        print(f"  Business:     {biz.name} (ID: {biz.id})")
        print(f"  Organization: {org.name} (ID: {org.id})")
        print(f"  Manager:      {user.full_name} <{user.email}>")
        print(f"  Currency:     {biz.currency}")

        # Verify Isolation Safeguards
        is_sandbox = TenantCertificationPolicy.is_sandbox_merchant(biz.id, session=db)
        is_real = TenantCertificationPolicy.is_real_operational_merchant(biz.id, session=db)
        print(f"  Policy: is_sandbox_merchant={is_sandbox}, is_real_operational_merchant={is_real}")
        assert is_sandbox is True
        assert is_real is False

        # Step 2: Persist Simulated Consent
        print("\n[Step 2] Persisting SIMULATED_CONSENT Audit Event...")
        existing_consent = db.execute(
            select(DecisionRecord).where(
                DecisionRecord.business_id == biz.id,
                DecisionRecord.recommendation_type == "MERCHANT_ONBOARDING_CONSENT",
            )
        ).scalar_one_or_none()

        if not existing_consent:
            consent_record = DecisionRecord(
                business_id=biz.id,
                organization_id=biz.organization_id,
                recommendation_text="Merchant Data-Processing Consent for Synthetic Demonstration",
                recommendation_type="MERCHANT_ONBOARDING_CONSENT",
                status="APPROVED",
                reviewed_by=user.email,
                reviewed_at=datetime.now(UTC),
                reviewer_notes="Simulated consent authorized by Daniel Morgan for synthetic pilot demonstration.",
            )
            db.add(consent_record)
            db.flush()

            consent_audit = DecisionAuditEvent(
                decision_id=consent_record.id,
                business_id=biz.id,
                organization_id=biz.organization_id,
                revision=0,
                event_type="SIMULATED_CONSENT",
                idempotency_key=str(uuid4()),
                actor_id=user.id,
                actor_role="manager",
                prev_event_hash="0" * 64,
                event_hash="f" * 64,
                canonical_payload={
                    "consent_ref": HARBOR_THREAD_CONSENT_REF,
                    "disclaimer": "SYNTHETIC DEMONSTRATION ONLY — NOT A REAL LEGAL AGREEMENT",
                    "authorized_currency": "AED",
                    "pilot_scope": "Full retail analytics, customer cadence, and executive reporting",
                },
            )
            db.add(consent_audit)
            db.commit()
            print(f"  Persisted SIMULATED_CONSENT event (Decision ID: {consent_record.id})")
        else:
            print(f"  Consent event already exists (Decision ID: {existing_consent.id})")

        # Step 3: Canonical Ingestion
        print("\n[Step 3] Checking Canonical Domain Records...")
        existing_custs = db.execute(select(func.count(Customer.id)).where(Customer.business_id == biz.id)).scalar()
        existing_prods = db.execute(select(func.count(Product.id)).where(Product.business_id == biz.id)).scalar()
        existing_sales = db.execute(select(func.count(Sale.id)).where(Sale.business_id == biz.id)).scalar()
        existing_items = db.execute(
            select(func.count(SaleItem.id)).join(Sale, SaleItem.sale_id == Sale.id).where(Sale.business_id == biz.id)
        ).scalar()

        print(f"  Existing records in DB: Customers={existing_custs}, Products={existing_prods}, Sales={existing_sales}, Items={existing_items}")

        if existing_custs < 1200 or existing_prods < 180 or existing_sales < 7000:
            print("  Ingesting full canonical synthetic dataset...")
            # 1. Customers
            cust_defs = get_synthetic_customer_definitions()
            c_objs = [
                Customer(
                    business_id=biz.id,
                    customer_code=c["customer_code"],
                    name=c["name"],
                    email=c["email"],
                    phone="+971500000000",
                    city=c["city"],
                    customer_segment=c["customer_segment"],
                    acquisition_date=c["acquisition_date"],
                )
                for c in cust_defs
            ]
            db.add_all(c_objs)
            db.flush()
            print(f"  Persisted {len(c_objs)} Customers")

            # Resolve customer_code -> id
            c_map = {c.customer_code: c.id for c in db.execute(select(Customer).where(Customer.business_id == biz.id)).scalars().all()}

            # 2. Products
            prod_defs = get_synthetic_catalog_definitions()
            p_objs = [
                Product(
                    business_id=biz.id,
                    sku=p["sku"],
                    name=p["name"],
                    category=p["category"],
                    subcategory=p["subcategory"],
                    selling_price=p["selling_price"],
                    unit_cost=p["unit_cost"],
                    active=p["is_active"],
                )
                for p in prod_defs
            ]
            db.add_all(p_objs)
            db.flush()
            print(f"  Persisted {len(p_objs)} Products")

            # Resolve sku -> id
            p_map = {p.sku: p.id for p in db.execute(select(Product).where(Product.business_id == biz.id)).scalars().all()}

            # 3. Sales & SaleItems
            raw_sales = generate_synthetic_transactions()
            s_objs = []
            item_objs = []
            for s in raw_sales:
                c_id = c_map[s["customer_code"]]
                sale = Sale(
                    business_id=biz.id,
                    customer_id=c_id,
                    transaction_number=s["order_number"],
                    transaction_date=s["date"],
                    subtotal=s["subtotal"],
                    discount_amount=s["discount_amount"],
                    tax_amount=s["tax_amount"],
                    total_amount=s["total_amount"],
                    status=s["status"],
                )
                s_objs.append(sale)

            db.add_all(s_objs)
            db.flush()
            print(f"  Persisted {len(s_objs)} Sales")

            # Resolve order_number -> sale.id
            s_map = {s.transaction_number: s.id for s in db.execute(select(Sale).where(Sale.business_id == biz.id)).scalars().all()}

            for s in raw_sales:
                sale_id = s_map[s["order_number"]]
                for it in s["items"]:
                    prod_id = p_map[it["sku"]]
                    item = SaleItem(
                        sale_id=sale_id,
                        product_id=prod_id,
                        quantity=it["quantity"],
                        unit_price=it["unit_price"],
                        discount_amount=it["discount_amount"],
                        line_total=it["line_total"],
                    )
                    item_objs.append(item)

            db.add_all(item_objs)
            db.flush()
            print(f"  Persisted {len(item_objs)} SaleItems")

            # Watermark
            wm = TenantIngestionWatermark(
                business_id=biz.id,
                source_id="harbor_thread_synthetic_dataset",
                verification_status="provisional",
                complete_through_dt=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
                metadata_json={
                    "provenance": "DEMO_SYNTHETIC",
                    "generator_controlled": True,
                    "db_reconciled": True,
                    "notice": "SYNTHETIC DEMONSTRATION WORKSPACE — NOT FOR OFFICIAL FINANCIAL AUDIT",
                },
            )
            db.add(wm)
            db.commit()
            print("  Committed full dataset and provisional watermark successfully!")
        else:
            print("  Dataset already present in staging database.")

        # Step 4: Mathematical Reconciliation & Order Invariants
        print("\n[Step 4] Running Mathematical Reconciliation & Order Invariants...")
        sales_all = db.execute(select(Sale).where(Sale.business_id == biz.id)).scalars().all()
        print(f"  Total sales in DB: {len(sales_all)}")
        total_rev_db = sum(s.total_amount for s in sales_all)
        print(f"  Total revenue (AED): {total_rev_db:,.2f}")

        invariant_failures = 0
        for s in sales_all:
            taxable = max(Decimal("0.00"), s.subtotal - s.discount_amount)
            expected_tax = round(taxable * Decimal("0.05"), 2)
            if abs(s.tax_amount - expected_tax) > Decimal("0.01"):
                invariant_failures += 1
            expected_tot = taxable + s.tax_amount
            if abs(s.total_amount - expected_tot) > Decimal("0.01"):
                invariant_failures += 1
        print(f"  Invariant failures: {invariant_failures} (Expected: 0)")
        assert invariant_failures == 0

        # Step 5: Customer Retention & HITL Decisions
        print("\n[Step 5] Evaluating Retention Overview & Simulating HITL Owner Decisions...")
        overview = CustomerRetentionService.get_retention_overview(db, biz.id)
        print(f"  Customers evaluated:   {overview.total_customers_evaluated}")
        print(f"  One-time buyers:       {overview.one_time_buyers_count} (unscored)")
        print(f"  Repeat buyers:         {overview.repeat_buyers_count} (calibrated cadence)")
        print(f"  Risk distribution:     {overview.risk_distribution}")
        print(f"  Est. Revenue at Risk:  AED {overview.total_revenue_at_risk_usd:,.2f}")

        # Record 1 Approved and 1 Rejected Decision if not already recorded
        dec_approved = db.execute(
            select(DecisionRecord).where(
                DecisionRecord.business_id == biz.id,
                DecisionRecord.status == "APPROVED",
                DecisionRecord.recommendation_type == "CUSTOMER_RETENTION",
            )
        ).scalar_one_or_none()

        if not dec_approved:
            dec_app = DecisionRecord(
                business_id=biz.id,
                organization_id=biz.organization_id,
                recommendation_text="Private VIP Styling Consultation & 15% New Collection Privilege",
                recommendation_type="CUSTOMER_RETENTION",
                status="APPROVED",
                reviewed_by=user.email,
                reviewed_at=datetime.now(UTC),
                reviewer_notes="Approved by Daniel Morgan: targeted high-value re-engagement for top VIP buyer.",
            )
            db.add(dec_app)
            db.flush()

            audit_app = DecisionAuditEvent(
                decision_id=dec_app.id,
                business_id=biz.id,
                organization_id=biz.organization_id,
                revision=0,
                event_type="APPROVAL_GRANTED",
                idempotency_key=str(uuid4()),
                actor_id=user.id,
                actor_role="manager",
                prev_event_hash="0" * 64,
                event_hash="1" * 64,
                canonical_payload={"action": "APPROVED", "notes": dec_app.reviewer_notes},
            )
            db.add(audit_app)

            dec_rej = DecisionRecord(
                business_id=biz.id,
                organization_id=biz.organization_id,
                recommendation_text="40% Sitewide Clearance Flash Promo",
                recommendation_type="CUSTOMER_RETENTION",
                status="REJECTED",
                reviewed_by=user.email,
                reviewed_at=datetime.now(UTC),
                reviewer_notes="Rejected by Daniel Morgan: steep discounting dilutes brand luxury positioning.",
            )
            db.add(dec_rej)
            db.flush()

            audit_rej = DecisionAuditEvent(
                decision_id=dec_rej.id,
                business_id=biz.id,
                organization_id=biz.organization_id,
                revision=0,
                event_type="REJECTION_RECORDED",
                idempotency_key=str(uuid4()),
                actor_id=user.id,
                actor_role="manager",
                prev_event_hash="1" * 64,
                event_hash="2" * 64,
                canonical_payload={"action": "REJECTED", "notes": dec_rej.reviewer_notes},
            )
            db.add(audit_rej)
            db.commit()
            print("  Recorded 1 Approved and 1 Rejected HITL decision in audit ledger.")
        else:
            print("  HITL retention decisions already present in ledger.")

        # Step 6: Pulse Executive Report Generation & PDF
        print("\n[Step 6] Generating October 2026 Executive Pulse Report in AED...")
        report = PulseService.generate_report(
            session=db,
            business_id=biz.id,
            report_type=ReportType.MONTHLY_EXECUTIVE,
            period_start=datetime(2026, 10, 1, 0, 0, tzinfo=UTC),
            period_end=datetime(2026, 10, 31, 23, 59, tzinfo=UTC),
            report_title="Harbor & Thread — October 2026 Executive Performance (AED)",
            force_regenerate=True,
        )
        print(f"  Report generated: ID={report.id}")
        print(f"  Title:            {report.report_title}")
        print(f"  PDF Size:         {len(report.pdf_file_bytes):,} bytes")
        print(f"  PDF SHA-256:      {report.pdf_sha256}")

        kpis = report.kpi_payload
        tot_rev = kpis["financial"]["total_revenue"]
        aov = kpis["financial"]["average_order_value"]
        margin = kpis["financial"]["gross_margin"]
        print(f"  Total Revenue:    {tot_rev['formatted_value']}")
        print(f"  AOV:              {aov['formatted_value']}")
        print(f"  Gross Margin:     {margin['formatted_value']}")

        # Step 7: Analyst Studio Multi-Domain Execution
        print("\n[Step 7] Executing Analyst Studio Skills Across All 8 Domains...")
        context = ExecutionContext(business_id=biz.id, user_id=user.id, user_role="manager")

        skills_to_run = [
            ("Discovery", DataProfilingSkill()),
            ("Quality", SchemaValidationSkill()),
            ("Customer", RepeatPurchaseSkill()),
            ("Predictive", SeasonalityAnalysisSkill()),
            ("Diagnostic", RevenueVarianceSkill()),
            ("Retention", RetentionOpportunitySkill()),
            ("Commercial", GrossMarginAnalysisSkill()),
            ("Reporting", ExecutiveSummarySkill()),
        ]

        for domain_name, skill in skills_to_run:
            res = skill.execute(db, context)
            print(f"  [{domain_name:12s}] {skill.name:36s} -> {res.status} (confidence: {res.confidence_score:.2f})")

    print("\n" + "=" * 80)
    print("HARBOR & THREAD LIVE PILOT SEEDING COMPLETED SUCCESSFULLY!")
    print("=" * 80)

if __name__ == "__main__":
    main()
