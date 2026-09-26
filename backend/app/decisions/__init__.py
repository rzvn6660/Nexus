"""NEXUS Decision Gateway Abstraction Package.

Provides provider-independent structured decision routing, scoring, ranking,
and gating across analytical and agent workflows.
"""

from app.decisions.base import BaseDecisionProvider
from app.decisions.errors import (
    DecisionError,
    DecisionProviderUnavailableError,
    DecisionTimeoutError,
    DecisionValidationError,
    InvalidDecisionProviderError,
    MalformedDecisionResponseError,
    UnsupportedDecisionTaskError,
)
from app.decisions.gateway import DecisionGateway, get_decision_gateway
from app.decisions.models import (
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionTask,
    DecisionTelemetry,
)
from app.decisions.providers.mock import MockDecisionProvider
from app.decisions.providers.structured_llm import StructuredLLMDecisionProvider

__all__ = [
    "BaseDecisionProvider",
    "DecisionError",
    "DecisionGateway",
    "DecisionProviderUnavailableError",
    "DecisionRequest",
    "DecisionResult",
    "DecisionStatus",
    "DecisionTask",
    "DecisionTelemetry",
    "DecisionTimeoutError",
    "DecisionValidationError",
    "InvalidDecisionProviderError",
    "MalformedDecisionResponseError",
    "MockDecisionProvider",
    "StructuredLLMDecisionProvider",
    "UnsupportedDecisionTaskError",
    "get_decision_gateway",
]
