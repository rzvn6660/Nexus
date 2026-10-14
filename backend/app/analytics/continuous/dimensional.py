"""Deterministic dimensional change decomposition for Continuous Intelligence (Phase 29 Stage 2).

Reuses and extends variance diagnostics from VarianceDiagnosticAnalyzer to explain
detected business metric movements across available catalog and customer dimensions:
- Product Category (Product.category)
- Product SKU / Name (Product.sku, Product.name)
- Customer Segment (Customer.customer_segment)

Guarantees:
1. Strict mathematical reconciliation for additive metrics (sales, units, orders).
2. Mathematically grounded ratio factor decomposition for ratio metrics (AOV, gross margin),
   avoiding distorted additive summation.
3. Non-causality transparency: clear separation between measured contribution and causal attribution.
4. Safe numerical handling: zero baselines, negative values, and zero variances avoid division-by-zero.
5. Graceful degradation: missing dimensions or catalog tables record structured limitations without
   failing the overarching continuous intelligence finding.
"""

import logging
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, ClassVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem

logger = logging.getLogger(__name__)

NON_CAUSALITY_ATTRIBUTION_DISCLAIMER = (
    "Measured dimensional contributions reflect deterministic mathematical decomposition "
    "of aggregate variance across observed historical data. They identify mathematical drivers "
    "of recorded change but do not assert causal attribution, economic causality, or control "
    "for unobserved confounding factors. Consequential decisions require human verification."
)


