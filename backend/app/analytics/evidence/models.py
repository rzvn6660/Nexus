"""EvidenceRecord schema ensuring full auditability and traceability for all analytical outputs."""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import uuid4
from pydantic import BaseModel, Field


class EvidenceRecord(BaseModel):
    """
    Structured evidence metadata attached to every major analytical calculation.
    
    Provides complete provenance so downstream components (including future LangGraph agents)
    can trace:
    - What was computed
    - The mathematical formula utilized
    - The underlying tables and columns accessed
    - Applied filters and temporal ranges
    - Assumptions, constraints, and statistical limitations
    """
    analysis_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique execution identifier for this analytical calculation"
    )
    metric: str = Field(description="Name or key of the primary metric analyzed")
    source_tables: List[str] = Field(
        default_factory=list,
        description="Database tables queried to derive this metric"
    )
    source_columns: List[str] = Field(
        default_factory=list,
        description="Specific columns accessed during calculation"
    )
    filters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Active filter parameters applied (e.g. status, customer_ids, categories)"
    )
    date_range: Dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="Primary analysis time interval (start, end)"
    )
    comparison_period: Optional[Dict[str, Optional[str]]] = Field(
        default=None,
        description="Comparison baseline interval (start, end), if applicable"
    )
    calculation: str = Field(
        description="Exact human-readable mathematical formula or SQL aggregation rule"
    )
    method: str = Field(
        default="deterministic_sql_aggregation",
        description="Computation engine / method (e.g. 'SQL_SUM', 'WELCH_TTEST', 'RFM_QUANTILES')"
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description="Underlying domain assumptions (e.g. 'Tax excluded from revenue', 'COGS uses current unit_cost')"
    )
    data_quality_status: str = Field(
        default="verified",
        description="Data quality status: verified, warning, or unverified"
    )
    limitations: List[str] = Field(
        default_factory=list,
        description="Known limitations or caveats for business interpretation"
    )
    result_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Key output values for quick reference"
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the calculation was evaluated"
    )
