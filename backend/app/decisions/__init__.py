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
from app.decisions.providers.jev import JevDecisionProvider
from app.decisions.providers.mock import MockDecisionProvider
from app.decisions.providers.structured_llm import StructuredLLMDecisionProvider
from app.decisions.taxonomy import (
    CANONICAL_INTENT_DEFINITIONS,
    CanonicalIntent,
    IntentDefinition,
    get_canonical_intent_ids,
    resolve_intent,
    resolve_tool,
    validate_intent_id,
)

__all__ = [
    "BaseDecisionProvider",
    "CANONICAL_INTENT_DEFINITIONS",
    "CanonicalIntent",
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
    "IntentDefinition",
    "InvalidDecisionProviderError",
    "JevDecisionProvider",
    "MalformedDecisionResponseError",
    "MockDecisionProvider",
    "StructuredLLMDecisionProvider",
    "UnsupportedDecisionTaskError",
    "get_canonical_intent_ids",
    "get_decision_gateway",
    "resolve_intent",
    "resolve_tool",
    "validate_intent_id",
]
