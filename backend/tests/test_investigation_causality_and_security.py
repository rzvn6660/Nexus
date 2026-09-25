"""Tests for causality safeguards, linguistic boundaries, and security guardrails."""


from app.investigation.evidence import EvidenceSynthesizer
from app.investigation.models import (
    EvidenceGap,
    EvidenceLink,
    EvidenceStrength,
    HypothesisStatus,
    InvestigationHypothesis,
    InvestigationObservation,
    InvestigationPlan,
    InvestigationType,
)
from app.investigation.validators import CausalitySafeguard


def test_causality_safeguard_detects_aggressive_claims():
    """Verify CausalitySafeguard detects unsupported causal language."""
    text_bad = "The discount change directly caused revenue to fall and proves causality."
    findings = CausalitySafeguard.check_causal_assertions(text_bad)
    assert len(findings) > 0

    text_good = "Discounts were associated with lower order volume and contributed to the measured variance."
    findings_good = CausalitySafeguard.check_causal_assertions(text_good)
    assert len(findings_good) == 0


def test_causality_safeguard_detects_prescriptive_recommendations():
    """Verify CausalitySafeguard detects prohibited prescriptive advice."""
    prescriptive_text = "We should raise prices and fire supplier X to fix margins."
    findings = CausalitySafeguard.check_prescriptive_claims(prescriptive_text)
    assert len(findings) > 0

    diagnostic_text = "Review product velocity and unit margins within the category."
    findings_clean = CausalitySafeguard.check_prescriptive_claims(diagnostic_text)
    assert len(findings_clean) == 0


def test_causality_sanitization_converts_causal_to_contribution():
    """Verify automatic text sanitization softens unproven causal assertions."""
    raw = "Category A caused the decline and was the root cause of lost revenue."
    sanitized = CausalitySafeguard.sanitize_diagnostic_text(raw)
    assert "caused" not in sanitized.lower()
    assert "contributed to" in sanitized.lower() or "largest measured contributor" in sanitized.lower()


def test_explanation_contains_required_sections_and_caveats():
    """Verify diagnostic explanation enforces Section 21 structure and caveats."""
    plan = InvestigationPlan(
        goal="Diagnose revenue decline",
        investigation_type=InvestigationType.REVENUE_DECLINE,
    )
    obs = [
        InvestigationObservation(
            id="OBS-1",
            statement="Revenue decreased by 8.2% ($12,000 vs $13,071).",
            metric="net_sales",
        )
    ]
    hyp = [
        InvestigationHypothesis(
            id="HYP-1",
            statement="Category A accounted for majority of variance.",
            type="category_contribution",
            status=HypothesisStatus.SUPPORTED,
            evidence_strength=EvidenceStrength.DIRECT,
            confidence_reason="Category A accounted for 62.4% of variance.",
            supporting_evidence=[
                EvidenceLink(
                    tool_name="run_variance_analysis",
                    metric="category_share",
                    source="sales",
                    value="62.4%",
                    contribution_pct=62.4,
                )
            ],
        )
    ]
    conclusions = EvidenceSynthesizer.synthesize_conclusions(hyp, obs)
    gaps = [
        EvidenceGap(
            description="Daily stockout logs not present.",
            missing_data="Historical daily inventory balances",
            impact="Cannot establish past stockout timeline.",
        )
    ]

    explanation = EvidenceSynthesizer.generate_explanation(plan, obs, hyp, conclusions, gaps)

    # Check all mandatory sections from prompt Section 21
    assert "### What happened" in explanation
    assert "### Main contributors" in explanation
    assert "### Supporting evidence" in explanation
    assert "### Other factors" in explanation
    assert "### What the data does not establish" in explanation
    assert "### Evidence gaps" in explanation
    assert "### Suggested next investigation" in explanation

    # Check that conclusions carry causality caveats
    assert len(conclusions) == 1
    assert "does not establish an isolated independent causal mechanism" in conclusions[0].causal_caveat
