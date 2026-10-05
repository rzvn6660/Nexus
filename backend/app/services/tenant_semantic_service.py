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
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.expense import Expense
from app.models.history import DecisionRecord
from app.models.inventory import Inventory
from app.models.okf import OKFItemModel
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, TenantSemanticModel, UploadedDataset
from app.rag.semantic.ontology import kpi_ontology, semantic_resolver
from app.schemas.semantic import (
    AmbiguousTermDiffItem,
    BusinessDataSummary,
    BusinessUnderstandingResponse,
    DimensionUnderstanding,
    EntityDiffItem,
    EntityUnderstanding,
    MetricAvailability,
    MetricDiffItem,
    SemanticDiffResponse,
    SemanticResolveResponse,
    SemanticReviewActionResponse,
    SemanticRevisionSummary,
    SynonymDiffItem,
)

logger = logging.getLogger(__name__)


class TenantSemanticService:
    """Service orchestrating tenant-specific business understanding, semantic activation, and resolution."""

    CANONICAL_METRIC_SPECS = {
        "net_revenue": {
            "display_name": "Net Revenue",
            "description": "Total realized commercial sales value after discounts.",
            "source_table": "sales",
            "source_field": "subtotal - discount_amount",
            "calculation_formula": "SUM(sales.subtotal - sales.discount_amount)",
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
            "source_field": "subtotal - discount_amount",
            "calculation_formula": "SUM(sales.subtotal - sales.discount_amount) / NULLIF(COUNT(sales.id), 0)",
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

    APPROVED_FORMULA_FUNCTIONS = {
        "SUM",
        "COUNT",
        "AVG",
        "MIN",
        "MAX",
        "ROUND",
        "NULLIF",
        "DISTINCT",
        "COALESCE",
        "ABS",
    }

    APPROVED_SOURCE_TABLES = {
        "sales",
        "sale_items",
        "products",
        "inventory",
        "customers",
        "expenses",
    }

    APPROVED_STANDALONE_IDENTIFIERS = {
        "revenue",
        "cogs",
        "repeat_customers",
        "all_customers",
        "sales",
        "discount",
        "id",
        "amount",
        "quantity",
    }

    FORBIDDEN_FORMULA_CHARACTERS = {
        ";", "--", "/*", "*/", "#", "`", "$", "\\", "{", "}", "[", "]",
        "|", "&", "^", "~", "!", "<", ">", "?", ":", "@", "'", '"',
    }

    FORBIDDEN_FORMULA_KEYWORDS = {
        "select",
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "union",
        "truncate",
        "from",
        "where",
        "join",
        "inner",
        "outer",
        "left",
        "right",
        "full",
        "on",
        "having",
        "group",
        "order",
        "limit",
        "offset",
        "exec",
        "execute",
        "eval",
        "import",
        "__import__",
        "system",
        "subprocess",
        "sh",
        "bash",
        "cmd",
        "powershell",
        "os",
        "sys",
        "lambda",
        "def",
        "class",
        "return",
        "yield",
        "open",
        "read",
        "write",
        "compile",
        "getattr",
        "setattr",
        "builtins",
        "globals",
        "locals",
        "vars",
    }

    @classmethod
    def validate_semantic_formula(cls, formula: str) -> None:
        """
        Validate reviewer-modified semantic formula against strict allowlisted expression grammar.
        Rejects semicolons, comments, SQL DDL/DML, SELECT, INSERT, UPDATE, DELETE, DROP, ALTER, CREATE,
        UNION, subqueries, Python syntax, eval/exec/import, shell expressions, unknown function names,
        and unknown source fields.
        Formula remains a semantic definition only, never executable code.
        """
        if not formula or not isinstance(formula, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Semantic formula cannot be empty.",
            )

        f_clean = formula.strip()
        if not f_clean:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Semantic formula cannot be whitespace-only.",
            )

        if len(f_clean) > 500:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Semantic formula exceeds maximum allowed length of 500 characters.",
            )

        # 1. Semicolons and comments
        if ";" in f_clean:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Semantic formula contains forbidden semicolon character.",
            )
        for c_pat in ["--", "/*", "*/", "#"]:
            if c_pat in f_clean:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Semantic formula contains forbidden comment pattern '{c_pat}'.",
                )

        # 2. Forbidden characters
        for char in cls.FORBIDDEN_FORMULA_CHARACTERS:
            if char in f_clean:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Semantic formula contains forbidden character: '{char}'.",
                )

        # 3. Forbidden keywords (SQL DDL/DML, commands, Python keywords)
        for kw in cls.FORBIDDEN_FORMULA_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", f_clean, re.IGNORECASE):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Semantic formula contains forbidden SQL/code keyword: '{kw}'.",
                )

        # 4. Balanced parentheses
        paren_balance = 0
        for ch in f_clean:
            if ch == "(":
                paren_balance += 1
            elif ch == ")":
                paren_balance -= 1
                if paren_balance < 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Semantic formula has mismatched parentheses.",
                    )
        if paren_balance != 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Semantic formula has unclosed parentheses.",
            )

        # 5. Token validation (approved functions and approved table fields)
        tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?\b", f_clean)
        for token in tokens:
            if "." in token:
                table, col = token.split(".", 1)
                if table.lower() not in cls.APPROVED_SOURCE_TABLES:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Semantic formula references unknown source table '{table}'. Approved tables: {sorted(cls.APPROVED_SOURCE_TABLES)}",
                    )
                if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", col):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Semantic formula contains invalid column identifier '{col}'.",
                    )
            else:
                upper_tok = token.upper()
                lower_tok = token.lower()
                if (
                    upper_tok not in cls.APPROVED_FORMULA_FUNCTIONS
                    and lower_tok not in cls.APPROVED_STANDALONE_IDENTIFIERS
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Semantic formula references unknown function or field '{token}'.",
                    )

        # 6. Syntax validation outside tokens, numbers, and allowed punctuation
        stripped = re.sub(r"\b[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?\b", "", f_clean)
        stripped = re.sub(r"\b\d+(?:\.\d+)?\b", "", stripped)
        stripped = re.sub(r"[\s\+\-\*\/\(\)\,\.]", "", stripped)
        if stripped:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Semantic formula contains unsupported syntax or characters: '{stripped}'.",
            )

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
        entities_dict = {}
        for k, v in (model.entities_json or {}).items():
            if isinstance(v, dict):
                v_copy = dict(v)
                if "entity_name" not in v_copy:
                    v_copy["entity_name"] = k
                entities_dict[k] = EntityUnderstanding(**v_copy)

        metrics_dict = {}
        for k, v in (model.metrics_json or {}).items():
            if isinstance(v, dict):
                v_copy = dict(v)
                if "canonical_name" not in v_copy:
                    v_copy["canonical_name"] = k
                if "display_name" not in v_copy:
                    v_copy["display_name"] = k.replace("_", " ").title()
                if "description" not in v_copy:
                    v_copy["description"] = v_copy.get("display_name", k)
                if "unit" not in v_copy:
                    v_copy["unit"] = "currency"
                if "business_domain" not in v_copy:
                    v_copy["business_domain"] = "finance"
                if "status" not in v_copy:
                    v_copy["status"] = "AVAILABLE"
                metrics_dict[k] = MetricAvailability(**v_copy)

        dims_dict = {}
        for k, v in (model.dimensions_json or {}).items():
            if isinstance(v, dict):
                v_copy = dict(v)
                if "dimension_name" not in v_copy:
                    v_copy["dimension_name"] = k
                dims_dict[k] = DimensionUnderstanding(**v_copy)

        return BusinessUnderstandingResponse(
            business_id=model.business_id,
            version=model.version,
            status=model.status,
            source_dataset_id=model.source_dataset_id,
            summary=BusinessDataSummary(**(model.business_summary_json or {})),
            entities=entities_dict,
            metrics=metrics_dict,
            dimensions=dims_dict,
            synonyms=model.synonyms_json or {},
            ambiguous_terms=model.ambiguous_terms_json or {},
            has_conflicts=bool(conflicts),
            conflicts=conflicts,
            activated_at=model.created_at.isoformat() if model.created_at else None,
        )

    @classmethod
    def get_revision(cls, revision_id: str, business_id: str, db: Session) -> Optional[TenantSemanticModel]:
        """Fetch a specific historical or review-pending semantic model revision."""
        return db.execute(
            select(TenantSemanticModel).where(
                TenantSemanticModel.id == revision_id,
                TenantSemanticModel.business_id == business_id,
            )
        ).scalar_one_or_none()

    @classmethod
    def compute_revision_diff(
        cls,
        target_revision_id: str,
        business_id: str,
        db: Session,
        base_revision_id: Optional[str] = None,
    ) -> SemanticDiffResponse:
        """
        Deterministically compare target revision against base revision (or current ACTIVE model).
        Categorizes differences as ADDED, REMOVED, CHANGED, or UNCHANGED.
        """
        target_model = cls.get_revision(target_revision_id, business_id, db)
        if not target_model:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Target semantic revision '{target_revision_id}' not found for this business workspace.",
            )

        base_model = None
        if base_revision_id:
            base_model = cls.get_revision(base_revision_id, business_id, db)
            if not base_model:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Base semantic revision '{base_revision_id}' not found for this business workspace.",
                )
        else:
            base_model = cls.get_active_semantic_model(business_id, db)
            if base_model and base_model.id == target_model.id:
                base_model = db.execute(
                    select(TenantSemanticModel)
                    .where(
                        TenantSemanticModel.business_id == business_id,
                        TenantSemanticModel.version < target_model.version,
                    )
                    .order_by(desc(TenantSemanticModel.version))
                ).scalars().first()

        t_metrics = target_model.metrics_json or {}
        t_entities = target_model.entities_json or {}
        t_synonyms = target_model.synonyms_json or {}
        t_ambig = target_model.ambiguous_terms_json or {}
        t_conflicts = (target_model.conflicts_json or {}).get("conflicts", [])
        conflict_metrics = {c["metric"]: c.get("message", "Formula conflict") for c in t_conflicts if "metric" in c}

        b_metrics = base_model.metrics_json or {} if base_model else {}
        b_entities = base_model.entities_json or {} if base_model else {}
        b_synonyms = base_model.synonyms_json or {} if base_model else {}
        b_ambig = base_model.ambiguous_terms_json or {} if base_model else {}

        # 1. Metric Diffs
        metric_diffs: List[MetricDiffItem] = []
        all_metric_keys = sorted(set(b_metrics.keys()).union(set(t_metrics.keys())))
        for m_key in all_metric_keys:
            in_base = m_key in b_metrics
            in_target = m_key in t_metrics
            has_conf = m_key in conflict_metrics
            conf_msg = conflict_metrics.get(m_key)

            if in_target and not in_base:
                t_val = t_metrics[m_key]
                metric_diffs.append(
                    MetricDiffItem(
                        metric_name=m_key,
                        change_type="ADDED",
                        proposed_definition=f"{t_val.get('source_table')}.{t_val.get('source_field')}",
                        proposed_formula=t_val.get("calculation_formula"),
                        proposed_availability=t_val.get("status"),
                        source_data=t_val.get("source_table"),
                        has_conflict=has_conf,
                        conflict_reason=conf_msg,
                    )
                )
            elif in_base and not in_target:
                b_val = b_metrics[m_key]
                metric_diffs.append(
                    MetricDiffItem(
                        metric_name=m_key,
                        change_type="REMOVED",
                        previous_definition=f"{b_val.get('source_table')}.{b_val.get('source_field')}",
                        previous_formula=b_val.get("calculation_formula"),
                        previous_availability=b_val.get("status"),
                        source_data=b_val.get("source_table"),
                        has_conflict=False,
                    )
                )
            else:
                b_val = b_metrics[m_key]
                t_val = t_metrics[m_key]
                formula_changed = b_val.get("calculation_formula") != t_val.get("calculation_formula")
                status_changed = b_val.get("status") != t_val.get("status")
                source_changed = (
                    b_val.get("source_table") != t_val.get("source_table")
                    or b_val.get("source_field") != t_val.get("source_field")
                )

                change_type = "CHANGED" if (formula_changed or status_changed or source_changed or has_conf) else "UNCHANGED"
                metric_diffs.append(
                    MetricDiffItem(
                        metric_name=m_key,
                        change_type=change_type,
                        previous_definition=f"{b_val.get('source_table')}.{b_val.get('source_field')}",
                        proposed_definition=f"{t_val.get('source_table')}.{t_val.get('source_field')}",
                        previous_formula=b_val.get("calculation_formula"),
                        proposed_formula=t_val.get("calculation_formula"),
                        previous_availability=b_val.get("status"),
                        proposed_availability=t_val.get("status"),
                        source_data=t_val.get("source_table"),
                        has_conflict=has_conf,
                        conflict_reason=conf_msg,
                    )
                )

        # 2. Entity Diffs
        entity_diffs: List[EntityDiffItem] = []
        all_entity_keys = sorted(set(b_entities.keys()).union(set(t_entities.keys())))
        for e_key in all_entity_keys:
            in_base = e_key in b_entities
            in_target = e_key in t_entities

            if in_target and not in_base:
                t_val = t_entities[e_key]
                entity_diffs.append(
                    EntityDiffItem(
                        entity_name=e_key,
                        change_type="ADDED",
                        proposed_count=t_val.get("record_count", 0),
                        proposed_fields=t_val.get("mapped_fields", {}),
                    )
                )
            elif in_base and not in_target:
                b_val = b_entities[e_key]
                entity_diffs.append(
                    EntityDiffItem(
                        entity_name=e_key,
                        change_type="REMOVED",
                        previous_count=b_val.get("record_count", 0),
                        previous_fields=b_val.get("mapped_fields", {}),
                    )
                )
            else:
                b_val = b_entities[e_key]
                t_val = t_entities[e_key]
                count_diff = b_val.get("record_count", 0) != t_val.get("record_count", 0)
                fields_diff = b_val.get("mapped_fields", {}) != t_val.get("mapped_fields", {})
                change_type = "CHANGED" if (count_diff or fields_diff) else "UNCHANGED"
                entity_diffs.append(
                    EntityDiffItem(
                        entity_name=e_key,
                        change_type=change_type,
                        previous_count=b_val.get("record_count", 0),
                        proposed_count=t_val.get("record_count", 0),
                        previous_fields=b_val.get("mapped_fields", {}),
                        proposed_fields=t_val.get("mapped_fields", {}),
                    )
                )

        # 3. Synonym Diffs
        synonym_diffs: List[SynonymDiffItem] = []
        all_syn_keys = sorted(set(b_synonyms.keys()).union(set(t_synonyms.keys())))
        for s_key in all_syn_keys:
            in_base = s_key in b_synonyms
            in_target = s_key in t_synonyms

            if in_target and not in_base:
                synonym_diffs.append(
                    SynonymDiffItem(
                        term=s_key,
                        change_type="ADDED",
                        proposed_target=t_synonyms[s_key],
                    )
                )
            elif in_base and not in_target:
                synonym_diffs.append(
                    SynonymDiffItem(
                        term=s_key,
                        change_type="REMOVED",
                        previous_target=b_synonyms[s_key],
                    )
                )
            else:
                change_type = "CHANGED" if b_synonyms[s_key] != t_synonyms[s_key] else "UNCHANGED"
                synonym_diffs.append(
                    SynonymDiffItem(
                        term=s_key,
                        change_type=change_type,
                        previous_target=b_synonyms[s_key],
                        proposed_target=t_synonyms[s_key],
                    )
                )

        # 4. Ambiguous Terms Diffs
        ambig_diffs: List[AmbiguousTermDiffItem] = []
        all_ambig_keys = sorted(set(b_ambig.keys()).union(set(t_ambig.keys())))
        for a_key in all_ambig_keys:
            in_base = a_key in b_ambig
            in_target = a_key in t_ambig
            if in_target and not in_base:
                ambig_diffs.append(
                    AmbiguousTermDiffItem(
                        term=a_key,
                        change_type="ADDED",
                        proposed_candidates=t_ambig[a_key].get("candidates", []),
                    )
                )
            elif in_base and not in_target:
                ambig_diffs.append(
                    AmbiguousTermDiffItem(
                        term=a_key,
                        change_type="REMOVED",
                        previous_candidates=b_ambig[a_key].get("candidates", []),
                    )
                )
            else:
                b_cands = b_ambig[a_key].get("candidates", [])
                t_cands = t_ambig[a_key].get("candidates", [])
                change_type = "CHANGED" if b_cands != t_cands else "UNCHANGED"
                ambig_diffs.append(
                    AmbiguousTermDiffItem(
                        term=a_key,
                        change_type=change_type,
                        previous_candidates=b_cands,
                        proposed_candidates=t_cands,
                    )
                )

        # Summary diff
        b_sum = base_model.business_summary_json or {} if base_model else {}
        t_sum = target_model.business_summary_json or {}
        summary_diff = {
            "sales_count_diff": t_sum.get("sales_count", 0) - b_sum.get("sales_count", 0),
            "customers_count_diff": t_sum.get("customers_count", 0) - b_sum.get("customers_count", 0),
            "products_count_diff": t_sum.get("products_count", 0) - b_sum.get("products_count", 0),
            "inventory_count_diff": t_sum.get("inventory_count", 0) - b_sum.get("inventory_count", 0),
            "expenses_count_diff": t_sum.get("expenses_count", 0) - b_sum.get("expenses_count", 0),
        }

        return SemanticDiffResponse(
            base_revision_id=base_model.id if base_model else None,
            base_version=base_model.version if base_model else None,
            target_revision_id=target_model.id,
            target_version=target_model.version,
            has_conflicts=bool(t_conflicts),
            conflicts_count=len(t_conflicts),
            summary_diff=summary_diff,
            metric_diffs=metric_diffs,
            entity_diffs=entity_diffs,
            synonym_diffs=synonym_diffs,
            ambiguous_term_diffs=ambig_diffs,
        )

    @classmethod
    def approve_revision(
        cls,
        revision_id: str,
        business_id: str,
        reviewer_user_id: str,
        reviewer_email: str,
        db: Session,
        comment: Optional[str] = None,
    ) -> Tuple[TenantSemanticModel, DecisionRecord]:
        """
        Atomically approve a proposed semantic revision (REQUIRES_REVIEW -> ACTIVE).
        Archives any currently ACTIVE revision to uphold the active-model invariant (<= 1 active model).
        Records review decision in DecisionRecord HITL ledger.
        """
        # Concurrency serialization: lock parent Business record first
        biz = db.execute(
            select(Business).where(Business.id == business_id).with_for_update()
        ).scalar_one_or_none()
        if not biz:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Business workspace '{business_id}' not found.",
            )

        revision = db.execute(
            select(TenantSemanticModel)
            .where(
                TenantSemanticModel.id == revision_id,
                TenantSemanticModel.business_id == business_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if not revision:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Semantic revision '{revision_id}' not found for this business workspace.",
            )

        if revision.status == "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Semantic revision is already ACTIVE.",
            )

        if revision.status != "REQUIRES_REVIEW":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Revision with status '{revision.status}' is not eligible for approval. Only REQUIRES_REVIEW revisions can be approved.",
            )

        # 1. Archive all existing ACTIVE models for this business
        db.execute(
            update(TenantSemanticModel)
            .where(
                TenantSemanticModel.business_id == business_id,
                TenantSemanticModel.status == "ACTIVE",
            )
            .values(status="ARCHIVED", updated_at=datetime.now(timezone.utc))
        )

        # 2. Transition target revision to ACTIVE
        previous_status = revision.status
        revision.status = "ACTIVE"
        revision.updated_at = datetime.now(timezone.utc)

        # 3. Attach review audit metadata to revision
        conflicts_data = dict(revision.conflicts_json or {})
        conflicts_data["resolved"] = True
        conflicts_data["resolved_at"] = datetime.now(timezone.utc).isoformat()
        conflicts_data["resolved_by"] = reviewer_email or reviewer_user_id
        conflicts_data["review"] = {
            "action": "APPROVED",
            "reviewed_by": reviewer_email or reviewer_user_id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "comment": comment or "Approved semantic revision changes.",
            "previous_status": previous_status,
        }
        revision.conflicts_json = conflicts_data

        # 4. Update Business semantic_status to ACTIVE
        biz.semantic_status = "ACTIVE"

        # 5. Persist HITL DecisionRecord
        decision = DecisionRecord(
            business_id=business_id,
            organization_id=revision.organization_id,
            recommendation_text=f"Approved semantic model revision v{revision.version} ({revision.id})",
            status="APPROVED",
            reviewer_notes=comment or "Approved semantic changes and resolved definition conflicts.",
            reviewed_by=reviewer_email or reviewer_user_id,
            reviewed_at=datetime.now(timezone.utc),
        )
        db.add(decision)
        db.commit()
        db.refresh(revision)
        db.refresh(decision)

        logger.info(
            "Approved TenantSemanticModel v%d (%s) for business %s by %s. Status is now ACTIVE.",
            revision.version,
            revision.id,
            business_id,
            reviewer_email or reviewer_user_id,
        )
        return revision, decision

    @classmethod
    def reject_revision(
        cls,
        revision_id: str,
        business_id: str,
        reviewer_user_id: str,
        reviewer_email: str,
        db: Session,
        comment: Optional[str] = None,
    ) -> Tuple[TenantSemanticModel, DecisionRecord]:
        """
        Reject a proposed semantic revision (REQUIRES_REVIEW -> REJECTED).
        Leaves currently verified ACTIVE model untouched.
        Records rejection decision in DecisionRecord HITL ledger.
        """
        # Concurrency serialization: lock parent Business record first
        biz = db.execute(
            select(Business).where(Business.id == business_id).with_for_update()
        ).scalar_one_or_none()
        if not biz:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Business workspace '{business_id}' not found.",
            )

        revision = db.execute(
            select(TenantSemanticModel)
            .where(
                TenantSemanticModel.id == revision_id,
                TenantSemanticModel.business_id == business_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if not revision:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Semantic revision '{revision_id}' not found for this business workspace.",
            )

        if revision.status == "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reject an ACTIVE semantic model. It is currently in production.",
            )

        if revision.status != "REQUIRES_REVIEW":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Revision with status '{revision.status}' is not eligible for rejection.",
            )

        previous_status = revision.status
        revision.status = "REJECTED"
        revision.updated_at = datetime.now(timezone.utc)

        conflicts_data = dict(revision.conflicts_json or {})
        conflicts_data["review"] = {
            "action": "REJECTED",
            "reviewed_by": reviewer_email or reviewer_user_id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "comment": comment or "Rejected proposed semantic revision.",
            "previous_status": previous_status,
        }
        revision.conflicts_json = conflicts_data

        # If business has no other pending reviews, set business semantic_status back to ACTIVE
        remaining_pending = db.execute(
            select(func.count(TenantSemanticModel.id))
            .where(
                TenantSemanticModel.business_id == business_id,
                TenantSemanticModel.status == "REQUIRES_REVIEW",
            )
        ).scalar() or 0

        if remaining_pending == 0:
            active_model = cls.get_active_semantic_model(business_id, db)
            biz.semantic_status = "ACTIVE" if active_model else "NOT_ACTIVATED"

        decision = DecisionRecord(
            business_id=business_id,
            organization_id=revision.organization_id,
            recommendation_text=f"Rejected semantic model revision v{revision.version} ({revision.id})",
            status="REJECTED",
            reviewer_notes=comment or "Rejected proposed semantic changes. Active model preserved.",
            reviewed_by=reviewer_email or reviewer_user_id,
            reviewed_at=datetime.now(timezone.utc),
        )
        db.add(decision)
        db.commit()
        db.refresh(revision)
        db.refresh(decision)

        logger.info(
            "Rejected TenantSemanticModel v%d (%s) for business %s by %s.",
            revision.version,
            revision.id,
            business_id,
            reviewer_email or reviewer_user_id,
        )
        return revision, decision

    @classmethod
    def modify_revision(
        cls,
        revision_id: str,
        business_id: str,
        reviewer_user_id: str,
        reviewer_email: str,
        db: Session,
        metrics_override: Dict[str, Dict[str, Any]],
        custom_synonyms: Optional[Dict[str, str]] = None,
        comment: Optional[str] = None,
    ) -> Tuple[TenantSemanticModel, DecisionRecord]:
        """
        Create a new immutable revision incorporating human reviewer modifications.
        The source revision remains immutable and is marked SUPERSEDED.
        The newly created revision is placed in REQUIRES_REVIEW for subsequent verification/approval.
        All reviewer formulas are deterministically validated before persistence.
        """
        # 1. Deterministic formula safety validation on all reviewer overrides
        for m_name, m_override in metrics_override.items():
            if isinstance(m_override, dict):
                formula = m_override.get("calculation_formula")
                if formula is not None:
                    cls.validate_semantic_formula(str(formula))

        # Concurrency serialization: lock parent Business record first
        biz = db.execute(
            select(Business).where(Business.id == business_id).with_for_update()
        ).scalar_one_or_none()
        if not biz:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Business workspace '{business_id}' not found.",
            )

        source_rev = db.execute(
            select(TenantSemanticModel)
            .where(
                TenantSemanticModel.id == revision_id,
                TenantSemanticModel.business_id == business_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if not source_rev:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source semantic revision '{revision_id}' not found.",
            )

        if source_rev.status not in ["REQUIRES_REVIEW", "ACTIVE"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot modify revision with status '{source_rev.status}'. Only REQUIRES_REVIEW or ACTIVE revisions can be modified.",
            )

        if source_rev.status == "REQUIRES_REVIEW":
            source_rev.status = "SUPERSEDED"
            source_rev.updated_at = datetime.now(timezone.utc)

        latest_model = db.execute(
            select(TenantSemanticModel)
            .where(TenantSemanticModel.business_id == business_id)
            .order_by(desc(TenantSemanticModel.version))
        ).scalars().first()
        new_version = (latest_model.version + 1) if latest_model else 1

        entities = dict(source_rev.entities_json or {})
        dimensions = dict(source_rev.dimensions_json or {})
        summary = dict(source_rev.business_summary_json or {})
        ambiguous = dict(source_rev.ambiguous_terms_json or cls.DEFAULT_AMBIGUOUS_TERMS)
        synonyms = dict(source_rev.synonyms_json or {})
        metrics = {k: dict(v) for k, v in (source_rev.metrics_json or {}).items()}

        for m_name, m_override in metrics_override.items():
            if m_name in metrics:
                metrics[m_name].update(m_override)
            else:
                metrics[m_name] = m_override

        if custom_synonyms:
            for s_k, s_v in custom_synonyms.items():
                synonyms[s_k.lower().strip()] = s_v

        active_model = cls.get_active_semantic_model(business_id, db)
        conflicts: List[Dict[str, Any]] = []
        if active_model:
            old_metrics = active_model.metrics_json or {}
            for m_name, m_val in metrics.items():
                if m_name in old_metrics:
                    old_f = old_metrics[m_name].get("calculation_formula")
                    new_f = m_val.get("calculation_formula")
                    if old_f != new_f:
                        conflicts.append({
                            "type": "metric_formula_conflict",
                            "metric": m_name,
                            "existing_formula": old_f,
                            "proposed_formula": new_f,
                            "message": f"Reviewer modified formula for '{m_name}': differs from verified active formula.",
                        })

        conflicts_payload = {
            "conflicts": conflicts,
            "parent_revision_id": source_rev.id,
            "parent_version": source_rev.version,
            "modification_note": comment or "Reviewer adjusted metric formulas/definitions",
            "modified_by": reviewer_email or reviewer_user_id,
            "modified_at": datetime.now(timezone.utc).isoformat(),
            "modified_fields": list(metrics_override.keys()),
        }

        new_model = TenantSemanticModel(
            id=str(uuid4()),
            organization_id=source_rev.organization_id,
            business_id=business_id,
            version=new_version,
            status="REQUIRES_REVIEW",
            source_dataset_id=source_rev.source_dataset_id,
            entities_json=entities,
            metrics_json=metrics,
            dimensions_json=dimensions,
            synonyms_json=synonyms,
            ambiguous_terms_json=ambiguous,
            business_summary_json=summary,
            conflicts_json=conflicts_payload,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(new_model)

        biz.semantic_status = "REQUIRES_REVIEW"

        decision = DecisionRecord(
            business_id=business_id,
            organization_id=source_rev.organization_id,
            recommendation_text=f"Reviewer modified semantic revision v{source_rev.version} -> created v{new_version}",
            status="MODIFIED",
            reviewer_notes=comment or f"Modified metric formulas for: {', '.join(metrics_override.keys())}",
            reviewed_by=reviewer_email or reviewer_user_id,
            reviewed_at=datetime.now(timezone.utc),
        )
        db.add(decision)
        db.commit()
        db.refresh(new_model)
        db.refresh(decision)

        logger.info(
            "Created modified TenantSemanticModel v%d (%s) for business %s based on parent v%d.",
            new_version,
            new_model.id,
            business_id,
            source_rev.version,
        )
        return new_model, decision

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
        clean_query = re.sub(r"[^\w\s]", " ", query.lower()).strip()
        clean_query = " ".join(clean_query.split())
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
                if not has_qualifier:
                    for syn in synonyms_dict.keys():
                        syn_clean = syn.replace("_", " ")
                        if len(syn_clean) > len(ambig_term) and (syn in clean_query or syn_clean in clean_query) and (ambig_term in syn or ambig_term in syn_clean):
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
            syn_clean = syn.replace("_", " ")
            if (
                f" {syn} " in f" {clean_query} "
                or f" {syn_clean} " in f" {clean_query} "
                or clean_query == syn
                or clean_query == syn_clean
            ):
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
            m_info = dict(metrics_dict[matched_canonical])
            canon_spec = cls.CANONICAL_METRIC_SPECS.get(matched_canonical)
            if canon_spec:
                if m_info.get("calculation_formula") in ("SUM(sales.total_amount)", None):
                    m_info["calculation_formula"] = canon_spec["calculation_formula"]
                if m_info.get("source_field") in ("total_amount", None):
                    m_info["source_field"] = canon_spec["source_field"]
            status = m_info.get("status", "AVAILABLE")
            unsupp_msg = None
            if status == "REQUIRES_COST_DATA":
                unsupp_msg = "Gross Margin calculation requires cost data (unit cost or purchase price) which is not present in your data."
            elif status == "INSUFFICIENT_HISTORY":
                unsupp_msg = f"{m_info.get('display_name')} requires at least 90 days of transaction history."
            elif status == "UNAVAILABLE":
                unsupp_msg = f"{m_info.get('display_name')} is not available based on your currently uploaded records."

            sem_ver = None
            sem_id = None
            if tenant_model:
                v_val = getattr(tenant_model, "version", None)
                if isinstance(v_val, int):
                    sem_ver = v_val
                elif v_val is not None and not type(v_val).__name__.startswith("MagicMock"):
                    try:
                        sem_ver = int(v_val)
                    except (ValueError, TypeError):
                        sem_ver = None

                id_val = getattr(tenant_model, "id", None)
                if isinstance(id_val, str):
                    sem_id = id_val
                elif id_val is not None and not type(id_val).__name__.startswith("MagicMock"):
                    sem_id = str(id_val)

            provenance = {
                "source_data": m_info.get("source_table", "sales"),
                "semantic_definition": f"{m_info.get('source_table')}.{m_info.get('source_field')}",
                "calculation": m_info.get("calculation_formula"),
                "availability": status,
                "tenant_scoped": True,
                "semantic_version": sem_ver,
                "semantic_revision_id": sem_id,
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
                semantic_version=sem_ver,
                semantic_revision_id=sem_id,
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
