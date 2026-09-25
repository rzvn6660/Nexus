"""Unit tests for Phase 6 Hypothesis Engine and evidence evaluation."""


from app.investigation.hypotheses import HypothesisEngine
from app.investigation.models import (
    EvidenceStrength,
    HypothesisStatus,
    InvestigationHypothesis,
)


def test_hypothesis_supported_by_category_variance():
    """Verify hypothesis transitions to SUPPORTED when category variance shows concentration."""
    hyp = InvestigationHypothesis(
        id="HYP-1",
        statement="Revenue decline was concentrated within specific merchandise categories.",
        type="category_contribution",
    )

    tool_results = [
        {
            "step": 1,
            "tool": "run_variance_analysis",
            "result": {
                "dimension": "category",
                "total_variance": -10000.0,
                "items": [
                    {
                        "entity_name": "Electronics",
                        "variance_amount": -6500.0,
                        "contribution_percentage": 65.0,
                    },
                    {
                        "entity_name": "Apparel",
                        "variance_amount": -3500.0,
                        "contribution_percentage": 35.0,
                    },
                ],
            },
        }
    ]

    evaluated = HypothesisEngine.evaluate_hypotheses([hyp], tool_results, [])
    res = evaluated[0]

    assert res.status == HypothesisStatus.SUPPORTED
    assert res.evidence_strength == EvidenceStrength.DIRECT
    assert len(res.supporting_evidence) == 1
    assert res.supporting_evidence[0].contribution_pct == 65.0
    assert "Electronics" in res.confidence_reason


def test_hypothesis_not_supported_when_diffuse_variance():
    """Verify hypothesis is NOT_SUPPORTED when variance is diffuse across many categories."""
    hyp = InvestigationHypothesis(
        id="HYP-1",
        statement="Revenue decline was concentrated in one category.",
        type="category_contribution",
    )

    tool_results = [
        {
            "step": 1,
            "tool": "run_variance_analysis",
            "result": {
                "dimension": "category",
                "total_variance": -10000.0,
                "items": [
                    {
                        "entity_name": "Category A",
                        "variance_amount": -1200.0,
                        "contribution_percentage": 12.0,
                    },
                    {
                        "entity_name": "Category B",
                        "variance_amount": -1100.0,
                        "contribution_percentage": 11.0,
                    },
                ],
            },
        }
    ]

    evaluated = HypothesisEngine.evaluate_hypotheses([hyp], tool_results, [])
    res = evaluated[0]

    assert res.status == HypothesisStatus.NOT_SUPPORTED
    assert len(res.contradicting_evidence) == 1
    assert "diffuse" in res.confidence_reason.lower()


def test_hypothesis_supported_by_volume_effect_in_pvm():
    """Verify volume effect dominance in Price/Volume/Mix decomposition."""
    hyp = InvestigationHypothesis(
        id="HYP-VOL",
        statement="Revenue change was driven by sales volume rather than pricing.",
        type="volume_effect",
    )

    tool_results = [
        {
            "step": 1,
            "tool": "run_price_volume_mix",
            "result": {
                "total_variance": -10000.0,
                "volume_effect": -8000.0,
                "price_effect": -1500.0,
                "mix_effect": -500.0,
            },
        }
    ]

    evaluated = HypothesisEngine.evaluate_hypotheses([hyp], tool_results, [])
    res = evaluated[0]

    assert res.status == HypothesisStatus.SUPPORTED
    assert res.evidence_strength == EvidenceStrength.DIRECT
    assert len(res.supporting_evidence) == 1
    assert res.supporting_evidence[0].contribution_pct == 80.0


def test_inventory_hypothesis_handles_stockouts_with_limitation():
    """Verify stockout hypothesis evaluates moderately and records snapshot limitation."""
    hyp = InvestigationHypothesis(
        id="HYP-INV",
        statement="Low stock levels restricted sales fulfillment.",
        type="stockout_constraint",
    )

    tool_results = [
        {
            "step": 1,
            "tool": "get_inventory_overview",
            "result": {
                "low_stock_count": 5,
                "out_of_stock_count": 2,
            },
        }
    ]

    evaluated = HypothesisEngine.evaluate_hypotheses([hyp], tool_results, [])
    res = evaluated[0]

    assert res.status == HypothesisStatus.PARTIALLY_SUPPORTED
    assert res.evidence_strength == EvidenceStrength.MODERATE
    assert len(res.limitations) > 0
    assert "snapshot" in res.limitations[0].lower()
