"""Core enumerations and constant types for the NEXUS Analytics Engine."""

from enum import Enum


class PeriodGranularity(str, Enum):
    """Time aggregation granularity."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class TrendDirection(str, Enum):
    """Direction of variance or growth comparison."""
    INCREASE = "increase"
    DECREASE = "decrease"
    UNCHANGED = "unchanged"
    UNDEFINED = "undefined"


class MetricUnit(str, Enum):
    """Measurement unit for business metrics."""
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    UNITS = "units"
    COUNT = "count"
    RATIO = "ratio"
    DAYS = "days"


class CorrelationMethod(str, Enum):
    """Statistical correlation algorithm."""
    PEARSON = "pearson"
    SPEARMAN = "spearman"


StatisticalMethod = CorrelationMethod


class HypothesisTestType(str, Enum):
    """Hypothesis test type for two-sample or group comparisons."""
    TWO_SAMPLE_TTEST = "two_sample_ttest"  # Welch's t-test (unequal variances assumed)
    MANN_WHITNEY_U = "mann_whitney_u"      # Non-parametric rank-sum test
    PAIRED_TTEST = "paired_ttest"


class SortOrder(str, Enum):
    """Sorting order."""
    ASC = "asc"
    DESC = "desc"
