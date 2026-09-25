"""Validation, security guardrails, and causality safeguards for the Investigation Engine."""

import re

from pydantic import ValidationError

from app.agents.tools.registry import tool_registry
from app.investigation.models import InvestigationPlan, InvestigationStep

# Prohibited causal assertion patterns that fail causality safeguards
UNSUPPORTED_CAUSAL_PATTERNS = [
    r"\bcaused\b",
    r"\bproves?\s+(?:that\s+)?(?:\w+\s+)?caused\b",
    r"\bis\s+the\s+(?:root\s+)?cause\s+of\b",
    r"\bdirectly\s+caused\b",
    r"\bthe\s+sole\s+reason\s+for\b",
    r"\bproves?\s+causality\b",
]

# Prohibited prescriptive action patterns (strictly barred in Phase 6)
PRESCRIPTIVE_PATTERNS = [
    r"\b(?:you\s+should|we\s+should|recommend\s+to|must)\s+(?:raise|lower|reduce|increase|stop|cut|fire|discontinue|eliminate)\b",
    r"\braise\s+prices?\b",
    r"\breduce\s+(?:inventory|stock|prices?)\b",
    r"\bstop\s+selling\b",
    r"\bfire\s+supplier\b",
    r"\bincrease\s+discounts?\b",
]


class InvestigationValidator:
    """Validates investigation plans and enforces diagnostic safety invariants."""

    @staticmethod
    def validate_plan(plan: InvestigationPlan) -> tuple[bool, list[str]]:
        """
        Ensure plan is strictly bounded, uses only registered deterministic tools,
        and conforms to argument schemas.
        """
        errors: list[str] = []

        if not plan.steps:
            errors.append("Investigation plan has zero steps.")
            return False, errors

        if len(plan.steps) > plan.max_steps:
            errors.append(f"Investigation plan steps ({len(plan.steps)}) exceed maximum bound ({plan.max_steps}).")

        for step in plan.steps:
            valid, step_errs = InvestigationValidator.validate_step(step)
            if not valid:
                errors.extend(step_errs)

        return len(errors) == 0, errors

    @staticmethod
    def validate_step(step: InvestigationStep) -> tuple[bool, list[str]]:
        """Validate an individual investigative step against the deterministic tool registry."""
        errors: list[str] = []

        # Check tool registry presence
        if not tool_registry.has_tool(step.tool):
            errors.append(f"Security invariant violated: Tool '{step.tool}' is not registered.")
            return False, errors

        tool = tool_registry.get_tool(step.tool)
        if not tool:
            errors.append(f"Tool '{step.tool}' could not be resolved.")
            return False, errors

        # Validate arguments against Pydantic schema
        try:
            tool.input_schema.model_validate(step.arguments)
        except ValidationError as ve:
            errors.append(f"Argument schema validation failed for tool '{step.tool}': {ve}")

        # Validate date consistency if provided
        args = step.arguments
        if (
            args.get("date_from")
            and args.get("date_to")
            and str(args["date_from"]) > str(args["date_to"])
        ):
            errors.append(f"Invalid date interval: date_from ({args['date_from']}) > date_to ({args['date_to']})")

        return len(errors) == 0, errors


class CausalitySafeguard:
    """Enforces scientific boundaries between association/contribution and causality."""

    @staticmethod
    def check_causal_assertions(text: str) -> list[str]:
        """Identify instances of unsupported causal language in generated text."""
        findings: list[str] = []
        for pat in UNSUPPORTED_CAUSAL_PATTERNS:
            matches = re.findall(pat, text, re.IGNORECASE)
            if matches:
                findings.append(f"Disallowed causal claim detected matching pattern: '{pat}'")
        return findings

    @staticmethod
    def check_prescriptive_claims(text: str) -> list[str]:
        """Identify disallowed prescriptive recommendations in diagnostic explanations."""
        findings: list[str] = []
        for pat in PRESCRIPTIVE_PATTERNS:
            matches = re.findall(pat, text, re.IGNORECASE)
            if matches:
                findings.append(f"Disallowed prescriptive recommendation detected matching pattern: '{pat}'")
        return findings

    @staticmethod
    def sanitize_diagnostic_text(text: str) -> str:
        """
        Replace aggressive causal assertions with empirical contribution terminology.
        
        Example:
        'Category A caused the decline' -> 'Category A contributed to the decline'
        """
        sanitized = text
        # Replace 'caused' with 'contributed to'
        sanitized = re.sub(r"\bcaused\b", "contributed to", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r"\bdirectly caused\b", "was a primary contributor to", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r"\bis the root cause of\b", "is the largest measured contributor to", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r"\bthe sole reason for\b", "a significant factor in", sanitized, flags=re.IGNORECASE)
        return sanitized
