# Investigation Planning & Plan Lifecycle

## Core Principle
An investigation in NEXUS is never an open-ended loop or an unconstrained LLM thought process. Every investigation begins with a **structured, inspectable, bounded, and schema-validated InvestigationPlan**.

---

## Plan Structure
```json
{
  "goal": "Diagnose factors contributing to revenue decline: 'Why did revenue drop in August?'",
  "investigation_type": "revenue_decline",
  "baseline_dates": {
    "date_from": "2024-07-01",
    "date_to": "2024-07-31"
  },
  "comparison_dates": {
    "date_from": "2024-08-01",
    "date_to": "2024-08-31"
  },
  "steps": [
    {
      "step": 1,
      "purpose": "Establish macro revenue variance and period comparison baseline",
      "tool": "get_financial_summary",
      "arguments": {
        "date_from": "2024-08-01",
        "date_to": "2024-08-31",
        "comparison_date_from": "2024-07-01",
        "comparison_date_to": "2024-07-31"
      }
    },
    {
      "step": 2,
      "purpose": "Decompose revenue variance by merchandise category to identify primary contributors",
      "tool": "run_variance_analysis",
      "arguments": {
        "date_from": "2024-08-01",
        "date_to": "2024-08-31",
        "comparison_date_from": "2024-07-01",
        "comparison_date_to": "2024-07-31",
        "dimension": "category"
      }
    },
    {
      "step": 3,
      "purpose": "Decompose revenue change into Price Effect, Volume Effect, and Mix Effect",
      "tool": "run_price_volume_mix",
      "arguments": {
        "date_from": "2024-08-01",
        "date_to": "2024-08-31",
        "comparison_date_from": "2024-07-01",
        "comparison_date_to": "2024-07-31"
      }
    }
  ],
  "adaptive_branching_enabled": true,
  "max_steps": 8
}
```

---

## Plan Formulation Pipeline
1. **Archetype Classification**: `InvestigationPlanner.classify_investigation_type` inspects semantic metadata and natural language patterns.
2. **Temporal Alignment**: `InvestigationPlanner.resolve_comparison_dates` infers comparable baseline dates (e.g. preceding month or year) if the user supplied only one evaluation timeframe.
3. **Strategy Initialization**: The matching diagnostic strategy is instantiated.
4. **Step Construction**: Ordered sequence of deterministic analytics tools is prepared.
5. **Schema & Security Validation**: Every step is checked against `ToolRegistry` and its Pydantic input model.
