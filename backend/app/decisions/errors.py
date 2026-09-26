"""Exception hierarchy for the NEXUS Decision Gateway abstraction."""

class DecisionError(Exception):
    """Base exception for all decision gateway errors."""
    pass


class InvalidDecisionProviderError(DecisionError):
    """Raised when an unconfigured or unknown decision provider is requested."""
    pass


class DecisionProviderUnavailableError(DecisionError):
    """Raised when a configured provider is unreachable, lacks credentials, or is offline in production."""
    pass


class DecisionTimeoutError(DecisionError):
    """Raised when a decision request exceeds its allotted execution deadline."""
    pass


class MalformedDecisionResponseError(DecisionError):
    """Raised when a provider returns a payload that cannot be parsed into the expected decision schema."""
    pass


class DecisionValidationError(DecisionError):
    """Raised when a decision result fails semantic or schema validation rules."""
    pass


class UnsupportedDecisionTaskError(DecisionError):
    """Raised when a provider does not support the requested decision task."""
    pass
