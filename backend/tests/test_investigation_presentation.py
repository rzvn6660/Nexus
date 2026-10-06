"""Focused regression tests for Phase 6 Investigation Presentation.

Verifies:
1. Observed Empirical Signals never render bare "-" and return explicit unavailable state
   when current tenant lacks required line-item/product telemetry.
2. Evidence Gaps contain gap_id and area without missing attributes.
3. NOT_SUPPORTED hypotheses have INSUFFICIENT evidence strength when telemetry is missing,
   never implying "Confidence: DIRECT" on an unsupported conclusion.
4. No metrics or drivers (like "Price Effect was predominant driver (0.0%)") are fabricated.
"""

from unittest.mock import MagicMock
from app.investigation.engine import InvestigationEngine
from app.investigation.hypotheses import HypothesisEngine
from app.investigation.models import (
    EvidenceGap,
    EvidenceStrength,
    HypothesisStatus,
    InvestigationHypothesis,
    InvestigationPlan,
    InvestigationType,
)
from app.investigation.strategies.revenue import RevenueInvestigationStrategy


def test_category_variance_not_supported_with_insufficient_evidence_when_zero_items():
    """NOT_SUPPORTED hypothesis for category contribution must have INSUFFICIENT strength, not DIRECT."""
    hyp = InvestigationHypothesis(
        id="HYP-CAT",
        statement="Revenue decline was concentrated within specific merchandise categories.",
        type="category_contribution",
    )

    tool_results = [
        {
            "step": 1,
            "tool": "run_variance_analysis",
            "result": {
                "dimension": "category",
                "total_variance": 0.0,
                "items": [],
                "top_negative_contributors": [],
                "top_positive_contributors": [],
            },
        }
    ]

    evaluated = HypothesisEngine.evaluate_hypotheses([hyp], tool_results, [])
    res = evaluated[0]

    assert res.status == HypothesisStatus.NOT_SUPPORTED
    assert res.evidence_strength == EvidenceStrength.INSUFFICIENT
    assert res.evidence_strength != EvidenceStrength.DIRECT
    assert "zero categorized line items" in res.confidence_reason
    assert "insufficient" in res.confidence_reason.lower()


def test_volume_effect_not_supported_with_insufficient_evidence_when_zero_variance():
    """PVM with zero variance/items must have INSUFFICIENT strength and NOT fabricate predominant driver."""
    hyp = InvestigationHypothesis(
        id="HYP-VOL",
        statement="Revenue change was driven by sales volume rather than pricing.",
        type="volume_effect",
    )

    tool_results = [
        {
            "step": 2,
            "tool": "run_price_volume_mix",
            "result": {
                "total_variance": 0.0,
                "volume_effect": 0.0,
                "price_effect": 0.0,
                "mix_effect": 0.0,
                "reconciled": True,
            },
        }
    ]

    evaluated = HypothesisEngine.evaluate_hypotheses([hyp], tool_results, [])
    res = evaluated[0]

    assert res.status == HypothesisStatus.NOT_SUPPORTED
    assert res.evidence_strength == EvidenceStrength.INSUFFICIENT
    assert res.evidence_strength != EvidenceStrength.DIRECT
    # Must NOT fabricate that Price Effect was predominant driver (0.0%)
    assert "predominant driver" not in res.confidence_reason
    assert "insufficient line-item telemetry" in res.confidence_reason


def test_mix_effect_not_supported_with_insufficient_evidence_when_zero_variance():
    """PVM mix effect with zero variance/items must have INSUFFICIENT strength and not claim DIRECT."""
    hyp = InvestigationHypothesis(
        id="HYP-MIX",
        statement="Product mix shifting drove revenue variance.",
        type="product_mix_shift",
    )

    tool_results = [
        {
            "step": 2,
            "tool": "run_price_volume_mix",
            "result": {
                "total_variance": 0.0,
                "volume_effect": 0.0,
                "price_effect": 0.0,
                "mix_effect": 0.0,
                "reconciled": True,
            },
        }
    ]

    evaluated = HypothesisEngine.evaluate_hypotheses([hyp], tool_results, [])
    res = evaluated[0]

    assert res.status == HypothesisStatus.NOT_SUPPORTED
    assert res.evidence_strength == EvidenceStrength.INSUFFICIENT
    assert res.evidence_strength != EvidenceStrength.DIRECT
    assert "insufficient line-item telemetry" in res.confidence_reason


def test_evidence_gap_model_and_strategy_area_attributes():
    """EvidenceGap must serialize gap_id, area, and impact_assessment cleanly without undefined fields."""
    gap = EvidenceGap(
        description="Competitor pricing data unobserved.",
        missing_data="Retail benchmark data",
        impact="Limited to internal telemetry.",
    )
    assert gap.gap_id.startswith("GAP-")
    assert gap.area == "External Market Telemetry"
    assert gap.impact_assessment == "Limited to internal telemetry."

    strategy = RevenueInvestigationStrategy(is_decline=True)
    gaps = strategy.identify_evidence_gaps(
        executed_tools=["get_financial_summary", "run_variance_analysis", "run_price_volume_mix"],
        results=[
            {"dimension": "category", "items": [], "top_negative_contributors": []},
            {"volume_effect": 0.0, "price_effect": 0.0, "total_variance": 0.0},
        ],
    )

    assert len(gaps) >= 2
    # Verify primary external gap
    assert gaps[0].area == "Competitor & Market Pricing"
    assert gaps[0].gap_id == "GAP-REV-01"
    # Verify missing line-item telemetry gap
    assert any(g.area == "Line-Item & Product Telemetry" for g in gaps)
    for g in gaps:
        assert g.gap_id
        assert g.area
        assert g.description


def test_engine_extract_observations_explicit_unavailable_when_line_items_missing():
    """InvestigationEngine must generate explicit unavailable observations rather than empty/bare values."""
    mock_db = MagicMock()
    engine = InvestigationEngine(mock_db, business_id="test-biz")

    plan = InvestigationPlan(
        goal="Test Goal",
        investigation_type=InvestigationType.REVENUE_DECLINE,
        baseline_dates={"date_from": "2026-01-01"},
        comparison_dates={"date_from": "2026-02-01"},
        steps=[],
    )

    # 1. Variance analysis with zero items
    var_obs = engine._extract_observations(
        step_num=1,
        tool_name="run_variance_analysis",
        result={"dimension": "category", "total_variance": 0.0, "items": []},
        plan=plan,
    )
    assert len(var_obs) == 1
    assert var_obs[0].value_current is None
    assert var_obs[0].value_baseline is None
    assert "unavailable: current tenant lacks required line-item/product telemetry" in var_obs[0].statement

    # 2. PVM with zero variance / zero items
    pvm_obs = engine._extract_observations(
        step_num=2,
        tool_name="run_price_volume_mix",
        result={"volume_effect": 0.0, "price_effect": 0.0, "mix_effect": 0.0, "total_variance": 0.0},
        plan=plan,
    )
    assert len(pvm_obs) == 1
    assert pvm_obs[0].value_current is None
    assert pvm_obs[0].value_baseline is None
    assert "unavailable: current tenant lacks required line-item/product telemetry" in pvm_obs[0].statement
