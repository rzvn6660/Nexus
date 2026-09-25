"""Evidence synthesis and diagnostic narrative formulation with strict causality safeguards."""


from app.investigation.models import (
    EvidenceGap,
    EvidenceStrength,
    HypothesisStatus,
    InvestigationConclusion,
    InvestigationHypothesis,
    InvestigationObservation,
    InvestigationPlan,
)
from app.investigation.validators import CausalitySafeguard


class EvidenceSynthesizer:
    """
    Synthesizes empirical observations and tested hypotheses into audited diagnostic conclusions
    and structured, human-readable explanations.
    """

    @classmethod
    def synthesize_conclusions(
        cls,
        hypotheses: list[InvestigationHypothesis],
        observations: list[InvestigationObservation],
    ) -> list[InvestigationConclusion]:
        """Derive explicit, audited diagnostic conclusions with causality caveats."""
        conclusions: list[InvestigationConclusion] = []
        idx = 1

        for h in hypotheses:
            if h.status in (HypothesisStatus.SUPPORTED, HypothesisStatus.PARTIALLY_SUPPORTED):
                share = None
                tools: list[str] = []
                for ev in h.supporting_evidence:
                    tools.append(ev.tool_name)
                    if ev.contribution_pct is not None:
                        share = ev.contribution_pct

                tools = sorted(set(tools))
                caveat = (
                    "Contribution and association measure derived from deterministic decomposition; "
                    "does not establish an isolated independent causal mechanism."
                )

                statement = (
                    f"{h.statement} ({h.confidence_reason})"
                    if h.confidence_reason
                    else h.statement
                )

                # Ensure language is sanitized
                sanitized_statement = CausalitySafeguard.sanitize_diagnostic_text(statement)

                conclusions.append(
                    InvestigationConclusion(
                        id=f"CONC-{idx}",
                        statement=sanitized_statement,
                        hypothesis_id=h.id,
                        strength=h.evidence_strength,
                        supporting_tools=tools,
                        contribution_share_pct=share,
                        causal_caveat=caveat,
                    )
                )
                idx += 1

        return conclusions

    @classmethod
    def generate_explanation(
        cls,
        plan: InvestigationPlan,
        observations: list[InvestigationObservation],
        hypotheses: list[InvestigationHypothesis],
        conclusions: list[InvestigationConclusion],
        evidence_gaps: list[EvidenceGap],
        rag_context_text: str | None = None,
    ) -> str:
        """
        Formulate a grounded diagnostic narrative adhering strictly to the Section 21 schema:
        - ### What happened
        - ### Main contributors
        - ### Supporting evidence
        - ### Other factors
        - ### What the data does not establish
        - ### Evidence gaps
        - ### Suggested next investigation
        """
        sections: list[str] = []

        # 1. ### What happened
        what_happened_lines: list[str] = []
        for obs in observations:
            what_happened_lines.append(f"- {obs.statement}")
        if not what_happened_lines:
            what_happened_lines.append(f"- Investigated: {plan.goal}.")
        sections.append("### What happened\n" + "\n".join(what_happened_lines))

        # 2. ### Main contributors
        main_contrib_lines: list[str] = []
        for c in conclusions:
            if c.strength in (EvidenceStrength.DIRECT, EvidenceStrength.STRONG):
                pct_str = f" ({c.contribution_share_pct:.1f}% share)" if c.contribution_share_pct is not None else ""
                main_contrib_lines.append(f"- {c.statement}{pct_str}")
        if not main_contrib_lines:
            main_contrib_lines.append("- No single dominant factor accounted for the variance; changes were distributed across multiple areas.")
        sections.append("### Main contributors\n" + "\n".join(main_contrib_lines))

        # 3. ### Supporting evidence
        evidence_lines: list[str] = []
        for h in hypotheses:
            for ev in h.supporting_evidence:
                evidence_lines.append(f"- [{ev.tool_name}] {ev.notes or ev.value}")
        if not evidence_lines:
            evidence_lines.append("- Empirical tool outputs provided baseline telemetry without statistical concentration.")
        sections.append("### Supporting evidence\n" + "\n".join(evidence_lines))

        # 4. ### Other factors
        other_lines: list[str] = []
        for h in hypotheses:
            if h.status == HypothesisStatus.NOT_SUPPORTED:
                other_lines.append(f"- [Evaluated & Ruled Out] {h.statement} ({h.confidence_reason})")
            elif h.status == HypothesisStatus.PARTIALLY_SUPPORTED:
                other_lines.append(f"- [Secondary Contributor] {h.statement} ({h.confidence_reason})")
        if not other_lines:
            other_lines.append("- Secondary and counter-hypotheses showed negligible deviation.")
        sections.append("### Other factors\n" + "\n".join(other_lines))

        # 5. ### What the data does not establish
        causal_disclaimer_lines: list[str] = [
            "- The available transactional records establish empirical contributions and mathematical variance shares, but do NOT prove independent causal mechanisms.",
            "- Statistical association or high contribution percentages should not be interpreted as proving that a single department, category, or pricing policy unilaterally created the change.",
        ]
        sections.append("### What the data does not establish\n" + "\n".join(causal_disclaimer_lines))

        # 6. ### Evidence gaps
        gap_lines: list[str] = []
        for g in evidence_gaps:
            gap_lines.append(f"- {g.description} (Missing: {g.missing_data}. Impact: {g.impact})")
        if not gap_lines:
            gap_lines.append("- No critical internal transactional data gaps were encountered during this analysis.")
        sections.append("### Evidence gaps\n" + "\n".join(gap_lines))

        # 7. ### Suggested next investigation (NO PRESCRIPTIVE RECOMMENDATIONS)
        next_steps_lines: list[str] = []
        if conclusions:
            top_conc = conclusions[0]
            next_steps_lines.append(
                f"- Drill deeper into the specific SKU lines, customer cohorts, or operational units linked to: {top_conc.statement.split('(')[0].strip()}."
            )
        next_steps_lines.append("- Review related period-over-period category mix and inventory turnover trends.")
        sections.append("### Suggested next investigation\n" + "\n".join(next_steps_lines))

        # 8. Business Context Reference if available
        if rag_context_text:
            sections.append(f"### Relevant Business Policy Context\n{rag_context_text.strip()}")

        full_text = "\n\n".join(sections)
        sanitized = CausalitySafeguard.sanitize_diagnostic_text(full_text)
        return sanitized
