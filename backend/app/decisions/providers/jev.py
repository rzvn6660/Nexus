"""Jev Decision Provider: System-1 discrete structured decision engine implementation."""

import logging
import os
import time
from typing import Any

from app.core.config import settings
from app.decisions.base import BaseDecisionProvider
from app.decisions.errors import (
    DecisionError,
    DecisionProviderUnavailableError,
    DecisionTimeoutError,
    DecisionValidationError,
    MalformedDecisionResponseError,
    UnsupportedDecisionTaskError,
)
from app.decisions.models import (
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionTask,
    DecisionTelemetry,
)

logger = logging.getLogger(__name__)

# Supported discrete decision tasks for Jev System-1
SUPPORTED_JEV_TASKS = {
    DecisionTask.INTENT_ROUTING.value,
    DecisionTask.TOOL_SELECTION.value,
    DecisionTask.EVIDENCE_SUFFICIENCY.value,
    DecisionTask.RISK_GATING.value,
    DecisionTask.RAG_RERANKING.value,
    DecisionTask.INVESTIGATION_ROUTING.value,
}


class JevDecisionProvider(BaseDecisionProvider):
    """
    Provider-independent adapter for TypeSafe AI's Jev System-1 decision model.
    
    Executes non-autoregressive, calibrated, typed decisions without text generation.
    Adapts Choice and Score primitives from typesafe-sdk to NEXUS DecisionResult.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        client: Any | None = None,
    ) -> None:
        self.api_key = (
            api_key
            or getattr(settings, "JEV_API_KEY", None)
            or os.environ.get("TYPESAFE_API_KEY")
            or os.environ.get("JEV_API_KEY")
        )
        self.model = model or getattr(settings, "JEV_MODEL", "jev-latest")
        self.timeout_seconds = timeout_seconds or getattr(settings, "DECISION_TIMEOUT_SECONDS", 10.0)

        if client is not None:
            self._client = client
        elif self.api_key:
            try:
                from typesafe_sdk import TypeSafeClient
                self._client = TypeSafeClient(
                    api_key=self.api_key,
                    model=self.model,
                    timeout=self.timeout_seconds,
                )
            except Exception as ex:
                logger.error(f"Failed to initialize TypeSafeClient for Jev: {ex}", exc_info=True)
                self._client = None
        else:
            self._client = None

    @property
    def provider_name(self) -> str:
        return "jev"

    def health_check(self) -> bool:
        """Verify whether the Jev client is initialized and ready for execution."""
        return self._client is not None

    def execute_decision(self, request: DecisionRequest) -> DecisionResult:
        """
        Execute a structured decision through Jev System-1.
        
        Strict Production Safety Rule:
        A failure or missing credentials in Jev must RAISE an explicit error.
        It must NEVER silently fall back to mock or Structured LLM.
        """
        if not self._client:
            raise DecisionProviderUnavailableError(
                "JevDecisionProvider is unavailable: TYPESAFE_API_KEY or JEV_API_KEY is not configured, "
                "or typesafe-sdk failed to initialize."
            )

        task_str = request.task.value if isinstance(request.task, DecisionTask) else str(request.task)

        if task_str not in SUPPORTED_JEV_TASKS:
            raise UnsupportedDecisionTaskError(
                f"Task '{task_str}' is not supported by JevDecisionProvider. "
                f"Supported tasks: {sorted(list(SUPPORTED_JEV_TASKS))}"
            )

        from typesafe_sdk import Choice, Score

        # Build task-specific Jev question and evaluation state
        state: dict[str, Any]
        question_key: str
        question: Any

        if task_str == DecisionTask.INTENT_ROUTING.value:
            candidates = request.candidate_options
            if not candidates:
                from app.agents.state.models import IntentCategory
                candidates = [e.value for e in IntentCategory]
            state = {"query": request.input_text, "context": request.context}
            question_key = "intent"
            question = Choice(
                instructions="Classify the analytical intent of the business query into the single most appropriate category.",
                criteria={c: None for c in candidates},
            )

        elif task_str == DecisionTask.TOOL_SELECTION.value:
            if not request.candidate_options:
                raise DecisionValidationError("candidate_options required for tool selection in Jev.")
            state = {"query": request.input_text, "context": request.context}
            question_key = "tool"
            question = Choice(
                instructions="Select the primary deterministic analytical tool required to answer the query.",
                criteria={t: None for t in request.candidate_options},
            )

        elif task_str == DecisionTask.EVIDENCE_SUFFICIENCY.value:
            candidates = request.candidate_options or ["SUFFICIENT", "PARTIAL", "INSUFFICIENT"]
            state = {
                "query": request.input_text,
                "evidence": request.context.get("evidence", []),
                "tool_results": request.context.get("tool_results", []),
            }
            question_key = "sufficiency"
            question = Choice(
                instructions="Determine if the retrieved evidence and tool execution results are sufficient to answer the business question.",
                criteria={c: None for c in candidates},
            )

        elif task_str == DecisionTask.RISK_GATING.value:
            candidates = request.candidate_options or ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
            state = {"recommendation": request.input_text, "context": request.context}
            question_key = "risk"
            question = Choice(
                instructions="Assess the business and financial risk of the proposed recommendation for human-in-the-loop review gating.",
                criteria={c: None for c in candidates},
            )

        elif task_str == DecisionTask.RAG_RERANKING.value:
            candidates = request.context.get("candidates", [])
            if not candidates:
                return DecisionResult(
                    task=task_str,
                    status=DecisionStatus.SUCCESS,
                    decision=None,
                    structured_output={"ranked_items": []},
                    telemetry=DecisionTelemetry(provider="jev", model=self.model, latency_ms=0.0),
                )
            candidate_ids = [c.get("chunk_id", str(i)) for i, c in enumerate(candidates)]
            state = {"query": request.input_text, "chunks": candidates}
            question_key = "top_chunk"
            question = Choice(
                instructions="Select the most relevant retrieved context chunk for the given user query.",
                criteria={cid: None for cid in candidate_ids},
            )

        elif task_str == DecisionTask.INVESTIGATION_ROUTING.value:
            candidates = request.candidate_options or [
                "revenue_decline_driver",
                "customer_churn_root_cause",
                "inventory_anomaly_diagnostic",
                "margin_variance_analysis",
            ]
            state = {"query": request.input_text, "context": request.context}
            question_key = "investigation_type"
            question = Choice(
                instructions="Select the most appropriate diagnostic investigation archetype for the anomaly.",
                criteria={c: None for c in candidates},
            )

        else:
            raise UnsupportedDecisionTaskError(f"Task '{task_str}' is not supported by Jev.")

        # Execute decision with latency profiling
        start_time = time.perf_counter()
        try:
            response = self._client.system_one(
                state=state,
                questions={question_key: question},
                model=self.model,
                timeout=self.timeout_seconds,
            )
        except DecisionError:
            raise
        except Exception as ex:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            ex_name = ex.__class__.__name__
            ex_str = str(ex).lower()

            logger.error(f"Jev execution error ({ex_name}) after {elapsed_ms}ms: {ex}", exc_info=True)

            if "timeout" in ex_name.lower() or "timeout" in ex_str or "timed out" in ex_str:
                raise DecisionTimeoutError(
                    f"Jev decision execution timed out after {self.timeout_seconds}s: {ex}"
                ) from ex
            if "validation" in ex_name.lower() or "malformed" in ex_str:
                raise MalformedDecisionResponseError(
                    f"Jev returned an invalid or malformed response: {ex}"
                ) from ex
            raise DecisionProviderUnavailableError(
                f"Jev decision execution failed ({ex_name}): {ex}"
            ) from ex

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Extract answer from response payload
        answers = getattr(response, "answers", {}) or {}
        answer = answers.get(question_key)

        if answer is None:
            raise MalformedDecisionResponseError(
                f"Jev response missing answer key '{question_key}' in response.answers: {list(answers.keys())}"
            )

        selected_decision = getattr(answer, "choice", None)
        if selected_decision is None and hasattr(answer, "score"):
            selected_decision = str(answer.score)

        # Honest confidence: calibrated probability from RLCD training, None if unavailable
        raw_confidence = getattr(answer, "confidence", None)
        confidence: float | None = None
        if raw_confidence is not None and isinstance(raw_confidence, (int, float)):
            confidence = max(0.0, min(1.0, float(raw_confidence)))

        # Telemetry: capture Jev tokens and version; cost is null (not fabricated)
        tokens_used: int | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        if hasattr(response, "usage") and response.usage:
            prompt_tokens = getattr(response.usage, "input_tokens", None)
            completion_tokens = getattr(response.usage, "output_tokens", None)
            if prompt_tokens is not None or completion_tokens is not None:
                tokens_used = (prompt_tokens or 0) + (completion_tokens or 0)

        resp_model = getattr(response, "model", None)
        model_name = resp_model if isinstance(resp_model, str) else self.model

        telemetry = DecisionTelemetry(
            provider="jev",
            model=model_name,
            latency_ms=elapsed_ms,
            tokens_used=tokens_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=None,  # Jev execution cost is not fabricated
            metadata={
                "jev_version": "0.7.1",
                "probabilities": getattr(answer, "probabilities", None),
                "scoring_legend": getattr(answer, "legend", None),
            },
        )

        # Enforce candidate option boundaries without silent substitution
        if request.candidate_options and selected_decision is not None:
            if selected_decision not in request.candidate_options:
                logger.warning(
                    f"Jev returned decision '{selected_decision}' not in allowed candidate_options: "
                    f"{request.candidate_options}"
                )
                return DecisionResult(
                    task=task_str,
                    status=DecisionStatus.DEGRADED,
                    decision=selected_decision,
                    structured_output={"decision": selected_decision, "confidence": confidence},
                    rationale=f"Jev returned unsupported decision outside allowed candidates.",
                    confidence=confidence,
                    telemetry=telemetry,
                    is_fallback=False,
                    error_message=(
                        f"Selected decision '{selected_decision}' is not in candidate_options: "
                        f"{request.candidate_options}"
                    ),
                )

        # Structure task-appropriate output payload
        if task_str == DecisionTask.TOOL_SELECTION.value:
            structured_output = {
                "selected_tools": [selected_decision] if selected_decision else [],
                "confidence": confidence,
            }
        elif task_str == DecisionTask.RAG_RERANKING.value:
            structured_output = {
                "ranked_items": [{"chunk_id": selected_decision, "score": confidence or 1.0}]
                if selected_decision
                else []
            }
        else:
            structured_output = {
                "decision": selected_decision,
                "confidence": confidence,
                "probabilities": getattr(answer, "probabilities", None),
            }

        return DecisionResult(
            task=task_str,
            status=DecisionStatus.SUCCESS,
            decision=selected_decision,
            structured_output=structured_output,
            rationale=f"Jev System-1 decision via {self.model}",
            confidence=confidence,
            telemetry=telemetry,
            is_fallback=False,
        )
