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
    """Hypothesis test type for one-sample, two-sample, or group comparisons."""
    ONE_SAMPLE_TTEST = "one_sample_ttest"
    TWO_SAMPLE_TTEST = "two_sample_ttest"      # Welch's t-test (unequal variances assumed)
    STUDENT_TTEST = "student_ttest"            # Standard two-sample t-test (equal variances)
    PAIRED_TTEST = "paired_ttest"
    MANN_WHITNEY_U = "mann_whitney_u"          # Non-parametric rank-sum test
    WILCOXON_SIGNED_RANK = "wilcoxon_signed_rank"  # Non-parametric paired test
    ONE_WAY_ANOVA = "one_way_anova"            # Comparison across 3+ independent groups
    KRUSKAL_WALLIS = "kruskal_wallis"          # Non-parametric 3+ groups test
    CHI_SQUARE_INDEPENDENCE = "chi_square_independence"  # Contingency test for categorical variables
    TWO_PROPORTION_ZTEST = "two_proportion_ztest"        # Test of equal proportions


class EffectSizeMagnitude(str, Enum):
    """Standard qualitative interpretation of statistical effect sizes."""
    NEGLIGIBLE = "negligible"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class DistributionType(str, Enum):
    """Distribution shape characteristics."""
    APPROXIMATELY_NORMAL = "approximately_normal"
    RIGHT_SKEWED = "right_skewed"
    LEFT_SKEWED = "left_skewed"
    HEAVY_TAILED = "heavy_tailed"
    LIGHT_TAILED = "light_tailed"
    UNIFORM = "uniform"
    UNDEFINED = "undefined"


class OutlierMethod(str, Enum):
    """Statistical outlier detection methodology."""
    TUKEY_IQR = "tukey_iqr"
    Z_SCORE = "z_score"


class AnalyticalQuestionType(str, Enum):
    """Classification of business analytical inquiries for method selection."""
    DESCRIPTIVE_SUMMARY = "descriptive_summary"
    GROUP_COMPARISON = "group_comparison"
    PAIRED_COMPARISON = "paired_comparison"
    CATEGORICAL_ASSOCIATION = "categorical_association"
    PROPORTION_COMPARISON = "proportion_comparison"
    BIVARIATE_CORRELATION = "bivariate_correlation"
    MULTIVARIATE_REGRESSION = "multivariate_regression"
    TIME_SERIES_TREND = "time_series_trend"
    TIME_SERIES_SEASONALITY = "time_series_seasonality"
    TIME_SERIES_ANOMALY = "time_series_anomaly"
    PARETO_CONCENTRATION = "pareto_concentration"
    CUSTOMER_RFM = "customer_rfm"
    COHORT_RETENTION = "cohort_retention"
    VARIANCE_DECOMPOSITION = "variance_decomposition"


class ChartType(str, Enum):
    """Analytical chart archetypes strictly tied to analytical questions."""
    LINE = "line"
    BAR = "bar"
    HISTOGRAM = "histogram"
    BOX_PLOT = "box_plot"
    SCATTER = "scatter"
    HEATMAP = "heatmap"
    WATERFALL = "waterfall"
    COMPOSED_CORRIDOR = "composed_corridor"
    COHORT_MATRIX = "cohort_matrix"


class SortOrder(str, Enum):
    """Sorting order."""
    ASC = "asc"
    DESC = "desc"
