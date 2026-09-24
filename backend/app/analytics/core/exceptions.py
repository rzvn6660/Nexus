"""Custom exceptions for the NEXUS Analytics Engine."""


class AnalyticsError(Exception):
    """Base exception for analytical operations."""
    pass


class InsufficientDataError(AnalyticsError):
    """Raised when data volume or sample size is insufficient for a valid computation."""
    pass


class InvalidContextError(AnalyticsError):
    """Raised when an AnalysisContext has invalid, conflicting, or inverted parameters."""
    pass


class UndefinedMetricError(AnalyticsError):
    """Raised when a requested metric is not recognized or cannot be computed."""
    pass


class DecompositionError(AnalyticsError):
    """Raised when mathematical decomposition cannot be computed due to missing cross-period entities."""
    pass