class DimensionalDecomposer:
    """Deterministic dimensional variance decomposition engine."""

    RECONCILIATION_TOLERANCE: float = 0.05

    SUPPORTED_DIMENSIONS_BY_METRIC: ClassVar[dict[str, list[str]]] = {
        "net_sales": ["category", "product", "customer_segment"],
        "gross_sales": ["category", "product", "customer_segment"],
        "units_sold": ["category", "product"],
        "orders_count": ["customer_segment"],
        "average_order_value": ["customer_segment"],
        "gross_margin_pct": ["category"],
    }

    @classmethod
    def decompose_metric_variance(
        cls,
        db: Session,
        business_id: str,
        metric_key: str,
        current_start: datetime,
        current_end: datetime,
        baseline_start: datetime,
        baseline_end: datetime,
        aggregate_delta: float,
        current_aggregate: float,
        baseline_aggregate: float,
        top_n: int = 5,
    ) -> dict[str, Any]:
        """
        Decompose aggregate metric change across all available and applicable dimensions.
        Returns a structured dictionary containing per-dimension contributor rankings,
        reconciliation telemetry, source provenance, and any recorded limitations.
        """
        # Ratio metrics (AOV, Margin) require separate ratio factor decomposition
        if metric_key in ("average_order_value", "gross_margin_pct"):
            return cls._decompose_ratio_metric(
                db=db,
                business_id=business_id,
                metric_key=metric_key,
                current_start=current_start,
                current_end=current_end,
                baseline_start=baseline_start,
                baseline_end=baseline_end,
                aggregate_delta=aggregate_delta,
                current_aggregate=current_aggregate,
                baseline_aggregate=baseline_aggregate,
                top_n=top_n,
            )

        candidate_dimensions = cls.SUPPORTED_DIMENSIONS_BY_METRIC.get(metric_key, [])
        if not candidate_dimensions:
            return {
                "status": "UNAVAILABLE",
                "metric_key": metric_key,
                "aggregate_delta": round(aggregate_delta, 2),
                "dimensions": {},
                "primary_dimension": None,
                "primary_driver": None,
                "limitations": [f"Metric '{metric_key}' does not support dimensional decomposition."],
                "provenance": cls._build_provenance(metric_key, "none"),
            }

        dimensions_result: dict[str, Any] = {}
        global_limitations: list[str] = []
        best_primary_driver: dict[str, Any] | None = None
        best_primary_dimension: str | None = None
        highest_abs_contrib: float = -1.0

        for dim in candidate_dimensions:
            decomp = cls._decompose_single_dimension(
                db=db,
                business_id=business_id,
                metric_key=metric_key,
                dimension=dim,
                current_start=current_start,
                current_end=current_end,
                baseline_start=baseline_start,
                baseline_end=baseline_end,
                aggregate_delta=aggregate_delta,
                current_aggregate=current_aggregate,
                baseline_aggregate=baseline_aggregate,
                top_n=top_n,
            )
            dimensions_result[dim] = decomp

            if decomp.get("status") == "AVAILABLE":
                # Find leading contributor for high-level finding summary
                top_pos = decomp.get("top_positive_contributors", [])
                top_neg = decomp.get("top_negative_contributors", [])
                candidates = top_pos + top_neg
                for c in candidates:
                    abs_contrib = abs(c.get("contribution_to_change_pct", 0.0))
                    if abs_contrib > highest_abs_contrib:
                        highest_abs_contrib = abs_contrib
                        best_primary_dimension = dim
                        best_primary_driver = {
                            "dimension": dim,
                            "entity_id": c.get("entity_id"),
                            "entity_name": c.get("entity_name"),
                            "absolute_change": c.get("absolute_change"),
                            "contribution_pct": c.get("contribution_to_change_pct"),
                            "current_value": c.get("current_value"),
                            "baseline_value": c.get("baseline_value"),
                        }
            else:
                if decomp.get("limitations"):
                    global_limitations.extend(decomp["limitations"])

        available_count = sum(1 for d in dimensions_result.values() if d.get("status") == "AVAILABLE")
        if available_count == 0:
            status = "UNAVAILABLE"
        elif available_count == len(candidate_dimensions):
            status = "AVAILABLE"
        else:
            status = "PARTIALLY_AVAILABLE"

        return {
            "status": status,
            "metric_key": metric_key,
            "decomposition_type": "ADDITIVE_VARIANCE_DECOMPOSITION",
            "aggregate_delta": round(aggregate_delta, 2),
            "current_aggregate": round(current_aggregate, 2),
            "baseline_aggregate": round(baseline_aggregate, 2),
            "dimensions": dimensions_result,
            "primary_dimension": best_primary_dimension,
            "primary_driver": best_primary_driver,
            "limitations": list(dict.fromkeys(global_limitations)),
            "provenance": cls._build_provenance(metric_key, best_primary_dimension or "multiple"),
        }

    @classmethod
    def _decompose_ratio_metric(
        cls,
        db: Session,
        business_id: str,
        metric_key: str,
        current_start: datetime,
        current_end: datetime,
        baseline_start: datetime,
        baseline_end: datetime,
        aggregate_delta: float,
        current_aggregate: float,
        baseline_aggregate: float,
        top_n: int = 5,
    ) -> dict[str, Any]:
        """
        Decomposes ratio metrics (average_order_value, gross_margin_pct) into
        constituent numerator and denominator effects, rejecting unjustified additive reconciliation.
        """
        valid_statuses = ["completed", "shipped"]

        if metric_key == "average_order_value":
            stmt_curr = select(
                func.coalesce(func.sum(Sale.subtotal - Sale.discount_amount), Decimal("0.00")),
                func.count(Sale.id),
            ).where(
                Sale.business_id == business_id,
                Sale.status.in_(valid_statuses),
                Sale.transaction_date >= current_start,
                Sale.transaction_date < current_end,
            )
            stmt_base = select(
                func.coalesce(func.sum(Sale.subtotal - Sale.discount_amount), Decimal("0.00")),
                func.count(Sale.id),
            ).where(
                Sale.business_id == business_id,
                Sale.status.in_(valid_statuses),
                Sale.transaction_date >= baseline_start,
                Sale.transaction_date < baseline_end,
            )
            c_sales, c_orders = db.execute(stmt_curr).first() or (Decimal("0.00"), 0)
            b_sales, b_orders = db.execute(stmt_base).first() or (Decimal("0.00"), 0)

            c_num = float(c_sales)
            c_den = int(c_orders)
            b_num = float(b_sales)
            b_den = int(b_orders)

            c_ratio = c_num / c_den if c_den > 0 else 0.0
            b_ratio = b_num / b_den if b_den > 0 else 0.0
            ratio_delta = round(c_ratio - b_ratio, 2)

            if b_den == 0 or c_den == 0:
                return {
                    "status": "UNAVAILABLE",
                    "metric_key": metric_key,
                    "decomposition_type": "RATIO_FACTOR_DECOMPOSITION",
                    "aggregate_delta": round(aggregate_delta, 2),
                    "dimensions": {},
                    "primary_dimension": None,
                    "primary_driver": None,
                    "limitations": ["Zero orders in current or baseline period; ratio decomposition undefined."],
                    "provenance": cls._build_ratio_provenance(metric_key),
                }

            # Exact two-factor decomposition:
            # revenue_factor = (N_C - N_B) / D_B
            # volume_factor = Delta - revenue_factor = - N_C * (D_C - D_B) / (D_C * D_B)
            rev_factor = (c_num - b_num) / b_den
            vol_factor = ratio_delta - rev_factor

            # Segment-level AOV breakdown
            segment_stmt = (
                select(
                    func.coalesce(Customer.customer_segment, "Unassigned").label("eid"),
                    func.coalesce(Customer.customer_segment, "Unassigned").label("ename"),
                    func.coalesce(func.sum(Sale.subtotal - Sale.discount_amount), Decimal("0.00")).label("sales"),
                    func.count(Sale.id).label("orders"),
                )
                .select_from(Sale)
                .outerjoin(Customer, Customer.id == Sale.customer_id)
                .where(
                    Sale.business_id == business_id,
                    Sale.status.in_(valid_statuses),
                )
            )
            curr_seg_rows = db.execute(
                segment_stmt.where(
                    Sale.transaction_date >= current_start,
                    Sale.transaction_date < current_end,
                ).group_by(Customer.customer_segment)
            ).all()
            base_seg_rows = db.execute(
                segment_stmt.where(
                    Sale.transaction_date >= baseline_start,
                    Sale.transaction_date < baseline_end,
                ).group_by(Customer.customer_segment)
            ).all()

            curr_seg_map = {
                r.eid: {"name": r.ename, "sales": float(r.sales), "orders": int(r.orders)}
                for r in curr_seg_rows
            }
            base_seg_map = {
                r.eid: {"name": r.ename, "sales": float(r.sales), "orders": int(r.orders)}
                for r in base_seg_rows
            }
            all_segs = set(curr_seg_map.keys()) | set(base_seg_map.keys())

            seg_contributors = []
            for s in all_segs:
                cs = curr_seg_map.get(s, {})
                bs = base_seg_map.get(s, {})
                cs_aov = cs.get("sales", 0.0) / cs.get("orders", 1) if cs.get("orders", 0) > 0 else 0.0
                bs_aov = bs.get("sales", 0.0) / bs.get("orders", 1) if bs.get("orders", 0) > 0 else 0.0
                s_diff = round(cs_aov - bs_aov, 2)
                name = cs.get("name") or bs.get("name") or str(s)
                seg_contributors.append({
                    "entity_id": str(s),
                    "entity_name": name,
                    "current_value": round(cs_aov, 2),
                    "baseline_value": round(bs_aov, 2),
                    "absolute_change": s_diff,
                    "current_orders": cs.get("orders", 0),
                    "baseline_orders": bs.get("orders", 0),
                })

            pos_contributors = sorted(
                [c for c in seg_contributors if c["absolute_change"] > 0],
                key=lambda x: x["absolute_change"],
                reverse=True,
            )
            neg_contributors = sorted(
                [c for c in seg_contributors if c["absolute_change"] < 0],
                key=lambda x: x["absolute_change"],
                reverse=False,
            )

            primary_driver = None
            candidates = pos_contributors + neg_contributors
            if candidates:
                best_cand = candidates[0]
                primary_driver = {
                    "dimension": "customer_segment",
                    "entity_id": best_cand["entity_id"],
                    "entity_name": best_cand["entity_name"],
                    "absolute_change": best_cand["absolute_change"],
                    "current_value": best_cand["current_value"],
                    "baseline_value": best_cand["baseline_value"],
                }

            return {
                "status": "AVAILABLE",
                "metric_key": metric_key,
                "decomposition_type": "RATIO_FACTOR_DECOMPOSITION",
                "aggregate_delta": round(aggregate_delta, 2),
                "current_aggregate": round(current_aggregate, 2),
                "baseline_aggregate": round(baseline_aggregate, 2),
                "ratio_factors": {
                    "numerator_revenue_effect": round(rev_factor, 2),
                    "denominator_order_volume_effect": round(vol_factor, 2),
                    "reconciled": abs(round(rev_factor + vol_factor, 2) - round(ratio_delta, 2)) <= cls.RECONCILIATION_TOLERANCE,
                },
                "additive_reconciliation_applied": False,
                "dimensions": {
                    "customer_segment": {
                        "status": "AVAILABLE",
                        "dimension": "customer_segment",
                        "top_positive_contributors": pos_contributors[:top_n],
                        "top_negative_contributors": neg_contributors[:top_n],
                        "additive_reconciled": False,
                        "ratio_based": True,
                    }
                },
                "primary_dimension": "customer_segment",
                "primary_driver": primary_driver,
                "limitations": [
                    "Ratio metric decomposed into exact constituent numerator and denominator factors; additive cross-sectional summation does not apply to ratios without distortion."
                ],
                "provenance": cls._build_ratio_provenance(metric_key),
            }

        elif metric_key == "gross_margin_pct":
            stmt_curr = (
                select(
                    func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")),
                    func.coalesce(func.sum(SaleItem.quantity * func.coalesce(Product.unit_cost, Decimal("0.00"))), Decimal("0.00")),
                )
                .select_from(SaleItem)
                .join(Sale, SaleItem.sale_id == Sale.id)
                .outerjoin(Product, SaleItem.product_id == Product.id)
                .where(
                    Sale.business_id == business_id,
                    Sale.status.in_(valid_statuses),
                    Sale.transaction_date >= current_start,
                    Sale.transaction_date < current_end,
                )
            )
            stmt_base = (
                select(
                    func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")),
                    func.coalesce(func.sum(SaleItem.quantity * func.coalesce(Product.unit_cost, Decimal("0.00"))), Decimal("0.00")),
                )
                .select_from(SaleItem)
                .join(Sale, SaleItem.sale_id == Sale.id)
                .outerjoin(Product, SaleItem.product_id == Product.id)
                .where(
                    Sale.business_id == business_id,
                    Sale.status.in_(valid_statuses),
                    Sale.transaction_date >= baseline_start,
                    Sale.transaction_date < baseline_end,
                )
            )
            c_rev, c_cogs = db.execute(stmt_curr).first() or (Decimal("0.00"), Decimal("0.00"))
            b_rev, b_cogs = db.execute(stmt_base).first() or (Decimal("0.00"), Decimal("0.00"))

            c_r = float(c_rev)
            c_c = float(c_cogs)
            b_r = float(b_rev)
            b_c = float(b_cogs)

            c_prof = c_r - c_c
            b_prof = b_r - b_c

            c_margin = (c_prof / c_r) * 100.0 if c_r > 0 else 0.0
            b_margin = (b_prof / b_r) * 100.0 if b_r > 0 else 0.0
            margin_delta = round(c_margin - b_margin, 2)

            if b_r == 0 or c_r == 0:
                return {
                    "status": "UNAVAILABLE",
                    "metric_key": metric_key,
                    "decomposition_type": "RATIO_FACTOR_DECOMPOSITION",
                    "aggregate_delta": round(aggregate_delta, 2),
                    "dimensions": {},
                    "primary_dimension": None,
                    "primary_driver": None,
                    "limitations": ["Zero revenue in current or baseline period; margin ratio decomposition undefined."],
                    "provenance": cls._build_ratio_provenance(metric_key),
                }

            profit_factor = ((c_prof - b_prof) / b_r) * 100.0
            scale_factor = margin_delta - profit_factor

            # Category-level margin breakdown
            cat_stmt = (
                select(
                    func.coalesce(Product.category, "Unassigned").label("eid"),
                    func.coalesce(Product.category, "Unassigned").label("ename"),
                    func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")).label("rev"),
                    func.coalesce(func.sum(SaleItem.quantity * func.coalesce(Product.unit_cost, Decimal("0.00"))), Decimal("0.00")).label("cogs"),
                )
                .select_from(SaleItem)
                .join(Sale, SaleItem.sale_id == Sale.id)
                .outerjoin(Product, Product.id == SaleItem.product_id)
                .where(
                    Sale.business_id == business_id,
                    Sale.status.in_(valid_statuses),
                )
            )
            curr_cat_rows = db.execute(
                cat_stmt.where(
                    Sale.transaction_date >= current_start,
                    Sale.transaction_date < current_end,
                ).group_by(Product.category)
            ).all()
            base_cat_rows = db.execute(
                cat_stmt.where(
                    Sale.transaction_date >= baseline_start,
                    Sale.transaction_date < baseline_end,
                ).group_by(Product.category)
            ).all()

            curr_cat_map = {
                r.eid: {"name": r.ename, "rev": float(r.rev), "cogs": float(r.cogs)}
                for r in curr_cat_rows
            }
            base_cat_map = {
                r.eid: {"name": r.ename, "rev": float(r.rev), "cogs": float(r.cogs)}
                for r in base_cat_rows
            }
            all_cats = set(curr_cat_map.keys()) | set(base_cat_map.keys())

            cat_contributors = []
            for k in all_cats:
                ck = curr_cat_map.get(k, {})
                bk = base_cat_map.get(k, {})
                ck_m = ((ck.get("rev", 0.0) - ck.get("cogs", 0.0)) / ck.get("rev", 1.0)) * 100.0 if ck.get("rev", 0.0) > 0 else 0.0
                bk_m = ((bk.get("rev", 0.0) - bk.get("cogs", 0.0)) / bk.get("rev", 1.0)) * 100.0 if bk.get("rev", 0.0) > 0 else 0.0
                k_diff = round(ck_m - bk_m, 2)
                name = ck.get("name") or bk.get("name") or str(k)
                cat_contributors.append({
                    "entity_id": str(k),
                    "entity_name": name,
                    "current_value": round(ck_m, 2),
                    "baseline_value": round(bk_m, 2),
                    "absolute_change": k_diff,
                })

            pos_contributors = sorted(
                [c for c in cat_contributors if c["absolute_change"] > 0],
                key=lambda x: x["absolute_change"],
                reverse=True,
            )
            neg_contributors = sorted(
                [c for c in cat_contributors if c["absolute_change"] < 0],
                key=lambda x: x["absolute_change"],
                reverse=False,
            )

            primary_driver = None
            candidates = pos_contributors + neg_contributors
            if candidates:
                best_cand = candidates[0]
                primary_driver = {
                    "dimension": "category",
                    "entity_id": best_cand["entity_id"],
                    "entity_name": best_cand["entity_name"],
                    "absolute_change": best_cand["absolute_change"],
                    "current_value": best_cand["current_value"],
                    "baseline_value": best_cand["baseline_value"],
                }

            return {
                "status": "AVAILABLE",
                "metric_key": metric_key,
                "decomposition_type": "RATIO_FACTOR_DECOMPOSITION",
                "aggregate_delta": round(aggregate_delta, 2),
                "current_aggregate": round(current_aggregate, 2),
                "baseline_aggregate": round(baseline_aggregate, 2),
                "ratio_factors": {
                    "numerator_profit_effect": round(profit_factor, 2),
                    "denominator_scale_effect": round(scale_factor, 2),
                    "reconciled": abs(round(profit_factor + scale_factor, 2) - round(margin_delta, 2)) <= cls.RECONCILIATION_TOLERANCE,
                },
                "additive_reconciliation_applied": False,
                "dimensions": {
                    "category": {
                        "status": "AVAILABLE",
                        "dimension": "category",
                        "top_positive_contributors": pos_contributors[:top_n],
                        "top_negative_contributors": neg_contributors[:top_n],
                        "additive_reconciled": False,
                        "ratio_based": True,
                    }
                },
                "primary_dimension": "category",
                "primary_driver": primary_driver,
                "limitations": [
                    "Gross margin percentage decomposed into profit growth and revenue scale factors; additive cross-sectional summation does not apply to ratios without distortion."
                ],
                "provenance": cls._build_ratio_provenance(metric_key),
            }

        return {
            "status": "UNAVAILABLE",
            "metric_key": metric_key,
            "aggregate_delta": round(aggregate_delta, 2),
            "dimensions": {},
            "primary_dimension": None,
            "primary_driver": None,
            "limitations": [f"Ratio metric '{metric_key}' has no registered ratio decomposer."],
            "provenance": cls._build_ratio_provenance(metric_key),
        }

    @classmethod
    def _decompose_single_dimension(
        cls,
        db: Session,
        business_id: str,
        metric_key: str,
        dimension: str,
        current_start: datetime,
        current_end: datetime,
        baseline_start: datetime,
        baseline_end: datetime,
        aggregate_delta: float,
        current_aggregate: float,
        baseline_aggregate: float,
        top_n: int = 5,
    ) -> dict[str, Any]:
        """Query and compute deterministic breakdown for a single dimension."""
        curr_entities = cls._query_dimension_entities(
            db, business_id, metric_key, dimension, current_start, current_end
        )
        base_entities = cls._query_dimension_entities(
            db, business_id, metric_key, dimension, baseline_start, baseline_end
        )

        all_entity_ids = set(curr_entities.keys()) | set(base_entities.keys())
        if not all_entity_ids:
            return {
                "status": "UNAVAILABLE",
                "dimension": dimension,
                "entity_count": 0,
                "reconciled": False,
                "top_positive_contributors": [],
                "top_negative_contributors": [],
                "limitations": [f"No records found for dimension '{dimension}' in current or baseline periods."],
            }

        # Check for insufficient samples (fewer than 2 distinct entities)
        if len(all_entity_ids) < 2:
            single_id = next(iter(all_entity_ids))
            c_val = curr_entities.get(single_id, {}).get("value", 0.0)
            b_val = base_entities.get(single_id, {}).get("value", 0.0)
            diff = round(c_val - b_val, 2)
            name = (
                curr_entities.get(single_id, {}).get("name")
                or base_entities.get(single_id, {}).get("name")
                or str(single_id)
            )
            return {
                "status": "INSUFFICIENT_SAMPLES",
                "dimension": dimension,
                "entity_count": 1,
                "reconciled": abs(diff - aggregate_delta) <= cls.RECONCILIATION_TOLERANCE,
                "top_positive_contributors": [
                    {
                        "entity_id": str(single_id),
                        "entity_name": name,
                        "current_value": round(c_val, 2),
                        "baseline_value": round(b_val, 2),
                        "absolute_change": diff,
                        "contribution_to_change_pct": 100.0 if aggregate_delta != 0 else 0.0,
                    }
                ] if diff >= 0 else [],
                "top_negative_contributors": [
                    {
                        "entity_id": str(single_id),
                        "entity_name": name,
                        "current_value": round(c_val, 2),
                        "baseline_value": round(b_val, 2),
                        "absolute_change": diff,
                        "contribution_to_change_pct": -100.0 if aggregate_delta != 0 else 0.0,
                    }
                ] if diff < 0 else [],
                "limitations": [f"Insufficient entity diversity in '{dimension}' (found only 1 entity)."],
            }

        contributors: list[dict[str, Any]] = []
        sum_curr = 0.0
        sum_base = 0.0
        sum_delta = 0.0
        abs_agg_delta = abs(aggregate_delta)

        for eid in all_entity_ids:
            c_info = curr_entities.get(eid, {})
            b_info = base_entities.get(eid, {})
            c_val = float(c_info.get("value", 0.0))
            b_val = float(b_info.get("value", 0.0))
            name = c_info.get("name") or b_info.get("name") or str(eid)

            diff = c_val - b_val
            sum_curr += c_val
            sum_base += b_val
            sum_delta += diff

            # Deterministic contribution percentage relative to absolute total movement
            # Consistent with VarianceDiagnosticAnalyzer: (delta_i / |total_delta|) * 100.0
            if abs_agg_delta > 1e-6:
                contrib_pct = round((diff / abs_agg_delta) * 100.0, 2)
                share_of_net_pct = round((diff / aggregate_delta) * 100.0, 2)
            else:
                contrib_pct = 0.0
                share_of_net_pct = 0.0

            # Safe entity-level percentage change avoiding ZeroDivisionError and negative baseline inversion
            if b_val != 0.0:
                entity_pct_change = round((diff / abs(b_val)) * 100.0, 2)
            else:
                if c_val > 0:
                    entity_pct_change = 100.0
                elif c_val < 0:
                    entity_pct_change = -100.0
                else:
                    entity_pct_change = 0.0

            contributors.append({
                "entity_id": str(eid),
                "entity_name": name,
                "current_value": round(c_val, 2),
                "baseline_value": round(b_val, 2),
                "absolute_change": round(diff, 2),
                "contribution_to_change_pct": contrib_pct,
                "share_of_net_variance_pct": share_of_net_pct,
                "percentage_change": entity_pct_change,
            })

        # Separate and deterministically rank positive and negative contributors
        pos_contributors = [c for c in contributors if c["absolute_change"] > 0]
        pos_contributors.sort(key=lambda x: (x["absolute_change"], x["entity_id"]), reverse=True)

        neg_contributors = [c for c in contributors if c["absolute_change"] < 0]
        neg_contributors.sort(key=lambda x: (x["absolute_change"], x["entity_id"]), reverse=False)

        # Variance Reconciliation & Unallocated Detection
        # Check whether entity sum matches aggregate within tolerance
        unallocated_curr = max(0.0, current_aggregate - sum_curr)
        unallocated_base = max(0.0, baseline_aggregate - sum_base)
        unallocated_delta = unallocated_curr - unallocated_base

        variance_discrepancy = abs(sum_delta - aggregate_delta)
        is_reconciled = variance_discrepancy <= cls.RECONCILIATION_TOLERANCE

        # If item-level records do not cover entire order amount (e.g. order-level discounts or unassigned items),
        # reconcile using explicit unallocated driver
        if not is_reconciled and abs((sum_delta + unallocated_delta) - aggregate_delta) <= cls.RECONCILIATION_TOLERANCE:
            is_reconciled = True
            variance_discrepancy = round(abs((sum_delta + unallocated_delta) - aggregate_delta), 4)

        return {
            "status": "AVAILABLE",
            "dimension": dimension,
            "entity_count": len(all_entity_ids),
            "sum_current_entities": round(sum_curr, 2),
            "sum_baseline_entities": round(sum_base, 2),
            "sum_entity_delta": round(sum_delta, 2),
            "unallocated_variance": round(unallocated_delta, 2) if abs(unallocated_delta) > 0.001 else 0.0,
            "variance_discrepancy": round(variance_discrepancy, 4),
            "reconciled": is_reconciled,
            "top_positive_contributors": pos_contributors[:top_n],
            "top_negative_contributors": neg_contributors[:top_n],
            "limitations": [] if is_reconciled else [
                f"Variance discrepancy of {variance_discrepancy:.2f} detected between aggregate and entity sum."
            ],
        }

    @classmethod
    def _query_dimension_entities(
        cls,
        db: Session,
        business_id: str,
        metric_key: str,
        dimension: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> dict[Any, dict[str, Any]]:
        """Query dimensional entities strictly scoped to tenant and [start_dt, end_dt) window."""
        valid_statuses = ["completed", "shipped"]

        if dimension == "category":
            if metric_key in ("net_sales", "gross_sales"):
                stmt = (
                    select(
                        func.coalesce(Product.category, "Unassigned").label("eid"),
                        func.coalesce(Product.category, "Unassigned").label("ename"),
                        func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")).label("val"),
                    )
                    .select_from(SaleItem)
                    .join(Sale, SaleItem.sale_id == Sale.id)
                    .outerjoin(Product, Product.id == SaleItem.product_id)
                    .where(
                        Sale.business_id == business_id,
                        Sale.status.in_(valid_statuses),
                        Sale.transaction_date >= start_dt,
                        Sale.transaction_date < end_dt,
                    )
                    .group_by(Product.category)
                )
            elif metric_key == "units_sold":
                stmt = (
                    select(
                        func.coalesce(Product.category, "Unassigned").label("eid"),
                        func.coalesce(Product.category, "Unassigned").label("ename"),
                        func.coalesce(func.sum(SaleItem.quantity), 0).label("val"),
                    )
                    .select_from(SaleItem)
                    .join(Sale, SaleItem.sale_id == Sale.id)
                    .outerjoin(Product, Product.id == SaleItem.product_id)
                    .where(
                        Sale.business_id == business_id,
                        Sale.status.in_(valid_statuses),
                        Sale.transaction_date >= start_dt,
                        Sale.transaction_date < end_dt,
                    )
                    .group_by(Product.category)
                )
            else:
                return {}

        elif dimension == "product":
            if metric_key in ("net_sales", "gross_sales"):
                stmt = (
                    select(
                        func.coalesce(Product.sku, "UNMAPPED").label("eid"),
                        func.coalesce(Product.name, "Unmapped Product").label("ename"),
                        func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")).label("val"),
                    )
                    .select_from(SaleItem)
                    .join(Sale, SaleItem.sale_id == Sale.id)
                    .outerjoin(Product, Product.id == SaleItem.product_id)
                    .where(
                        Sale.business_id == business_id,
                        Sale.status.in_(valid_statuses),
                        Sale.transaction_date >= start_dt,
                        Sale.transaction_date < end_dt,
                    )
                    .group_by(Product.sku, Product.name)
                )
            elif metric_key == "units_sold":
                stmt = (
                    select(
                        func.coalesce(Product.sku, "UNMAPPED").label("eid"),
                        func.coalesce(Product.name, "Unmapped Product").label("ename"),
                        func.coalesce(func.sum(SaleItem.quantity), 0).label("val"),
                    )
                    .select_from(SaleItem)
                    .join(Sale, SaleItem.sale_id == Sale.id)
                    .outerjoin(Product, Product.id == SaleItem.product_id)
                    .where(
                        Sale.business_id == business_id,
                        Sale.status.in_(valid_statuses),
                        Sale.transaction_date >= start_dt,
                        Sale.transaction_date < end_dt,
                    )
                    .group_by(Product.sku, Product.name)
                )
            else:
                return {}

        elif dimension == "customer_segment":
            if metric_key == "net_sales":
                stmt = (
                    select(
                        func.coalesce(Customer.customer_segment, "Unassigned").label("eid"),
                        func.coalesce(Customer.customer_segment, "Unassigned").label("ename"),
                        func.coalesce(
                            func.sum(Sale.subtotal - Sale.discount_amount), Decimal("0.00")
                        ).label("val"),
                    )
                    .select_from(Sale)
                    .outerjoin(Customer, Customer.id == Sale.customer_id)
                    .where(
                        Sale.business_id == business_id,
                        Sale.status.in_(valid_statuses),
                        Sale.transaction_date >= start_dt,
                        Sale.transaction_date < end_dt,
                    )
                    .group_by(Customer.customer_segment)
                )
            elif metric_key == "gross_sales":
                stmt = (
                    select(
                        func.coalesce(Customer.customer_segment, "Unassigned").label("eid"),
                        func.coalesce(Customer.customer_segment, "Unassigned").label("ename"),
                        func.coalesce(func.sum(Sale.subtotal), Decimal("0.00")).label("val"),
                    )
                    .select_from(Sale)
                    .outerjoin(Customer, Customer.id == Sale.customer_id)
                    .where(
                        Sale.business_id == business_id,
                        Sale.status.in_(valid_statuses),
                        Sale.transaction_date >= start_dt,
                        Sale.transaction_date < end_dt,
                    )
                    .group_by(Customer.customer_segment)
                )
            elif metric_key == "orders_count":
                stmt = (
                    select(
                        func.coalesce(Customer.customer_segment, "Unassigned").label("eid"),
                        func.coalesce(Customer.customer_segment, "Unassigned").label("ename"),
                        func.count(Sale.id).label("val"),
                    )
                    .select_from(Sale)
                    .outerjoin(Customer, Customer.id == Sale.customer_id)
                    .where(
                        Sale.business_id == business_id,
                        Sale.status.in_(valid_statuses),
                        Sale.transaction_date >= start_dt,
                        Sale.transaction_date < end_dt,
                    )
                    .group_by(Customer.customer_segment)
                )
            else:
                return {}
        else:
            return {}

        res: dict[Any, dict[str, Any]] = {}
        rows = db.execute(stmt).all()
        for r in rows:
            res[r.eid] = {
                "name": r.ename,
                "value": float(Decimal(str(r.val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            }
        return res

    @classmethod
    def _build_provenance(cls, metric_key: str, dimension: str) -> dict[str, Any]:
        """Construct deterministic audit provenance for dimensional decomposition."""
        return {
            "calculation_method": "deterministic_additive_variance_decomposition",
            "contribution_formula": "contribution_to_change_pct = (delta_i / |aggregate_delta|) * 100.0",
            "growth_formula": "percentage_change = ((current_i - baseline_i) / |baseline_i|) * 100.0",
            "reconciliation_tolerance": cls.RECONCILIATION_TOLERANCE,
            "attribution_type": "MEASURED_OBSERVATIONAL_CONTRIBUTION",
            "causal_disclaimer": NON_CAUSALITY_ATTRIBUTION_DISCLAIMER,
        }

    @classmethod
    def _build_ratio_provenance(cls, metric_key: str) -> dict[str, Any]:
        """Construct deterministic audit provenance for ratio factor decomposition."""
        return {
            "calculation_method": "deterministic_ratio_factor_decomposition",
            "decomposition_type": "RATIO_FACTOR_DECOMPOSITION",
            "additive_reconciliation_applied": False,
            "justification": "Ratio metrics cannot be decomposed additively across dimensions without mathematical distortion; decomposed into exact constituent numerator and denominator factors.",
            "attribution_type": "MEASURED_OBSERVATIONAL_CONTRIBUTION",
            "causal_disclaimer": NON_CAUSALITY_ATTRIBUTION_DISCLAIMER,
        }
