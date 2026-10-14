"""Deterministic detection engine for Continuous Intelligence (Phase 29).

Executes period-over-period metric comparisons, Tukey IQR anomaly evaluations,
minimum sample size quality gating, and multi-factor deterministic prioritization.
Never uses LLMs for numerical arithmetic or anomaly determination.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.continuous.schemas import (
    ChangeType,
    EvidenceQualityGrade,
    FindingSeverity,
    MetricShiftObservation,
)
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem

NON_CAUSALITY_DISCLAIMER = (
    "Observed metric variation and statistical deviations reflect historical observational data "
    "and do not constitute proven causal attribution. External factors, catalog changes, "
    "and reporting lags may contribute. Final operational decisions require human review."
)


def compute_finding_fingerprint(
    business_id: str,
    metric_key: str,
    entity_type: str = "business",
    entity_id: str = "all",
) -> str:
    """Compute deterministic SHA-256 fingerprint identifying the metric finding target."""
    raw = f"{business_id}:{metric_key}:{entity_type}:{entity_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ContinuousDetectionEngine:
    """Deterministic detection and prioritization algorithms."""

    SUPPORTED_METRICS: ClassVar[list[str]] = [
        "net_sales",
        "gross_sales",
        "orders_count",
        "average_order_value",
        "units_sold",
        "gross_margin_pct",
        "stockout_risk_items",
    ]

    @classmethod
    def evaluate_metric_for_window(
        cls,
        db: Session,
        business_id: str,
        metric_key: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> tuple[float, int]:
        """
        Deterministically calculate a single metric value and row/transaction count
        strictly scoped to business_id and the specified time window.
        """
        valid_statuses = ["completed", "shipped"]

        if metric_key == "net_sales":
            stmt = select(
                func.coalesce(func.sum(Sale.subtotal - Sale.discount_amount), Decimal("0.00")),
                func.count(Sale.id),
            ).where(
                Sale.business_id == business_id,
                Sale.status.in_(valid_statuses),
                Sale.transaction_date >= start_dt,
                Sale.transaction_date < end_dt,
            )
            val, count = db.execute(stmt).first() or (Decimal("0.00"), 0)
            return float(val), int(count)

        if metric_key == "gross_sales":
            stmt = select(
                func.coalesce(func.sum(Sale.subtotal), Decimal("0.00")),
                func.count(Sale.id),
            ).where(
                Sale.business_id == business_id,
                Sale.status.in_(valid_statuses),
                Sale.transaction_date >= start_dt,
                Sale.transaction_date < end_dt,
            )
            val, count = db.execute(stmt).first() or (Decimal("0.00"), 0)
            return float(val), int(count)

        if metric_key == "orders_count":
            stmt = select(func.count(Sale.id)).where(
                Sale.business_id == business_id,
                Sale.status.in_(valid_statuses),
                Sale.transaction_date >= start_dt,
                Sale.transaction_date < end_dt,
            )
            count = db.execute(stmt).scalar() or 0
            return float(count), int(count)

        if metric_key == "average_order_value":
            stmt = select(
                func.coalesce(func.sum(Sale.subtotal - Sale.discount_amount), Decimal("0.00")),
                func.count(Sale.id),
            ).where(
                Sale.business_id == business_id,
                Sale.status.in_(valid_statuses),
                Sale.transaction_date >= start_dt,
                Sale.transaction_date < end_dt,
            )
            total_net, orders = db.execute(stmt).first() or (Decimal("0.00"), 0)
            aov = float(total_net) / float(orders) if orders > 0 else 0.0
            return round(aov, 2), int(orders)

        if metric_key == "units_sold":
            stmt = (
                select(
                    func.coalesce(func.sum(SaleItem.quantity), 0),
                    func.count(SaleItem.id),
                )
                .join(Sale, SaleItem.sale_id == Sale.id)
                .where(
                    Sale.business_id == business_id,
                    Sale.status.in_(valid_statuses),
                    Sale.transaction_date >= start_dt,
                    Sale.transaction_date < end_dt,
                )
            )
            units, count = db.execute(stmt).first() or (0, 0)
            return float(units), int(count)

        if metric_key == "gross_margin_pct":
            # Net sales vs COGS
            stmt = (
                select(
                    func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")),
                    func.coalesce(
                        func.sum(SaleItem.quantity * func.coalesce(Product.unit_cost, Decimal("0.00"))),
                        Decimal("0.00"),
                    ),
                )
                .join(Sale, SaleItem.sale_id == Sale.id)
                .join(Product, SaleItem.product_id == Product.id)
                .where(
                    Sale.business_id == business_id,
                    Sale.status.in_(valid_statuses),
                    Sale.transaction_date >= start_dt,
                    Sale.transaction_date < end_dt,
                )
            )
            revenue, cogs = db.execute(stmt).first() or (Decimal("0.00"), Decimal("0.00"))
            rev_f = float(revenue)
            cogs_f = float(cogs)
            if rev_f > 0:
                margin_pct = ((rev_f - cogs_f) / rev_f) * 100.0
            else:
                margin_pct = 0.0
            return round(margin_pct, 2), 1

        if metric_key == "stockout_risk_items":
            stmt = select(func.count(Inventory.id)).where(
                Inventory.business_id == business_id,
                Inventory.stock_quantity <= func.coalesce(Inventory.reorder_threshold, 0),
            )
            count = db.execute(stmt).scalar() or 0
            return float(count), int(count)

        return 0.0, 0

    @classmethod
    def calculate_priority_scores(
        cls,
        metric_key: str,
        current_val: float,
        baseline_val: float,
        rel_change_pct: float,
        is_anomaly: bool,
        evidence_quality: EvidenceQualityGrade,
    ) -> tuple[float, float, float, FindingSeverity]:
        """
        Compute deterministic multi-factor priority:
        (business_impact, confidence, urgency) -> FindingSeverity
        """
        # 1. Business Impact (0.0 to 1.0)
        abs_delta = abs(current_val - baseline_val)
        if metric_key in ("net_sales", "gross_sales"):
            impact_score = min(1.0, max(0.1, abs_delta / 10000.0))
        elif metric_key == "gross_margin_pct":
            impact_score = min(1.0, max(0.1, abs_delta / 25.0))
        elif metric_key == "stockout_risk_items":
            impact_score = min(1.0, max(0.2, abs_delta / 20.0))
        else:
            impact_score = min(1.0, max(0.1, abs(rel_change_pct) / 50.0))

        # 2. Confidence Score (0.0 to 1.0)
        if evidence_quality == EvidenceQualityGrade.HIGH:
            base_conf = 0.85 if is_anomaly else 0.75
        elif evidence_quality == EvidenceQualityGrade.MEDIUM:
            base_conf = 0.70 if is_anomaly else 0.60
        else:
            base_conf = 0.40
        confidence_score = min(1.0, base_conf)

        # 3. Urgency Score (0.0 to 1.0)
        # Drops in revenue/margin or spikes in stockouts have higher urgency
        is_negative_shift = False
        if metric_key in ("net_sales", "gross_sales", "orders_count", "average_order_value", "units_sold", "gross_margin_pct"):
            if current_val < baseline_val:
                is_negative_shift = True
        elif metric_key == "stockout_risk_items" and current_val > baseline_val:
            is_negative_shift = True

        if is_negative_shift:
            urgency_score = min(1.0, 0.60 + 0.40 * impact_score)
        else:
            urgency_score = max(0.20, 0.40 * impact_score)

        # 4. Severity Assignment
        if urgency_score >= 0.80 and impact_score >= 0.70 and confidence_score >= 0.70:
            severity = FindingSeverity.CRITICAL
        elif urgency_score >= 0.60 and impact_score >= 0.50:
            severity = FindingSeverity.HIGH
        elif impact_score >= 0.30 or urgency_score >= 0.50:
            severity = FindingSeverity.MEDIUM
        else:
            severity = FindingSeverity.LOW

        return (
            round(impact_score, 2),
            round(confidence_score, 2),
            round(urgency_score, 2),
            severity,
        )

    @classmethod
    def evaluate_metric_shift(
        cls,
        db: Session,
        business_id: str,
        metric_key: str,
        lookback_days: int = 30,
        baseline_days: int = 30,
        min_relative_change: float = 0.15,
        anomaly_iqr_multiplier: float = 1.5,
        reference_time: datetime | None = None,
    ) -> MetricShiftObservation | None:
        """
        Evaluate whether a metric exhibits a statistically or operationally meaningful shift.
        Returns a MetricShiftObservation if thresholds are breached, or None if normal.
        """
        now = reference_time or datetime.now(UTC)
        current_end = now
        current_start = current_end - timedelta(days=lookback_days)

        baseline_end = current_start
        baseline_start = baseline_end - timedelta(days=baseline_days)

        # 1. Query Current Period Value
        current_val, current_count = cls.evaluate_metric_for_window(
            db, business_id, metric_key, current_start, current_end
        )

        # 2. Query Prior Baseline Period Value
        baseline_val, baseline_count = cls.evaluate_metric_for_window(
            db, business_id, metric_key, baseline_start, baseline_end
        )

        # 3. Query Multi-Period Historical Series for Statistical Baseline and Fences
        # Collect up to 6 historical periods of length baseline_days prior to current_start
        historical_values: list[float] = [baseline_val]
        for p in range(1, 6):
            p_end = current_start - timedelta(days=p * baseline_days)
            p_start = p_end - timedelta(days=baseline_days)
            p_val, _ = cls.evaluate_metric_for_window(db, business_id, metric_key, p_start, p_end)
            historical_values.append(p_val)

        valid_hist = [v for v in historical_values if not np.isnan(v) and not np.isinf(v)]
        n_periods = len(valid_hist)

        # 4. Evidence Quality Gate based on history and observations
        if current_count == 0 and baseline_count == 0:
            # Entirely empty history: do not fabricate false findings
            return None

        if n_periods >= 4 and (current_count > 0 or baseline_count > 0):
            evidence_quality = EvidenceQualityGrade.HIGH
        elif n_periods >= 2:
            evidence_quality = EvidenceQualityGrade.MEDIUM
        else:
            evidence_quality = EvidenceQualityGrade.LOW

        # 5. Arithmetic Delta and Relative Percentage
        delta_val = current_val - baseline_val
        if baseline_val != 0.0:
            rel_change_pct = (delta_val / abs(baseline_val)) * 100.0
        else:
            if current_val > 0:
                rel_change_pct = 100.0
            elif current_val < 0:
                rel_change_pct = -100.0
            else:
                rel_change_pct = 0.0

        # 6. Statistical Fences via Tukey IQR with Zero-IQR / Constant-Series Fallback
        arr = np.array(valid_hist, dtype=float)
        q25, q75 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75))
        iqr = q75 - q25
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr))

        is_statistical_anomaly = False
        zero_iqr = bool(iqr <= 1e-9)
        fallback_method: str | None = None

        if n_periods >= 4:
            if not zero_iqr:
                lower_fence = q25 - anomaly_iqr_multiplier * iqr
                upper_fence = q75 + anomaly_iqr_multiplier * iqr
                if current_val < lower_fence or current_val > upper_fence:
                    is_statistical_anomaly = True
            elif std_val > 1e-6:
                # Zero IQR due to concentrated median, but non-zero standard deviation:
                # Fall back to 2.5-sigma Gaussian fence
                fallback_method = "std_dev_fallback_2.5_sigma"
                lower_fence = mean_val - 2.5 * std_val
                upper_fence = mean_val + 2.5 * std_val
                if current_val < lower_fence or current_val > upper_fence:
                    is_statistical_anomaly = True
            else:
                # Constant baseline series across all historical periods (std_val == 0)
                fallback_method = "constant_series_baseline"
                lower_fence = mean_val
                upper_fence = mean_val
                # Any significant divergence from a constant baseline is anomalous
                if abs(delta_val) > 1e-4 and (abs(rel_change_pct) / 100.0) >= min_relative_change:
                    is_statistical_anomaly = True
        else:
            lower_fence = q25
            upper_fence = q75

        # 7. Check if meaningful change condition is met
        abs_rel = abs(rel_change_pct) / 100.0
        is_meaningful_shift = abs_rel >= min_relative_change and abs(delta_val) > 1e-4

        if not is_statistical_anomaly and not is_meaningful_shift:
            # Normal metric movement within acceptable thresholds
            return None

        # 8. Determine Change Type
        if is_statistical_anomaly:
            change_type = ChangeType.STATISTICAL_ANOMALY
        else:
            change_type = ChangeType.TREND_SHIFT

        # 9. Priority & Severity
        impact_score, conf_score, urgency_score, severity = cls.calculate_priority_scores(
            metric_key=metric_key,
            current_val=current_val,
            baseline_val=baseline_val,
            rel_change_pct=rel_change_pct,
            is_anomaly=is_statistical_anomaly,
            evidence_quality=evidence_quality,
        )

        # 10. Human-readable Title & Summary (Deterministic, zero hallucination)
        metric_label = metric_key.replace("_", " ").title()
        direction_word = "increased" if delta_val > 0 else "decreased"
        if "sales" in metric_key or "value" in metric_key:
            unit_str = "USD"
        elif "orders" in metric_key:
            unit_str = "orders"
        elif "sold" in metric_key or "units" in metric_key:
            unit_str = "units"
        elif "items" in metric_key:
            unit_str = "items"
        elif "margin" in metric_key or "pct" in metric_key:
            unit_str = "%"
        else:
            unit_str = "units"

        title = f"{metric_label} {direction_word} by {abs(rel_change_pct):.1f}% over {lookback_days} days"

        if is_statistical_anomaly:
            boundary_breached = f"breached the lower fence ({lower_fence:.2f} {unit_str})" if current_val < lower_fence else f"breached the upper fence ({upper_fence:.2f} {unit_str})"
            summary = (
                f"{metric_label} observed at {current_val:.2f} {unit_str} in the current {lookback_days}-day period, "
                f"which is an anomaly that {boundary_breached} established across {n_periods} baseline periods "
                f"(prior baseline was {baseline_val:.2f} {unit_str}, delta of {delta_val:+.2f} {unit_str} / {rel_change_pct:+.1f}%)."
            )
        else:
            summary = (
                f"{metric_label} shifted from {baseline_val:.2f} {unit_str} to {current_val:.2f} {unit_str} "
                f"({delta_val:+.2f} {unit_str}, {rel_change_pct:+.1f}%) comparing the current {lookback_days}-day "
                f"window to the prior baseline period."
            )

        # 10. Dimensional Change Decomposition (Phase 29 Stage 2)
        from app.analytics.continuous.dimensional import DimensionalDecomposer
        dim_decomp = DimensionalDecomposer.decompose_metric_variance(
            db=db,
            business_id=business_id,
            metric_key=metric_key,
            current_start=current_start,
            current_end=current_end,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            aggregate_delta=delta_val,
            current_aggregate=current_val,
            baseline_aggregate=baseline_val,
        )

        if dim_decomp.get("primary_driver"):
            driver = dim_decomp["primary_driver"]
            contrib_prefix = (
                f"({driver['contribution_pct']:+.1f}% of change, "
                if driver.get("contribution_pct") is not None
                else "("
            )
            summary += (
                f" Primary contributor in {driver['dimension']}: {driver['entity_name']} "
                f"{contrib_prefix}delta {driver['absolute_change']:+.2f} {unit_str})."
            )

        calculation_details = {
            "current_period": {"start": current_start.isoformat(), "end": current_end.isoformat(), "value": current_val, "count": current_count},
            "baseline_period": {"start": baseline_start.isoformat(), "end": baseline_end.isoformat(), "value": baseline_val, "count": baseline_count},
            "historical_baseline": {
                "periods_sampled": n_periods,
                "values": valid_hist,
                "mean": round(mean_val, 2),
                "std": round(std_val, 2),
                "q25": round(q25, 2),
                "q75": round(q75, 2),
                "iqr": round(iqr, 2),
                "lower_fence": round(lower_fence, 2),
                "upper_fence": round(upper_fence, 2),
                "zero_iqr": zero_iqr,
                "fallback_method": fallback_method,
            },
            "statistical_anomaly": is_statistical_anomaly,
            "point_in_time_snapshot": metric_key == "stockout_risk_items",
            "dimensional_decomposition": dim_decomp,
        }

        provenance = {
            "metric_key": metric_key,
            "lookback_days": lookback_days,
            "baseline_days": baseline_days,
            "min_relative_change_threshold": min_relative_change,
            "iqr_multiplier": anomaly_iqr_multiplier,
            "zero_iqr_fallback": fallback_method,
            "disclaimer": NON_CAUSALITY_DISCLAIMER,
            "dimensional_provenance": dim_decomp.get("provenance"),
        }
        if dim_decomp.get("limitations"):
            provenance["dimensional_limitations"] = dim_decomp.get("limitations")

        return MetricShiftObservation(
            metric_key=metric_key,
            entity_type="business",
            entity_id="all",
            entity_name=None,
            change_type=change_type,
            title=title,
            summary=summary,
            current_value=current_val,
            baseline_value=baseline_val,
            delta_value=delta_val,
            relative_change_pct=round(rel_change_pct, 2),
            unit=unit_str,
            period_start=current_start,
            period_end=current_end,
            baseline_period_start=baseline_start,
            baseline_period_end=baseline_end,
            confidence_score=conf_score,
            business_impact_score=impact_score,
            urgency_score=urgency_score,
            severity=severity,
            evidence_quality=evidence_quality,
            calculation_details=calculation_details,
            provenance=provenance,
        )
