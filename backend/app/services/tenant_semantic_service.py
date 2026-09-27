"""Tenant Semantic and Business Understanding Service (Phase 17).

Provides:
- Deterministic Business Understanding from database-grounded state
- Metric availability classification (AVAILABLE, REQUIRES_COST_DATA, INSUFFICIENT_HISTORY, UNAVAILABLE)
- Persistent, versioned TenantSemanticModel lifecycle (NOT_ACTIVATED -> ACTIVATING -> ACTIVE -> REQUIRES_REVIEW)
- Conflict detection between sequential semantic revisions
- Tenant-scoped synonym and ambiguous term resolution
- Semantic evidence provenance generation
"""

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.expense import Expense
from app.models.inventory import Inventory
from app.models.okf import OKFItemModel
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, TenantSemanticModel, UploadedDataset
from app.rag.semantic.ontology import kpi_ontology, semantic_resolver
from app.schemas.semantic import (
    BusinessDataSummary,
    BusinessUnderstandingResponse,
    DimensionUnderstanding,
    EntityUnderstanding,
    MetricAvailability,
    SemanticRevisionSummary,
    SemanticResolveResponse,
)

logger = logging.getLogger(__name__)


class TenantSemanticService:
    """Service orchestrating tenant-specific business understanding, semantic activation, and resolution."""

    CANONICAL_METRIC_SPECS = {
        "net_revenue": {
            "display_name": "Net Revenue",
            "description": "Total realized commercial sales value after discounts.",
            "source_table": "sales",
            "source_field": "total_amount",
            "calculation_formula": "SUM(sales.total_amount)",
            "unit": "currency",
            "business_domain": "finance",
            "analytics_tool": "get_financial_summary",
            "required_entities": ["Sale"],
        },
        "orders": {
            "display_name": "Orders",
            "description": "Total transaction count of finalized customer purchases.",
            "source_table": "sales",
            "source_field": "id",
            "calculation_formula": "COUNT(sales.id)",
            "unit": "count",
            "business_domain": "sales",
            "analytics_tool": "get_financial_summary",
            "required_entities": ["Sale"],
        },
        "average_order_value": {
            "display_name": "Average Order Value (AOV)",
            "description": "Mean commercial value generated per customer order.",
            "source_table": "sales",
            "source_field": "total_amount",
            "calculation_formula": "SUM(sales.total_amount) / NULLIF(COUNT(sales.id), 0)",
            "unit": "currency",
            "business_domain": "sales",
            "analytics_tool": "get_financial_summary",
            "required_entities": ["Sale"],
        },
        "units_sold": {
            "display_name": "Units Sold",
            "description": "Total physical items and units transacted across all lines.",
            "source_table": "sale_items",
            "source_field": "quantity",
            "calculation_formula": "SUM(sale_items.quantity)",
            "unit": "units",
            "business_domain": "sales",
            "analytics_tool": "get_financial_summary",
            "required_entities": ["SaleItem"],
        },
        "gross_margin": {
            "display_name": "Gross Margin",
            "description": "Commercial margin remaining after deducting product cost of goods sold.",
            "source_table": "products",
            "source_field": "unit_cost",
            "calculation_formula": "ROUND((revenue - cogs) / NULLIF(revenue, 0) * 100, 2)",
            "unit": "percentage",
            "business_domain": "finance",
            "analytics_tool": "get_financial_summary",
            "required_entities": ["Sale", "Product"],
            "cost_sensitive": True,
        },
        "inventory_value": {
            "display_name": "Inventory Value",
            "description": "Total commercial or replacement value of current stock on hand.",
            "source_table": "inventory",
            "source_field": "stock_quantity",
            "calculation_formula": "SUM(inventory.stock_quantity * products.unit_cost)",
            "unit": "currency",
            "business_domain": "inventory",
            "analytics_tool": "get_inventory_status",
            "required_entities": ["Inventory"],
        },
        "customer_count": {
            "display_name": "Customer Count",
            "description": "Total unique customer accounts and business profiles.",
            "source_table": "customers",
            "source_field": "id",
            "calculation_formula": "COUNT(customers.id)",
            "unit": "count",
            "business_domain": "customer",
            "analytics_tool": "get_customer_metrics",
            "required_entities": ["Customer"],
        },
        "operating_expenses": {
            "display_name": "Operating Expenses",
            "description": "Total operating overhead, facility, marketing, and payroll expenditures.",
            "source_table": "expenses",
            "source_field": "amount",
            "calculation_formula": "SUM(expenses.amount)",
            "unit": "currency",
            "business_domain": "expenses",
            "analytics_tool": "get_financial_summary",
            "required_entities": ["Expense"],
        },
        "customer_retention": {
            "display_name": "Customer Retention Rate",
            "description": "Percentage of unique customers with repeat transactions over time.",
            "source_table": "sales",
            "source_field": "customer_id",
            "calculation_formula": "COUNT(DISTINCT repeat_customers) / NULLIF(COUNT(DISTINCT all_customers), 0)",
            "unit": "percentage",
            "business_domain": "customer",
            "analytics_tool": "get_customer_metrics",
            "required_entities": ["Sale", "Customer"],
            "min_days_history": 90,
        },
    }

    DEFAULT_AMBIGUOUS_TERMS = {
        "sales": {
            "candidates": ["net_revenue", "orders", "units_sold"],
            "prompt": "The term 'sales' is ambiguous. Do you mean Net Revenue, number of Orders, or Units Sold?",
        },
        "turnover": {
            "candidates": ["net_revenue", "inventory_turnover"],
            "prompt": "The term 'turnover' can refer to sales revenue or inventory turnover velocity. Which would you like to analyze?",
        },
        "margin": {
            "candidates": ["gross_margin", "operating_margin"],
            "prompt": "The term 'margin' can mean Gross Margin (product profit) or Operating Margin (after overhead). Which would you like to inspect?",
        },
    }

    UNSUPPORTED_METRICS = {
        "clv": "Customer Lifetime Value (CLV) is not currently supported in the NEXUS deterministic metric catalog.",
        "customer lifetime value": "Customer Lifetime Value (CLV) is not currently supported in the NEXUS deterministic metric catalog.",
        "cac": "Customer Acquisition Cost (CAC) is not currently tracked by the NEXUS metric catalog.",
        "customer acquisition cost": "Customer Acquisition Cost (CAC) is not currently tracked by the NEXUS metric catalog.",
        "nps": "Net Promoter Score (NPS) is not currently integrated into the NEXUS telemetry catalog.",
        "net promoter score": "Net Promoter Score (NPS) is not currently integrated into the NEXUS telemetry catalog.",
        "churn": "Churn Rate is scheduled for a future release and not currently supported.",
        "churn rate": "Churn Rate is scheduled for a future release and not currently supported.",
    }

    @classmethod
    def compute_semantic_fingerprint(
        cls,
        entities: Optional[Dict[str, Any]],
        metrics: Optional[Dict[str, Any]],
        dimensions: Optional[Dict[str, Any]],
        synonyms: Optional[Dict[str, str]],
        ambiguous_terms: Optional[Dict[str, Any]],
        summary: Optional[Dict[str, Any]],
        source_dataset_id: Optional[str] = None,
    ) -> str:
        """
        Compute a deterministic SHA-256 fingerprint of the meaningful semantic state.
        Excludes volatile timestamps and primary key IDs.
        """
        state = {
            "entities": entities or {},
            "metrics": metrics or {},
            "dimensions": dimensions or {},
            "synonyms": synonyms or {},
            "ambiguous_terms": ambiguous_terms or {},
            "summary": summary or {},
            "source_dataset_id": source_dataset_id or "",
        }
        serialized = json.dumps(state, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def generate_business_understanding(
        cls,
        business_id: str,
        organization_id: str,
        db: Session,
        source_dataset_id: Optional[str] = None,
        custom_synonyms: Optional[Dict[str, str]] = None,
    ) -> TenantSemanticModel:
        """
        Inspect actual database state for this tenant business and build a deterministic,
        versioned TenantSemanticModel.
        """
        # 1. Audit relational entities and counts strictly isolated by business_id
        sales_count = db.execute(select(func.count(Sale.id)).where(Sale.business_id == business_id)).scalar() or 0
        customers_count = db.execute(select(func.count(Customer.id)).where(Customer.business_id == business_id)).scalar() or 0
        products_count = db.execute(select(func.count(Product.id)).where(Product.business_id == business_id)).scalar() or 0
        inventory_count = db.execute(select(func.count(Inventory.id)).where(Inventory.business_id == business_id)).scalar() or 0
        expenses_count = db.execute(select(func.count(Expense.id)).where(Expense.business_id == business_id)).scalar() or 0
        
        # SaleItem joins Sale on sale_id to strictly isolate tenant business
        sale_items_count = db.execute(
            select(func.count(SaleItem.id))
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(Sale.business_id == business_id)
        ).scalar() or 0

        # 2. Date coverage audit for Sales
        sales_dates = db.execute(
            select(func.min(Sale.transaction_date), func.max(Sale.transaction_date))
            .where(Sale.business_id == business_id)
        ).first()

        sales_start: Optional[str] = None
        sales_end: Optional[str] = None
        history_days = 0
        if sales_dates and sales_dates[0] and sales_dates[1]:
            d_min = sales_dates[0]
            d_max = sales_dates[1]
            sales_start = d_min.date().isoformat() if hasattr(d_min, "date") else str(d_min)[:10]
            sales_end = d_max.date().isoformat() if hasattr(d_max, "date") else str(d_max)[:10]
            if hasattr(d_min, "date") and hasattr(d_max, "date"):
                history_days = (d_max.date() - d_min.date()).days

        # 3. Check for cost data availability
        has_product_cost = False
        if products_count > 0:
            cost_sample = db.execute(
                select(Product.unit_cost)
                .where(Product.business_id == business_id, Product.unit_cost.is_not(None))
                .limit(1)
            ).scalar()
            has_product_cost = cost_sample is not None and cost_sample > 0

        # 4. Catalog Entities
        entities: Dict[str, Any] = {}
        if sales_count > 0:
            entities["Sale"] = {
                "entity_name": "Sale",
                "record_count": sales_count,
                "mapped_fields": {"transaction_date": "date", "total_amount": "amount", "transaction_number": "order_number"},
                "date_range_start": sales_start,
                "date_range_end": sales_end,
            }
        if customers_count > 0:
            sample_cust = db.execute(select(Customer.customer_code).where(Customer.business_id == business_id).limit(3)).scalars().all()
            entities["Customer"] = {
                "entity_name": "Customer",
                "record_count": customers_count,
                "mapped_fields": {"customer_code": "code", "name": "name", "city": "city"},
                "sample_identifiers": sample_cust,
            }
        if products_count > 0:
            sample_prod = db.execute(select(Product.sku).where(Product.business_id == business_id).limit(3)).scalars().all()
            entities["Product"] = {
                "entity_name": "Product",
                "record_count": products_count,
                "mapped_fields": {"sku": "sku", "name": "name", "selling_price": "selling_price", "unit_cost": "unit_cost"},
                "sample_identifiers": sample_prod,
            }
        if inventory_count > 0:
            entities["Inventory"] = {
                "entity_name": "Inventory",
                "record_count": inventory_count,
                "mapped_fields": {"stock_quantity": "stock_quantity", "reorder_threshold": "reorder_threshold"},
            }
        if expenses_count > 0:
            entities["Expense"] = {
                "entity_name": "Expense",
                "record_count": expenses_count,
                "mapped_fields": {"amount": "amount", "category": "category", "expense_date": "date"},
            }
        if sale_items_count > 0:
            entities["SaleItem"] = {
                "entity_name": "SaleItem",
                "record_count": sale_items_count,
                "mapped_fields": {"quantity": "quantity", "unit_price": "unit_price", "line_total": "line_total"},
            }

        # 5. Evaluate Metric Availability deterministically
        metrics: Dict[str, Any] = {}
        warnings: List[str] = []
        supported_analytics: List[str] = []
        unsupported_analytics: List[str] = [
            "Customer Lifetime Value (CLV)",
            "Customer Acquisition Cost (CAC)",
            "Net Promoter Score (NPS)",
            "Churn Prediction",
        ]

        for canonical_name, spec in cls.CANONICAL_METRIC_SPECS.items():
            req_entities = spec["required_entities"]
            missing_entities = [e for e in req_entities if e not in entities]

            if missing_entities:
                metrics[canonical_name] = {
                    "canonical_name": canonical_name,
                    "display_name": spec["display_name"],
                    "description": spec["description"],
                    "status": "UNAVAILABLE",
                    "source_table": spec["source_table"],
                    "source_field": spec["source_field"],
                    "calculation_formula": spec["calculation_formula"],
                    "unit": spec["unit"],
                    "business_domain": spec["business_domain"],
                    "analytics_tool": spec.get("analytics_tool", "get_financial_summary"),
                    "missing_prerequisites": [f"Missing {e} data" for e in missing_entities],
                }
                continue

            # Entity exists, check sub-conditions
            if spec.get("cost_sensitive") and not has_product_cost:
                metrics[canonical_name] = {
                    "canonical_name": canonical_name,
                    "display_name": spec["display_name"],
                    "description": spec["description"],
                    "status": "REQUIRES_COST_DATA",
                    "source_table": spec["source_table"],
                    "source_field": spec["source_field"],
                    "calculation_formula": spec["calculation_formula"],
                    "unit": spec["unit"],
                    "business_domain": spec["business_domain"],
                    "analytics_tool": spec.get("analytics_tool", "get_financial_summary"),
                    "missing_prerequisites": ["Product unit_cost or purchase price is required"],
                }
                warnings.append(f"{spec['display_name']} calculation requires cost data (unit cost or purchase price) which is not present in your catalog.")
                continue

            min_days = spec.get("min_days_history", 0)
            if min_days > 0 and history_days < min_days:
                metrics[canonical_name] = {
                    "canonical_name": canonical_name,
                    "display_name": spec["display_name"],
                    "description": spec["description"],
                    "status": "INSUFFICIENT_HISTORY",
                    "source_table": spec["source_table"],
                    "source_field": spec["source_field"],
                    "calculation_formula": spec["calculation_formula"],
                    "unit": spec["unit"],
                    "business_domain": spec["business_domain"],
                    "analytics_tool": spec.get("analytics_tool", "get_customer_metrics"),
                    "missing_prerequisites": [f"Requires at least {min_days} days of transactions (found {history_days} days)"],
                }
                warnings.append(f"{spec['display_name']} requires at least {min_days} days of transaction history (found {history_days} days).")
                continue

            # Metric is fully available
            metrics[canonical_name] = {
                "canonical_name": canonical_name,
                "display_name": spec["display_name"],
                "description": spec["description"],
                "status": "AVAILABLE",
                "source_table": spec["source_table"],
                "source_field": spec["source_field"],
                "calculation_formula": spec["calculation_formula"],
                "unit": spec["unit"],
                "business_domain": spec["business_domain"],
                "analytics_tool": spec.get("analytics_tool", "get_financial_summary"),
                "missing_prerequisites": [],
            }
            supported_analytics.append(spec["display_name"])

        # 6. Catalog Analytical Dimensions
        dimensions: Dict[str, Any] = {
            "date": {"dimension_name": "date", "source_table": "sales", "source_column": "transaction_date", "cardinality": history_days},
            "channel": {"dimension_name": "channel", "source_table": "sales", "source_column": "channel", "cardinality": 4, "sample_values": ["Online", "Retail Store", "Wholesale"]},
            "category": {"dimension_name": "category", "source_table": "products", "source_column": "category", "cardinality": products_count, "sample_values": ["General"]},
        }

        # 7. Collect Business Synonyms (incorporating OKF items if present)
        synonyms: Dict[str, str] = {
            "revenue": "net_revenue",
            "net sales": "net_revenue",
            "sales revenue": "net_revenue",
            "turnover": "net_revenue",
            "order count": "orders",
            "transactions": "orders",
            "number of orders": "orders",
            "units": "units_sold",
            "quantity": "units_sold",
            "volume": "units_sold",
            "margin": "gross_margin",
            "profit margin": "gross_margin",
            "client": "Customer",
            "buyer": "Customer",
            "account": "Customer",
            "customers": "Customer",
            "stock": "Inventory",
            "overhead": "Expense",
            "spending": "Expense",
            "expenses": "Expense",
        }

        # Merge custom synonyms from OKF knowledge items for this tenant
        okf_items = db.execute(
            select(OKFItemModel).where(OKFItemModel.business_id == business_id)
        ).scalars().all()
        for item in okf_items:
            if item.synonyms:
                target = item.metric_field or item.name
                for syn in item.synonyms:
                    synonyms[syn.lower().strip()] = target

        if custom_synonyms:
            for k, v in custom_synonyms.items():
                synonyms[k.lower().strip()] = v

        # 8. Deterministic Summary
        summary = {
            "sales_count": sales_count,
            "sales_date_start": sales_start,
            "sales_date_end": sales_end,
            "customers_count": customers_count,
            "products_count": products_count,
            "inventory_count": inventory_count,
            "expenses_count": expenses_count,
            "supported_analytics": supported_analytics,
            "unsupported_analytics": unsupported_analytics,
            "warnings": warnings,
        }

        # 9. Versioning, Idempotency, and Conflict Detection
        latest_model = db.execute(
            select(TenantSemanticModel)
            .where(TenantSemanticModel.business_id == business_id)
            .order_by(desc(TenantSemanticModel.version))
        ).scalars().first()

        conflicts: List[Dict[str, Any]] = []
        if latest_model:
            # Check for conflicting metric definitions
            old_metrics = latest_model.metrics_json or {}
            for m_name, m_val in metrics.items():
                if m_name in old_metrics:
                    old_val = old_metrics[m_name]
                    if old_val.get("calculation_formula") != m_val.get("calculation_formula"):
                        conflicts.append({
                            "type": "metric_formula_conflict",
                            "metric": m_name,
                            "existing_formula": old_val.get("calculation_formula"),
                            "proposed_formula": m_val.get("calculation_formula"),
                            "message": f"Conflict detected for metric '{m_name}': formula differs from previous active version.",
                        })

            if conflicts:
                # CONFLICT SAFETY:
                # Old verified model remains ACTIVE.
                # New conflicting model becomes REQUIRES_REVIEW.
                new_version = latest_model.version + 1
                status = "REQUIRES_REVIEW"
            else:
                # No conflicts: Check Idempotency via semantic fingerprint
                new_fingerprint = cls.compute_semantic_fingerprint(
                    entities=entities,
                    metrics=metrics,
                    dimensions=dimensions,
                    synonyms=synonyms,
                    ambiguous_terms=cls.DEFAULT_AMBIGUOUS_TERMS,
                    summary=summary,
                    source_dataset_id=source_dataset_id,
                )
                latest_fingerprint = cls.compute_semantic_fingerprint(
                    entities=latest_model.entities_json,
                    metrics=latest_model.metrics_json,
                    dimensions=latest_model.dimensions_json,
                    synonyms=latest_model.synonyms_json,
                    ambiguous_terms=latest_model.ambiguous_terms_json,
                    summary=latest_model.business_summary_json,
                    source_dataset_id=latest_model.source_dataset_id,
                )
                if new_fingerprint == latest_fingerprint:
                    logger.info(
                        "Semantic state unchanged for business %s (fingerprint %s). Reusing active model v%d.",
                        business_id,
                        new_fingerprint,
                        latest_model.version,
                    )
                    return latest_model

                # Meaningful change without conflict:
                new_version = latest_model.version + 1
                status = "ACTIVE"
                # Archive all previous ACTIVE models for this business to ensure ACTIVE count <= 1
                db.execute(
                    update(TenantSemanticModel)
                    .where(
                        TenantSemanticModel.business_id == business_id,
                        TenantSemanticModel.status == "ACTIVE",
                    )
                    .values(status="ARCHIVED", updated_at=datetime.now(timezone.utc))
                )
        else:
            new_version = 1
            status = "ACTIVE"

        # 10. Persist Model
        semantic_model = TenantSemanticModel(
            id=str(uuid4()),
            organization_id=organization_id,
            business_id=business_id,
            version=new_version,
            status=status,
            source_dataset_id=source_dataset_id,
            entities_json=entities,
            metrics_json=metrics,
            dimensions_json=dimensions,
            synonyms_json=synonyms,
            ambiguous_terms_json=cls.DEFAULT_AMBIGUOUS_TERMS,
            business_summary_json=summary,
            conflicts_json={"conflicts": conflicts} if conflicts else None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(semantic_model)

        # Update business semantic status
        biz = db.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        if biz:
            biz.semantic_status = status

        db.commit()
        db.refresh(semantic_model)
        logger.info(
            "Activated TenantSemanticModel v%d for business %s (status: %s)",
            new_version,
            business_id,
            status,
        )
        return semantic_model

    @classmethod
    def get_active_semantic_model(cls, business_id: str, db: Session) -> Optional[TenantSemanticModel]:
        """Fetch the single verified ACTIVE semantic model for the business."""
        return db.execute(
            select(TenantSemanticModel)
            .where(
                TenantSemanticModel.business_id == business_id,
                TenantSemanticModel.status == "ACTIVE",
            )
            .order_by(desc(TenantSemanticModel.version))
        ).scalars().first()

    @classmethod
    def list_revisions(cls, business_id: str, db: Session) -> List[SemanticRevisionSummary]:
        """List historical semantic model versions for the tenant business."""
        models = db.execute(
            select(TenantSemanticModel)
            .where(TenantSemanticModel.business_id == business_id)
            .order_by(desc(TenantSemanticModel.version))
        ).scalars().all()

        revisions: List[SemanticRevisionSummary] = []
        for m in models:
            metrics_avail = sum(
                1 for v in (m.metrics_json or {}).values() if v.get("status") == "AVAILABLE"
            )
            revisions.append(
                SemanticRevisionSummary(
                    id=m.id,
                    version=m.version,
                    status=m.status,
                    source_dataset_id=m.source_dataset_id,
                    created_at=m.created_at.isoformat() if m.created_at else "",
                    entities_count=len(m.entities_json or {}),
                    metrics_available_count=metrics_avail,
                )
            )
        return revisions

    @classmethod
    def to_response(cls, model: TenantSemanticModel) -> BusinessUnderstandingResponse:
        """Convert a TenantSemanticModel ORM instance to a structured response."""
        conflicts = (model.conflicts_json or {}).get("conflicts", [])
        return BusinessUnderstandingResponse(
            business_id=model.business_id,
            version=model.version,
            status=model.status,
            source_dataset_id=model.source_dataset_id,
            summary=BusinessDataSummary(**(model.business_summary_json or {})),
            entities={k: EntityUnderstanding(**v) for k, v in (model.entities_json or {}).items()},
            metrics={k: MetricAvailability(**v) for k, v in (model.metrics_json or {}).items()},
            dimensions={k: DimensionUnderstanding(**v) for k, v in (model.dimensions_json or {}).items()},
            synonyms=model.synonyms_json or {},
            ambiguous_terms=model.ambiguous_terms_json or {},
            has_conflicts=bool(conflicts),
            conflicts=conflicts,
            activated_at=model.created_at.isoformat() if model.created_at else None,
        )

    @classmethod
    def resolve_query_with_tenant_context(
        cls,
        query: str,
        business_id: str,
        db: Session,
    ) -> SemanticResolveResponse:
        """
        Deterministically resolve user query with full tenant business understanding,
        custom synonyms, availability status, and evidence provenance.
        """
        clean_query = query.lower().strip()
        tenant_model = cls.get_active_semantic_model(business_id=business_id, db=db)
        if tenant_model is None:
            return SemanticResolveResponse(
                query=query,
                availability_status="UNAVAILABLE",
                is_supported=False,
                unsupported_message="No active business understanding exists for this business. Please upload and activate your data first.",
            )

        metrics_dict = tenant_model.metrics_json or {}
        synonyms_dict = tenant_model.synonyms_json or {}
        ambig_dict = tenant_model.ambiguous_terms_json or cls.DEFAULT_AMBIGUOUS_TERMS


        # 1. Check for explicit unsupported metrics
        for unsupp_term, unsupp_msg in cls.UNSUPPORTED_METRICS.items():
            if f" {unsupp_term} " in f" {clean_query} " or clean_query == unsupp_term:
                return SemanticResolveResponse(
                    query=query,
                    availability_status="UNAVAILABLE",
                    is_supported=False,
                    unsupported_message=unsupp_msg,
                )

        # 2. Check for ambiguous business terms (e.g. "sales", "turnover", "margin")
        for ambig_term, info in ambig_dict.items():
            if f" {ambig_term} " in f" {clean_query} " or clean_query.endswith(ambig_term) or clean_query.startswith(ambig_term):
                has_qualifier = False
                for c in info["candidates"]:
                    c_clean = c.replace("_", " ")
                    if c_clean in clean_query and c_clean != ambig_term:
                        has_qualifier = True
                        break
                # Also check if a longer multi-word synonym containing ambig_term is present (e.g. "sales revenue", "net sales")
                if not has_qualifier:
                    for syn in synonyms_dict.keys():
                        if len(syn) > len(ambig_term) and ambig_term in syn and syn in clean_query:
                            has_qualifier = True
                            break
                if not has_qualifier:
                    return SemanticResolveResponse(
                        query=query,
                        availability_status="UNAVAILABLE",
                        is_ambiguous=True,
                        clarification_prompt=info["prompt"],
                        ambiguity_candidates=info["candidates"],
                        is_supported=True,
                    )

        # 3. Check tenant-specific custom synonyms (longest match first)
        matched_canonical: Optional[str] = None
        matched_synonym: Optional[str] = None
        sorted_synonyms = sorted(synonyms_dict.keys(), key=len, reverse=True)
        for syn in sorted_synonyms:
            if f" {syn} " in f" {clean_query} " or clean_query == syn:
                matched_canonical = synonyms_dict[syn]
                matched_synonym = syn
                break

        # Fallback to KPIOntology resolver if no tenant synonym matched
        if not matched_canonical:
            kpi_res = semantic_resolver.resolve(query)
            if kpi_res.canonical_name:
                matched_canonical = kpi_res.canonical_name
                matched_synonym = kpi_res.matched_synonym

        # 4. If canonical KPI was resolved, evaluate availability against tenant database state
        if matched_canonical and matched_canonical in metrics_dict:
            m_info = metrics_dict[matched_canonical]
            status = m_info.get("status", "AVAILABLE")
            unsupp_msg = None
            if status == "REQUIRES_COST_DATA":
                unsupp_msg = "Gross Margin calculation requires cost data (unit cost or purchase price) which is not present in your data."
            elif status == "INSUFFICIENT_HISTORY":
                unsupp_msg = f"{m_info.get('display_name')} requires at least 90 days of transaction history."
            elif status == "UNAVAILABLE":
                unsupp_msg = f"{m_info.get('display_name')} is not available based on your currently uploaded records."

            provenance = {
                "source_data": m_info.get("source_table", "sales"),
                "semantic_definition": f"{m_info.get('source_table')}.{m_info.get('source_field')}",
                "calculation": m_info.get("calculation_formula"),
                "availability": status,
                "tenant_scoped": True,
            }

            return SemanticResolveResponse(
                query=query,
                canonical_name=matched_canonical,
                canonical_kpi=matched_canonical,
                display_name=m_info.get("display_name"),
                analytics_tool=m_info.get("analytics_tool", "get_financial_summary"),
                metric_field=m_info.get("source_field"),
                availability_status=status,
                source_table=m_info.get("source_table"),
                source_field=m_info.get("source_field"),
                calculation_formula=m_info.get("calculation_formula"),
                unit=m_info.get("unit"),
                is_ambiguous=False,
                is_supported=True,
                unsupported_message=unsupp_msg,
                matched_synonym=matched_synonym,
                evidence_provenance=provenance,
            )

        # 5. Fallback clean canonical resolution if no tenant match
        canon = semantic_resolver.resolve(query)
        return SemanticResolveResponse(
            query=query,
            canonical_name=canon.canonical_name,
            canonical_kpi=canon.canonical_name,
            analytics_tool=canon.analytics_tool,
            metric_field=canon.metric_field,
            is_ambiguous=canon.is_ambiguous,
            clarification_prompt=canon.clarification_prompt,
            is_supported=canon.is_supported,
            unsupported_message=canon.unsupported_message,
            matched_synonym=canon.matched_synonym,
            availability_status="AVAILABLE",
        )
