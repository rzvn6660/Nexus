"""DecisionGateway: Central provider-independent entrypoint for structured decisions."""

import logging
from typing import Any

from app.core.config import settings
from app.decisions.base import BaseDecisionProvider
from app.decisions.errors import (
    DecisionError,
    DecisionValidationError,
    InvalidDecisionProviderError,
)
from app.decisions.models import (
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionTask,
)
from app.decisions.providers.mock import MockDecisionProvider
from app.decisions.providers.structured_llm import StructuredLLMDecisionProvider

logger = logging.getLogger(__name__)


class DecisionGateway:
    """
    Central orchestration gateway for structured business decisions in NEXUS.
    
    Decouples analytical and agentic callers from specific AI or decision backends.
    Validates requests, routes to the configured provider, records telemetry,
    and enforces strict verification over candidate outputs.
    """

    def __init__(self, provider: BaseDecisionProvider | None = None, provider_name: str | None = None) -> None:
        if provider:
            self._provider = provider
        else:
            self._provider = self._resolve_provider(provider_name)

    @property
    def active_provider(self) -> BaseDecisionProvider:
        """Return the active underlying decision provider."""
        return self._provider

    @property
    def provider_name(self) -> str:
        """Name of the active provider."""
        return self._provider.provider_name

    def decide(self, request: DecisionRequest) -> DecisionResult:
        """
        Execute a structured decision request through the configured provider.
        
        Validates request parameters, calls provider, validates candidate constraints,
        and returns a standardized DecisionResult.
        """
        if not request.input_text and not request.context:
            raise DecisionValidationError("DecisionRequest must provide either input_text or context.")

        try:
            result = self._provider.execute_decision(request)
        except DecisionError:
            # Re-raise normalized decision errors without wrapping
            raise
        except Exception as ex:
            logger.error(f"Unexpected error in decision provider '{self.provider_name}': {ex}", exc_info=True)
            raise DecisionError(f"Unexpected decision execution failure: {ex}") from ex

        # Validate candidate options constraints if specified
        if request.candidate_options and result.decision is not None:
            if result.decision not in request.candidate_options:
                logger.warning(
                    f"Provider '{self.provider_name}' produced decision '{result.decision}' "
                    f"not in candidate_options: {request.candidate_options}"
                )
                result.status = DecisionStatus.DEGRADED
                result.error_message = (
                    f"Selected decision '{result.decision}' was not in candidate_options: {request.candidate_options}"
                )

        return result

    # ------------------------------------------------------------------
    # High-level convenience methods for common NEXUS decision tasks
    # ------------------------------------------------------------------

    def route_intent(
        self,
        query: str,
        candidate_intents: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DecisionResult:
        """Route user natural language query to an analytical intent category."""
        if not candidate_intents:
            from app.decisions.taxonomy import get_canonical_intent_ids
            candidate_intents = get_canonical_intent_ids()

        req = DecisionRequest(
            task=DecisionTask.INTENT_ROUTING,
            input_text=query,
            candidate_options=candidate_intents,
            metadata=metadata or {},
        )
        return self.decide(req)

    def select_tools(
        self,
        query: str,
        available_tools: list[str],
        context: dict[str, Any] | None = None,
    ) -> DecisionResult:
        """Select relevant deterministic tools to answer the business question."""
        req = DecisionRequest(
            task=DecisionTask.TOOL_SELECTION,
            input_text=query,
            context=context or {},
            candidate_options=available_tools,
        )
        return self.decide(req)

    def rerank_context(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 3,
    ) -> DecisionResult:
        """Rerank retrieved RAG business context chunks by relevance."""
        req = DecisionRequest(
            task=DecisionTask.RAG_RERANKING,
            input_text=query,
            context={"candidates": candidates},
            constraints={"top_k": top_k},
        )
        return self.decide(req)

    def evaluate_evidence(
        self,
        query: str,
        evidence: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
    ) -> DecisionResult:
        """Evaluate evidence sufficiency and relevance against user question."""
        req = DecisionRequest(
            task=DecisionTask.EVIDENCE_SUFFICIENCY,
            input_text=query,
            context={
                "evidence": evidence,
                "tool_results": tool_results,
            },
            candidate_options=["SUFFICIENT", "PARTIAL", "INSUFFICIENT"],
        )
        return self.decide(req)

    def assess_risk(
        self,
        recommendation: str,
        context: dict[str, Any] | None = None,
    ) -> DecisionResult:
        """Score decision risk for Human-in-the-Loop review gating."""
        req = DecisionRequest(
            task=DecisionTask.RISK_GATING,
            input_text=recommendation,
            context=context or {},
            candidate_options=["LOW", "MEDIUM", "HIGH", "CRITICAL"],
        )
        return self.decide(req)

    # ------------------------------------------------------------------
    # Internal factory resolution
    # ------------------------------------------------------------------

    @classmethod
    def _resolve_provider(cls, requested_name: str | None = None) -> BaseDecisionProvider:
        """
        Instantiate configured decision provider with explicit test/dev environment isolation.

        Strict Production Safety Rule:
        - In production, configured live providers (e.g. structured_llm) must never silently fall back
          to mock. If credentials or services fail, explicit errors are raised.
        - In test environments (pytest, APP_ENV == 'test') or local dev without configured API keys,
          the deterministic MockDecisionProvider is explicitly resolved.
        """
        import os
        import sys

        is_test_env = (
            "pytest" in sys.modules
            or "PYTEST_CURRENT_TEST" in os.environ
            or getattr(settings, "APP_ENV", "").lower() == "test"
        )

        name = (requested_name or getattr(settings, "DECISION_PROVIDER", "structured_llm")).lower().strip()

        # If explicitly requested 'mock' or running in test suite without an explicit provider override
        if name == "mock" or (is_test_env and requested_name is None):
            return MockDecisionProvider()

        # If in local dev without an API key and no explicit provider requested
        if (
            requested_name is None
            and not settings.is_production
            and not getattr(settings, "OPENAI_API_KEY", None)
        ):
            logger.info("Using MockDecisionProvider for local development (no OPENAI_API_KEY configured).")
            return MockDecisionProvider()

        if name == "structured_llm":
            return StructuredLLMDecisionProvider()

        if name == "jev":
            from app.decisions.providers.jev import JevDecisionProvider
            return JevDecisionProvider()

        raise InvalidDecisionProviderError(
            f"Unknown decision provider '{name}'. Configured provider must be one of: ['structured_llm', 'mock', 'jev']."
        )


# Global default gateway accessor
_gateway_instance: DecisionGateway | None = None


def get_decision_gateway(provider_name: str | None = None, force_new: bool = False) -> DecisionGateway:
    """Return singleton or configured instance of DecisionGateway."""
    global _gateway_instance
    if _gateway_instance is None or force_new or provider_name is not None:
        instance = DecisionGateway(provider_name=provider_name)
        if provider_name is None and not force_new:
            _gateway_instance = instance
        return instance
    return _gateway_instance
