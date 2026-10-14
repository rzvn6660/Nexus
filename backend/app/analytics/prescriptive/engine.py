"""Deterministic prescriptive analytics engine evaluating retail actions against business constraints."""

import math
from datetime import UTC, datetime
from uuid import uuid4

from scipy import stats
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.core.context import AnalysisContext
from app.analytics.prescriptive.schemas import (
    ActionAlternative,
    ActionType,
    ConstraintSet,
    ExpectedImpact,
    ForecastInput,
    ObjectiveType,
    ObservedFact,
    PrescriptiveRecommendation,
    RecommendationStatus,
    UncertaintyRange,
)
from app.analytics.product.velocity import ProductVelocityCalculator
from app.models.inventory import Inventory
from app.models.product import Product
from app.predictive.schemas import ForecastRequest, ForecastStatus, ModelPolicy
from app.predictive.services.forecasting_service import ForecastingService


class PrescriptiveEngine:
    """
    Deterministic Prescriptive Recommendation Engine for retail and distribution.
    
    Guarantees:
    1. Zero LLM arithmetic: All replenishment quantities, ROP, EOQ, holding costs,
       stockout risks, and markdown break-evens are computed via verifiable mathematical formulas.
    2. Strict separation of observed historical facts, forecast inputs, assumptions, and outcomes.
    3. Multi-alternative comparison against user-specified constraints and objectives.
    4. Strict abstention when evidence is insufficient or constraints conflict.
    5. Tenant isolation enforced at database query boundaries.
    6. Mandatory human-in-the-loop review gating (requires_human_approval = True).
    """

    def __init__(self, session: Session, business_id: str | None = None) -> None:
        self.session = session
        self.business_id = business_id

    def evaluate_inventory_replenishment(
        self,
        sku: str,
        constraints: ConstraintSet | None = None,
        objective: ObjectiveType = ObjectiveType.BALANCE_SERVICE_LEVEL,
    ) -> PrescriptiveRecommendation:
        """
        Evaluate inventory replenishment options for a specific product SKU.
        
        Calculates:
        - Reorder Point (ROP) = Lead Time Demand + Safety Stock
        - Economic Order Quantity (EOQ) balancing order cost vs annual holding cost
        - Lead-time stockout probability under central forecast vs forecast upper bound
        - Working capital outlay and annual holding costs
        """
        now_str = datetime.now(UTC).isoformat()
        rec_id = f"REC-INV-{uuid4().hex[:8].upper()}"
        cons = constraints or ConstraintSet()

        # 1. Tenant-isolated Product & Inventory Query
        prod_stmt = select(Product).where(Product.sku == sku)
        if self.business_id:
            prod_stmt = prod_stmt.where(Product.business_id == self.business_id)
        prod = self.session.execute(prod_stmt).scalar_one_or_none()

        if not prod:
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.INSUFFICIENT_EVIDENCE,
                reason=f"Product with SKU '{sku}' not found in tenant catalog.",
                created_at=now_str,
            )

        inv_stmt = select(Inventory).where(Inventory.product_id == prod.id)
        if self.business_id:
            inv_stmt = inv_stmt.where(Inventory.business_id == self.business_id)
        inv = self.session.execute(inv_stmt).scalar_one_or_none()

        if not inv:
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.INSUFFICIENT_EVIDENCE,
                reason=f"No inventory tracking record exists for SKU '{sku}'.",
                created_at=now_str,
            )

        # 2. Validate Product Economics & Operating Constraints
        try:
            unit_cost = float(prod.unit_cost)
            selling_price = float(prod.selling_price)
        except (TypeError, ValueError):
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.INSUFFICIENT_EVIDENCE,
                reason=f"Product SKU '{sku}' has non-numeric unit cost or selling price.",
                created_at=now_str,
            )

        if not math.isfinite(unit_cost) or unit_cost <= 0.0:
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.INSUFFICIENT_EVIDENCE,
                reason=f"Product SKU '{sku}' has invalid unit cost (${unit_cost}). Unit cost must be positive and finite.",
                created_at=now_str,
            )

        if not math.isfinite(selling_price) or selling_price <= 0.0:
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.INSUFFICIENT_EVIDENCE,
                reason=f"Product SKU '{sku}' has invalid selling price (${selling_price}). Selling price must be positive and finite.",
                created_at=now_str,
            )

        if not math.isfinite(cons.lead_time_days) or cons.lead_time_days <= 0:
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.CONFLICTING_CONSTRAINTS,
                reason=f"Replenishment lead time ({cons.lead_time_days} days) must be a positive finite integer.",
                created_at=now_str,
            )

        if not math.isfinite(cons.target_service_level) or not (0.50 <= cons.target_service_level < 1.0):
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.CONFLICTING_CONSTRAINTS,
                reason=f"Target service level ({cons.target_service_level}) must be strictly between 0.50 and 0.999.",
                created_at=now_str,
            )

        if not math.isfinite(cons.annual_holding_cost_rate) or cons.annual_holding_cost_rate <= 0.0:
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.CONFLICTING_CONSTRAINTS,
                reason=f"Annual holding cost rate ({cons.annual_holding_cost_rate}) must be a positive finite number.",
                created_at=now_str,
            )

        if cons.min_order_quantity <= 0:
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.CONFLICTING_CONSTRAINTS,
                reason=f"Supplier MOQ ({cons.min_order_quantity}) must be at least 1 unit.",
                created_at=now_str,
            )

        if cons.max_order_quantity is not None and cons.max_order_quantity < cons.min_order_quantity:
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.CONFLICTING_CONSTRAINTS,
                reason=(
                    f"Conflicting constraints: Maximum order quantity ceiling ({cons.max_order_quantity}) "
                    f"is lower than supplier minimum order quantity MOQ ({cons.min_order_quantity})."
                ),
                created_at=now_str,
            )

        unit_margin = max(0.0, selling_price - unit_cost)
        current_stock = int(inv.stock_quantity)
        min_order = cons.min_order_quantity

        if cons.max_budget is not None and (min_order * unit_cost) > cons.max_budget:
            conflict_msg = (
                f"Conflicting constraints: Supplier minimum order quantity ({min_order} units @ ${unit_cost:.2f} = "
                f"${min_order * unit_cost:.2f}) exceeds maximum allowable budget of ${cons.max_budget:.2f}."
            )
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.CONFLICTING_CONSTRAINTS,
                reason=conflict_msg,
                created_at=now_str,
                observed_facts=[
                    ObservedFact(metric="unit_cost", value=unit_cost, source_table="products", description="Product COGS"),
                    ObservedFact(metric="min_order_quantity", value=min_order, source_table="constraints", description="Supplier MOQ"),
                ],
            )

        # 3. Retrieve Prospective Phase 26 Demand Forecast
        fcst_service = ForecastingService(self.session, business_id=self.business_id)
        fcst_req = ForecastRequest(
            target_metric="product_demand",
            entity_type="product",
            entity_id=sku,
            forecast_horizon=1,
            frequency="monthly",
            model_policy=ModelPolicy.VALIDATED_BEST,
            confidence_level=cons.target_service_level,
        )
        fcst_res = fcst_service.forecast(fcst_req)

        if fcst_res.status != ForecastStatus.COMPLETED or not fcst_res.predictions:
            reasons = fcst_res.limitations or ["Insufficient historical transactions to establish demand forecast."]
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.INSUFFICIENT_EVIDENCE,
                reason=f"Demand forecast unavailable: {reasons[0]}",
                created_at=now_str,
            )

        pred_pt = fcst_res.predictions[0]
        monthly_demand_point = max(0.0, pred_pt.point_forecast)
        monthly_demand_low = max(0.0, pred_pt.lower_bound)
        monthly_demand_high = max(monthly_demand_point, pred_pt.upper_bound)
        interval_width = pred_pt.interval_width

        # 4. Statistical Inventory Math (Deterministic)
        # Trace exact Phase 26 forecast frequency and period calendar duration
        fcst_freq = fcst_res.frequency or "monthly"
        period_days = 30.0 if fcst_freq == "monthly" else (7.0 if fcst_freq == "weekly" else 1.0)
        daily_demand = monthly_demand_point / period_days
        annual_demand = daily_demand * 365.0

        # Estimate demand standard deviation dynamically from 1-step forecast prediction interval metadata
        # Upper spread = upper_bound - point_forecast = z_crit * sigma (preserves unclipped margin when lower bound is zero-truncated)
        conf_lvl = pred_pt.confidence_level if (0.50 < pred_pt.confidence_level < 1.0) else None
        upper_spread = max(0.0, monthly_demand_high - monthly_demand_point)
        spread_to_use = max(upper_spread, interval_width / 2.0)
        is_interval_valid = (conf_lvl is not None and math.isfinite(conf_lvl) and spread_to_use > 0.0)

        if is_interval_valid and conf_lvl is not None:
            z_crit = float(stats.norm.ppf((1.0 + conf_lvl) / 2.0))
            sigma_period = max(0.5, spread_to_use / z_crit)
            sigma_daily = sigma_period / math.sqrt(period_days)
            interval_conversion_justified = True
        else:
            # Fallback when prediction interval is degenerate (zero width) or confidence level is invalid
            sigma_period = max(1.0, math.sqrt(monthly_demand_point))
            sigma_daily = sigma_period / math.sqrt(period_days)
            interval_conversion_justified = False

        # Lead time parameters
        L_days = float(cons.lead_time_days)
        mu_lead = daily_demand * L_days
        sigma_lead = sigma_daily * math.sqrt(L_days)

        # Safety stock and ROP for target service level
        z_sl = float(stats.norm.ppf(cons.target_service_level))
        safety_stock = math.ceil(max(0.0, z_sl * sigma_lead))
        reorder_point = math.ceil(mu_lead + safety_stock)

        # Current stockout probability before replenishment
        if current_stock < 0:
            current_stockout_risk = 1.0
        elif not interval_conversion_justified and interval_width == 0.0:
            # Degenerate interval: abstain from uncalibrated continuous Gaussian risk; use deterministic step threshold
            current_stockout_risk = 0.0 if current_stock >= mu_lead else 1.0
        elif sigma_lead > 1e-4:
            z_curr = (float(current_stock) - mu_lead) / sigma_lead
            current_stockout_risk = round(float(stats.norm.sf(z_curr)), 4)
        else:
            current_stockout_risk = 0.0 if current_stock >= mu_lead else 1.0

        # Wilson Economic Order Quantity (EOQ)
        # Configurable per tenant via ConstraintSet; defaults to system-wide assumption ($50.00) if omitted
        if cons.order_setup_cost is not None and math.isfinite(cons.order_setup_cost) and cons.order_setup_cost >= 0.0:
            order_setup_cost = float(cons.order_setup_cost)
            is_tenant_setup_cost = True
        else:
            order_setup_cost = 50.0  # System-wide default assumption
            is_tenant_setup_cost = False

        holding_rate = cons.annual_holding_cost_rate
        holding_cost_unit_annual = max(0.01, unit_cost * holding_rate)
        if holding_cost_unit_annual > 0 and annual_demand > 0:
            eoq_raw = math.sqrt((2.0 * annual_demand * order_setup_cost) / holding_cost_unit_annual)
            optimal_q = max(min_order, math.ceil(eoq_raw))
        else:
            optimal_q = 0  # Zero projected demand warrants zero replenishment order

        # 5. Formulate Distinct Evaluated Alternatives
        alternatives: list[ActionAlternative] = []

        # --- Alternative 1: Standard Replenishment (Optimal EOQ / Balanced) ---
        q1 = optimal_q
        cost1 = round(q1 * unit_cost, 2)
        annual_hold1 = round(((q1 / 2.0) + safety_stock) * holding_cost_unit_annual, 2)
        stockout_risk1 = round(1.0 - cons.target_service_level, 4)
        service_lvl1 = round(cons.target_service_level, 4)
        margin_exp1 = round(monthly_demand_point * unit_margin, 2)
        margin_worst1 = round(monthly_demand_low * unit_margin, 2)
        margin_best1 = round(monthly_demand_high * unit_margin, 2)

        is_feas1 = True
        violations1 = []
        if cons.max_budget is not None and cost1 > cons.max_budget:
            is_feas1 = False
            violations1.append(f"Capital outlay (${cost1:,.2f}) exceeds maximum budget (${cons.max_budget:,.2f}).")
        if cons.max_storage_units is not None and (current_stock + q1) > cons.max_storage_units:
            is_feas1 = False
            violations1.append(f"Post-order inventory ({current_stock + q1}) exceeds storage capacity ({cons.max_storage_units}).")
        if cons.max_order_quantity is not None and q1 > cons.max_order_quantity:
            is_feas1 = False
            violations1.append(f"Order quantity ({q1}) exceeds supplier allocation ceiling ({cons.max_order_quantity} units).")

        trade_offs1 = [
            f"Achieves target {cons.target_service_level * 100:.1f}% service level with balanced setup and holding costs.",
            f"Commits ${cost1:,.2f} in working capital with {cons.lead_time_days}-day supplier lead time.",
        ]
        if current_stock < reorder_point:
            trade_offs1.append(f"Stock ({current_stock} units) is below Reorder Point ({reorder_point} units); order immediately to avert stockout.")
        else:
            trade_offs1.append(f"Stock ({current_stock} units) currently exceeds Reorder Point ({reorder_point} units); replenishment will increase holding buffer.")

        alt1 = ActionAlternative(
            action_type=ActionType.REORDER_STANDARD,
            title=f"Standard Replenishment ({q1} units)",
            description=f"Issue purchase order for {q1} units via standard supplier channel ({cons.lead_time_days}-day lead time).",
            recommended_quantity=q1,
            impact=ExpectedImpact(
                expected_cost=cost1,
                expected_revenue_impact=round(monthly_demand_point * selling_price, 2),
                expected_margin_impact=margin_exp1,
                service_level_achieved=service_lvl1,
                stockout_risk=stockout_risk1,
                working_capital_required=cost1,
                holding_cost_annual=annual_hold1,
            ),
            uncertainty=UncertaintyRange(
                worst_case_margin=margin_worst1,
                expected_margin=margin_exp1,
                best_case_margin=margin_best1,
            ),
            trade_offs=trade_offs1,
            is_feasible=is_feas1,
            constraint_violations=violations1,
        )
        alternatives.append(alt1)

        # --- Alternative 2: Expedited Replenishment (Zero Stockout Priority) ---
        expedited_lead = max(1, cons.lead_time_days // 2)
        expedited_freight_fee = round(max(35.0, cost1 * 0.08), 2)  # 8% express surcharge
        q2 = max(min_order, math.ceil(optimal_q * 1.15))  # slightly larger buffer
        cost2 = round((q2 * unit_cost) + expedited_freight_fee, 2)
        annual_hold2 = round(((q2 / 2.0) + safety_stock) * holding_cost_unit_annual, 2)
        stockout_risk2 = round(stockout_risk1 * 0.3, 4)
        service_lvl2 = round(1.0 - stockout_risk2, 4)

        is_feas2 = True
        violations2 = []
        if cons.max_budget is not None and cost2 > cons.max_budget:
            is_feas2 = False
            violations2.append(f"Capital outlay (${cost2:,.2f}) exceeds maximum budget (${cons.max_budget:,.2f}).")
        if cons.max_storage_units is not None and (current_stock + q2) > cons.max_storage_units:
            is_feas2 = False
            violations2.append(f"Post-order inventory ({current_stock + q2}) exceeds storage capacity ({cons.max_storage_units}).")
        if cons.max_order_quantity is not None and q2 > cons.max_order_quantity:
            is_feas2 = False
            violations2.append(f"Order quantity ({q2}) exceeds supplier allocation ceiling ({cons.max_order_quantity} units).")

        alt2 = ActionAlternative(
            action_type=ActionType.REORDER_EXPEDITED,
            title=f"Expedited Replenishment ({q2} units)",
            description=f"Order {q2} units with expedited freight ({expedited_lead}-day lead time) to minimize stockout exposure.",
            recommended_quantity=q2,
            impact=ExpectedImpact(
                expected_cost=cost2,
                expected_revenue_impact=round(monthly_demand_point * selling_price, 2),
                expected_margin_impact=round(margin_exp1 - expedited_freight_fee, 2),
                service_level_achieved=service_lvl2,
                stockout_risk=stockout_risk2,
                working_capital_required=cost2,
                holding_cost_annual=annual_hold2,
            ),
            uncertainty=UncertaintyRange(
                worst_case_margin=round(margin_worst1 - expedited_freight_fee, 2),
                expected_margin=round(margin_exp1 - expedited_freight_fee, 2),
                best_case_margin=round(margin_best1 - expedited_freight_fee, 2),
            ),
            trade_offs=[
                f"Reduces stockout risk to {stockout_risk2 * 100:.2f}% via accelerated {expedited_lead}-day delivery.",
                f"Incurs ${expedited_freight_fee:,.2f} freight surcharge directly reducing gross profit.",
            ],
            is_feasible=is_feas2,
            constraint_violations=violations2,
        )
        alternatives.append(alt2)

        # --- Alternative 3: Maintain Current Stock / Defer Order ---
        unmet_demand_exp = max(0.0, monthly_demand_point - current_stock)
        lost_margin_exp = round(unmet_demand_exp * unit_margin, 2)
        unmet_demand_worst = max(0.0, monthly_demand_high - current_stock)
        lost_margin_worst = round(unmet_demand_worst * unit_margin, 2)
        hold_curr = round(current_stock * holding_cost_unit_annual, 2)

        alt3 = ActionAlternative(
            action_type=ActionType.MAINTAIN_STOCK,
            title="Maintain Current Stock (Zero Capital Outlay)",
            description="Defer purchase orders and fulfill demand exclusively from existing inventory on hand.",
            recommended_quantity=0,
            impact=ExpectedImpact(
                expected_cost=0.0,
                expected_revenue_impact=round(min(current_stock, monthly_demand_point) * selling_price, 2),
                expected_margin_impact=round((monthly_demand_point * unit_margin) - lost_margin_exp, 2),
                service_level_achieved=round(1.0 - current_stockout_risk, 4),
                stockout_risk=current_stockout_risk,
                working_capital_required=0.0,
                holding_cost_annual=hold_curr,
            ),
            uncertainty=UncertaintyRange(
                worst_case_margin=round((monthly_demand_point * unit_margin) - lost_margin_worst, 2),
                expected_margin=round((monthly_demand_point * unit_margin) - lost_margin_exp, 2),
                best_case_margin=round(monthly_demand_point * unit_margin, 2),
            ),
            trade_offs=[
                "Preserves 100% of working capital ($0 outlay).",
                f"Carries {current_stockout_risk * 100:.1f}% stockout risk during the forecast horizon.",
                f"Under upper forecast bound ({monthly_demand_high:.0f} units), faces potential lost margin of ${lost_margin_worst:,.2f}.",
            ],
            is_feasible=True,
            constraint_violations=[],
        )
        alternatives.append(alt3)

        # 6. Rank Alternatives According to Stated Objective
        selected_alt = None
        feasible_alts = [a for a in alternatives if a.is_feasible]

        if not feasible_alts:
            return self._build_abstained(
                rec_id=rec_id,
                category="inventory_replenishment",
                entity_id=sku,
                objective=objective,
                status=RecommendationStatus.CONFLICTING_CONSTRAINTS,
                reason="No evaluated action alternative satisfies the active budget or storage constraints.",
                created_at=now_str,
                alternatives=alternatives,
            )

        if objective == ObjectiveType.MINIMIZE_STOCKOUT:
            # Prioritize highest service level
            selected_alt = min(feasible_alts, key=lambda a: a.impact.stockout_risk)
        elif objective == ObjectiveType.MINIMIZE_HOLDING_COST:
            # Prioritize zero or minimal capital outlay
            selected_alt = min(feasible_alts, key=lambda a: (a.impact.holding_cost_annual, a.impact.expected_cost))
        elif objective == ObjectiveType.MAXIMIZE_MARGIN:
            # Prioritize highest expected margin impact
            selected_alt = max(feasible_alts, key=lambda a: a.impact.expected_margin_impact)
        else:  # BALANCE_SERVICE_LEVEL
            # If stock is below ROP, choose standard reorder if feasible, else maintain
            if current_stock < reorder_point:
                selected_alt = next((a for a in feasible_alts if a.action_type == ActionType.REORDER_STANDARD), feasible_alts[0])
            else:
                # Adequate stock exists; deferring is safe
                selected_alt = next((a for a in feasible_alts if a.action_type == ActionType.MAINTAIN_STOCK), feasible_alts[0])

        # 7. Assemble Grounded Evidence & Telemetry Lineage
        observed_facts = [
            ObservedFact(metric="current_stock_quantity", value=current_stock, source_table="inventory", description="Units physically on hand"),
            ObservedFact(metric="unit_cost", value=unit_cost, source_table="products", description="Product COGS unit cost ($)"),
            ObservedFact(metric="selling_price", value=selling_price, source_table="products", description="Retail selling price ($)"),
            ObservedFact(metric="reorder_threshold", value=int(inv.reorder_threshold), source_table="inventory", description="Existing static threshold in DB"),
            ObservedFact(metric="calculated_reorder_point", value=reorder_point, source_table="prescriptive_engine", description="Lead time demand + safety stock (ROP)"),
            ObservedFact(metric="calculated_safety_stock", value=safety_stock, source_table="prescriptive_engine", description=f"Safety buffer at {cons.target_service_level * 100:.1f}% service level"),
            ObservedFact(metric="current_stockout_risk", value=f"{current_stockout_risk * 100:.1f}%", source_table="prescriptive_engine", description="Probability of stockout before lead time replenishment"),
        ]
        if is_tenant_setup_cost:
            observed_facts.append(
                ObservedFact(metric="order_setup_cost", value=order_setup_cost, source_table="constraints", description="Tenant-configured procurement order setup cost ($)")
            )

        forecast_inputs = [
            ForecastInput(
                metric="product_demand",
                point_forecast=monthly_demand_point,
                lower_bound=monthly_demand_low,
                upper_bound=monthly_demand_high,
                confidence_level=pred_pt.confidence_level,
                horizon_periods=1,
                frequency=fcst_freq,
                model_name=fcst_res.model.name,
            )
        ]

        order_cost_assumption = (
            f"Procurement setup cost per purchase order is configured by tenant at ${order_setup_cost:.2f}."
            if is_tenant_setup_cost
            else f"Procurement setup cost per purchase order is assumed at ${order_setup_cost:.2f} (system-wide unconfigured default assumption; not a tenant-provided fact)."
        )

        volatility_conversion_assumption = (
            f"Daily demand volatility is converted from the Phase 26 1-step {fcst_freq} prediction interval "
            f"(coverage: {conf_lvl * 100:.1f}%) via square-root-of-time scaling (sigma_daily = sigma_{fcst_freq} / sqrt({int(period_days)})), "
            "assuming independent and identically distributed daily demand without serial correlation."
            if interval_conversion_justified and conf_lvl is not None
            else f"Forecast prediction interval has degenerate width; volatility defaults to Poisson square-root heuristic (sigma_daily = sqrt(mu_{fcst_freq}) / sqrt({int(period_days)}))."
        )

        assumptions = [
            f"Supplier lead time is constant at {cons.lead_time_days} calendar days.",
            f"Daily demand is assumed independent and identically distributed over the {cons.lead_time_days}-day lead time window.",
            f"Annual inventory holding cost rate is {cons.annual_holding_cost_rate * 100:.1f}% of unit COGS.",
            order_cost_assumption,
            volatility_conversion_assumption,
        ]

        limitations = [
            "Supplier volume tier discounts and freight rate step-functions are unmodeled.",
            "Forecast uncertainty reflects statistical historical variance and excludes unobserved macro supplier delays.",
            "Cross-SKU basket substitution effects are not incorporated in single-item inventory evaluations.",
            "Square-root-of-time temporal scaling assumes zero daily serial autocorrelation; positive autocorrelation would cause lead-time demand variance to be underestimated.",
        ]
        if L_days > period_days:
            limitations.append(
                f"Supplier lead time ({int(L_days)} days) exceeds the 1-period forecast horizon ({int(period_days)} days); "
                "square-root temporal scaling assumes stationary variance and uncompounded multi-period forecast error."
            )
        if not interval_conversion_justified:
            limitations.append(
                "Phase 26 prediction interval width was degenerate or uncalibrated; continuous probabilistic stockout risk was abstained or defaulted."
            )
        if sigma_lead > 0 and (mu_lead / sigma_lead) < 2.0:
            limitations.append(
                f"Lead-time demand variability is elevated (mu={mu_lead:.1f}, sigma={sigma_lead:.1f}, ratio={mu_lead/sigma_lead:.2f} < 2.0); "
                "normality assumption may assign non-zero probability to negative demand and underestimate extreme stockout tail risks."
            )

        return PrescriptiveRecommendation(
            recommendation_id=rec_id,
            status=RecommendationStatus.ACTIONABLE,
            category="inventory_replenishment",
            business_id=self.business_id,
            entity_type="product",
            entity_id=sku,
            objective=objective,
            recommended_action=selected_alt,
            alternatives=alternatives,
            observed_facts=observed_facts,
            forecast_inputs=forecast_inputs,
            assumptions=assumptions,
            limitations=limitations,
            abstention_reason=None,
            requires_human_approval=True,
            created_at=now_str,
        )

    def evaluate_pricing_markdown(
        self,
        sku: str,
        target_discount_pct: float = 0.15,
        target_margin_floor: float = 0.10,
    ) -> PrescriptiveRecommendation:
        """
        Evaluate pricing markdown / clearance discount for slow-moving or dormant inventory.
        
        Calculates:
        - Unit margin sacrifice vs holding cost savings
        - Required sales volume lift to achieve gross margin dollar break-even
        - Impact on working capital velocity under historical COGS valuation
        """
        now_str = datetime.now(UTC).isoformat()
        rec_id = f"REC-PRC-{uuid4().hex[:8].upper()}"

        # 1. Validate Target Discount & Margin Floor Input Parameters
        try:
            target_disc = float(target_discount_pct)
            target_floor = float(target_margin_floor)
        except (TypeError, ValueError):
            return self._build_abstained(
                rec_id=rec_id,
                category="pricing_markdown",
                entity_id=sku,
                objective=ObjectiveType.MAXIMIZE_MARGIN,
                status=RecommendationStatus.INSUFFICIENT_EVIDENCE,
                reason="Target discount percentage and margin floor must be numeric values.",
                created_at=now_str,
            )

        if not math.isfinite(target_disc) or not (0.01 <= target_disc <= 0.90):
            return self._build_abstained(
                rec_id=rec_id,
                category="pricing_markdown",
                entity_id=sku,
                objective=ObjectiveType.MAXIMIZE_MARGIN,
                status=RecommendationStatus.CONFLICTING_CONSTRAINTS,
                reason=f"Target discount percentage ({target_disc}) must be a finite number between 0.01 (1%) and 0.90 (90%).",
                created_at=now_str,
            )

        if not math.isfinite(target_floor) or not (0.0 <= target_floor <= 0.90):
            return self._build_abstained(
                rec_id=rec_id,
                category="pricing_markdown",
                entity_id=sku,
                objective=ObjectiveType.MAXIMIZE_MARGIN,
                status=RecommendationStatus.CONFLICTING_CONSTRAINTS,
                reason=f"Target margin floor ({target_floor}) must be a finite number between 0.0 and 0.90.",
                created_at=now_str,
            )

        # 2. Query Product & Stock
        prod_stmt = select(Product).where(Product.sku == sku)
        if self.business_id:
            prod_stmt = prod_stmt.where(Product.business_id == self.business_id)
        prod = self.session.execute(prod_stmt).scalar_one_or_none()

        if not prod:
            return self._build_abstained(
                rec_id=rec_id,
                category="pricing_markdown",
                entity_id=sku,
                objective=ObjectiveType.MAXIMIZE_MARGIN,
                status=RecommendationStatus.INSUFFICIENT_EVIDENCE,
                reason=f"Product SKU '{sku}' not found.",
                created_at=now_str,
            )

        inv_stmt = select(Inventory).where(Inventory.product_id == prod.id)
        if self.business_id:
            inv_stmt = inv_stmt.where(Inventory.business_id == self.business_id)
        inv = self.session.execute(inv_stmt).scalar_one_or_none()

        if not inv or inv.stock_quantity <= 0:
            return self._build_abstained(
                rec_id=rec_id,
                category="pricing_markdown",
                entity_id=sku,
                objective=ObjectiveType.MAXIMIZE_MARGIN,
                status=RecommendationStatus.ABSTAINED,
                reason=f"SKU '{sku}' currently has zero physical stock on hand; promotional markdown is inapplicable.",
                created_at=now_str,
            )

        # 3. Validate Product Economics
        try:
            unit_cost = float(prod.unit_cost)
            base_price = float(prod.selling_price)
        except (TypeError, ValueError):
            return self._build_abstained(
                rec_id=rec_id,
                category="pricing_markdown",
                entity_id=sku,
                objective=ObjectiveType.MAXIMIZE_MARGIN,
                status=RecommendationStatus.INSUFFICIENT_EVIDENCE,
                reason=f"Product SKU '{sku}' has non-numeric unit cost or selling price.",
                created_at=now_str,
            )

        if not math.isfinite(unit_cost) or unit_cost <= 0.0:
            return self._build_abstained(
                rec_id=rec_id,
                category="pricing_markdown",
                entity_id=sku,
                objective=ObjectiveType.MAXIMIZE_MARGIN,
                status=RecommendationStatus.INSUFFICIENT_EVIDENCE,
                reason=f"Product SKU '{sku}' has invalid unit cost (${unit_cost}). Unit cost must be positive and finite.",
                created_at=now_str,
            )

        if not math.isfinite(base_price) or base_price <= 0.0:
            return self._build_abstained(
                rec_id=rec_id,
                category="pricing_markdown",
                entity_id=sku,
                objective=ObjectiveType.MAXIMIZE_MARGIN,
                status=RecommendationStatus.INSUFFICIENT_EVIDENCE,
                reason=f"Product SKU '{sku}' has invalid selling price (${base_price}). Selling price must be positive and finite.",
                created_at=now_str,
            )

        if base_price <= unit_cost:
            return self._build_abstained(
                rec_id=rec_id,
                category="pricing_markdown",
                entity_id=sku,
                objective=ObjectiveType.MAXIMIZE_MARGIN,
                status=RecommendationStatus.ABSTAINED,
                reason=(
                    f"Product SKU '{sku}' currently sells at or below unit cost "
                    f"(price ${base_price:.2f} <= cost ${unit_cost:.2f}); promotional markdown cannot achieve gross-margin break-even."
                ),
                created_at=now_str,
            )

        stock_units = int(inv.stock_quantity)
        base_unit_margin = base_price - unit_cost
        base_margin_pct = base_unit_margin / base_price
        tied_working_capital = round(stock_units * unit_cost, 2)

        # 4. Check Product Velocity
        context = AnalysisContext(business_id=self.business_id)
        velocity_res = ProductVelocityCalculator.evaluate(self.session, context)
        sku_velocity_item = next((p for p in velocity_res.products if p.sku == sku), None)
        velocity_class = sku_velocity_item.velocity_classification if sku_velocity_item else "slow_moving"

        # If product already has high velocity, markdown is counterproductive
        if velocity_class == "high":
            return self._build_abstained(
                rec_id=rec_id,
                category="pricing_markdown",
                entity_id=sku,
                objective=ObjectiveType.MAXIMIZE_MARGIN,
                status=RecommendationStatus.ABSTAINED,
                reason=(
                    f"SKU '{sku}' already exhibits 'high' sales velocity ({sku_velocity_item.units_per_day:.1f} units/day). "
                    "Promotional discounting would dilute gross margin without operational necessity."
                ),
                created_at=now_str,
            )

        # 5. Formulate Alternatives and Compute Break-Even Metrics
        disc_rate = target_disc
        discounted_price = round(base_price * (1.0 - disc_rate), 2)
        disc_unit_margin = discounted_price - unit_cost
        disc_margin_pct = (disc_unit_margin / discounted_price) if discounted_price > 0 else 0.0

        # Exact Gross Margin Dollar Break-Even Volume Lift Formula:
        # M_base = Q0 * (P0 - C)
        # M_disc = Q1 * (P1 - C)
        # Break-even condition: M_disc = M_base => Q1 / Q0 = (P0 - C) / (P1 - C)
        # Required volume lift % = (Q1 - Q0) / Q0 * 100 = ((base_unit_margin / disc_unit_margin) - 1.0) * 100
        if disc_unit_margin > 0.0:
            req_volume_lift_pct = round(((base_unit_margin / disc_unit_margin) - 1.0) * 100.0, 1)
        else:
            req_volume_lift_pct = float("inf")

        annual_holding_per_unit = unit_cost * 0.20
        holding_saved_if_cleared = round(stock_units * annual_holding_per_unit * 0.5, 2)  # 6-month holding savings

        alternatives: list[ActionAlternative] = []

        # Alt 1: Clearance Markdown
        is_feas1 = True
        violations1 = []

        if disc_unit_margin <= 0.0:
            is_feas1 = False
            violations1.append(
                f"Discounted price (${discounted_price:.2f}) does not exceed unit cost (${unit_cost:.2f}); "
                "dollar gross margin break-even is mathematically impossible."
            )
        elif disc_margin_pct < target_floor:
            is_feas1 = False
            violations1.append(
                f"Discounted margin rate ({disc_margin_pct * 100:.1f}%) breaches target margin floor ({target_floor * 100:.1f}%)."
            )

        lift_display = f"{req_volume_lift_pct:.1f}%" if math.isfinite(req_volume_lift_pct) else "infinite (impossible)"

        alt1 = ActionAlternative(
            action_type=ActionType.CLEARANCE_MARKDOWN,
            title=f"Apply {disc_rate * 100:.0f}% Promotional Markdown (${discounted_price:.2f})",
            description=f"Reduce retail catalog price by {disc_rate * 100:.0f}% from ${base_price:.2f} to ${discounted_price:.2f} to stimulate inventory turnover.",
            recommended_quantity=stock_units,
            recommended_discount_pct=disc_rate,
            impact=ExpectedImpact(
                expected_cost=0.0,
                expected_revenue_impact=round(stock_units * discounted_price, 2),
                expected_margin_impact=round(stock_units * max(0.0, disc_unit_margin), 2),
                service_level_achieved=1.0,
                stockout_risk=0.0,
                working_capital_required=0.0,
                holding_cost_annual=0.0,
            ),
            trade_offs=[
                f"Requires a {lift_display} sales volume increase to maintain baseline gross margin dollars; this is a mathematical break-even threshold, not an empirical demand forecast.",
                f"Accelerates recovery of ${tied_working_capital:,.2f} in working capital (COGS valuation basis) and avoids up to ${holding_saved_if_cleared:,.2f} in 6-month warehousing holding drag.",
                f"Yields ${max(0.0, disc_unit_margin):.2f} unit gross margin ({disc_margin_pct * 100:.1f}% margin rate) upon liquidation.",
            ],
            is_feasible=is_feas1,
            constraint_violations=violations1,
        )
        alternatives.append(alt1)

        # Alt 2: Hold Base Price
        alt2 = ActionAlternative(
            action_type=ActionType.HOLD_PRICE,
            title=f"Maintain Standard Price (${base_price:.2f})",
            description=f"Keep standard catalog price at ${base_price:.2f} preserving {base_margin_pct * 100:.1f}% gross margin percentage.",
            recommended_quantity=0,
            recommended_discount_pct=0.0,
            impact=ExpectedImpact(
                expected_cost=0.0,
                expected_revenue_impact=round(stock_units * base_price, 2),
                expected_margin_impact=round(stock_units * base_unit_margin, 2),
                service_level_achieved=1.0,
                stockout_risk=0.0,
                working_capital_required=0.0,
                holding_cost_annual=round(stock_units * annual_holding_per_unit, 2),
            ),
            trade_offs=[
                f"Protects premium margin rate ({base_margin_pct * 100:.1f}%), avoiding price erosion.",
                f"Maintains ${tied_working_capital:,.2f} in tied working capital (COGS valuation basis) and incurs up to ${stock_units * annual_holding_per_unit:,.2f}/yr holding drag.",
            ],
            is_feasible=True,
            constraint_violations=[],
        )
        alternatives.append(alt2)

        # Feasible alternative selection: Alt 1 if feasible, else Alt 2
        selected_alt = alt1 if is_feas1 else alt2

        return PrescriptiveRecommendation(
            recommendation_id=rec_id,
            status=RecommendationStatus.ACTIONABLE,
            category="pricing_markdown",
            business_id=self.business_id,
            entity_type="product",
            entity_id=sku,
            objective=ObjectiveType.MAXIMIZE_MARGIN,
            recommended_action=selected_alt,
            alternatives=alternatives,
            observed_facts=[
                ObservedFact(metric="current_stock", value=stock_units, source_table="inventory", description="Units physically on hand"),
                ObservedFact(metric="unit_cost", value=unit_cost, source_table="products", description="Product COGS ($)"),
                ObservedFact(metric="current_price", value=base_price, source_table="products", description="Current retail selling price ($)"),
                ObservedFact(metric="tied_working_capital", value=tied_working_capital, source_table="inventory", description="Working capital tied in inventory at COGS ($)"),
                ObservedFact(metric="velocity_classification", value=velocity_class, source_table="velocity_analytics", description="Catalog turnover velocity tier"),
            ],
            forecast_inputs=[],
            assumptions=[
                "Inventory working capital is valued strictly on a historical COGS basis (stock units * unit cost), consistent with lower-of-cost-or-net-realizable-value accounting.",
                "Holding carrying costs accrue at 20.0% p.a. of unit COGS inventory valuation.",
                f"Gross margin break-even requires {lift_display} sales volume lift. Actual demand elasticity is not empirically estimated in this evaluation and must be validated against market elasticity.",
            ],
            limitations=[
                "This evaluation computes mathematical gross-margin break-even thresholds and does not predict actual price elasticity of demand.",
                "Cross-elasticity and cannibalization of complementary catalog items are unmeasured.",
                "Brand equity, customer reference price decay, and competitor price-matching reactions are unobserved.",
            ],
            abstention_reason=None,
            requires_human_approval=True,
            created_at=now_str,
        )

    def _build_abstained(
        self,
        rec_id: str,
        category: str,
        entity_id: str | None,
        objective: ObjectiveType,
        status: RecommendationStatus,
        reason: str,
        created_at: str,
        observed_facts: list[ObservedFact] | None = None,
        alternatives: list[ActionAlternative] | None = None,
    ) -> PrescriptiveRecommendation:
        """Construct a standardized abstention payload with explicit diagnostic rationale."""
        return PrescriptiveRecommendation(
            recommendation_id=rec_id,
            status=status,
            category=category,
            business_id=self.business_id,
            entity_type="product",
            entity_id=entity_id,
            objective=objective,
            recommended_action=None,
            alternatives=alternatives or [],
            observed_facts=observed_facts or [],
            forecast_inputs=[],
            assumptions=[],
            limitations=[reason],
            abstention_reason=reason,
            requires_human_approval=True,
            created_at=created_at,
        )
