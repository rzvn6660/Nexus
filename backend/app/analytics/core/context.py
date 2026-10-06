"""Analysis context and filter specifications for the NEXUS Analytics Engine."""

from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, model_validator
from app.analytics.core.types import PeriodGranularity
from app.analytics.core.exceptions import InvalidContextError


CURRENCY_SYMBOLS: Dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "INR": "₹",
    "CAD": "CA$",
    "AUD": "A$",
    "JPY": "¥",
    "CHF": "CHF",
    "CNY": "¥",
}


def resolve_currency_symbol(currency_code_or_symbol: Optional[str]) -> str:
    if not currency_code_or_symbol:
        return "$"
    code = currency_code_or_symbol.strip().upper()
    if code in CURRENCY_SYMBOLS:
        return CURRENCY_SYMBOLS[code]
    if currency_code_or_symbol in ("$", "₹", "€", "£", "¥"):
        return currency_code_or_symbol
    return "$"


class AnalysisContext(BaseModel):
    """
    Standardized, strongly-typed filter context governing all deterministic calculations.
    
    Prevents ad-hoc dict passing and guarantees consistent boundary enforcement across
    metrics, time-series, segmentation, and diagnostic decompositions.
    """
    business_id: Optional[str] = Field(
        default=None,
        description="Tenant business workspace boundary"
    )
    currency: Optional[str] = Field(
        default="USD",
        description="Operational currency code (e.g. USD, INR, EUR)"
    )
    currency_symbol: Optional[str] = Field(
        default="$",
        description="Currency display symbol (e.g. $, ₹, €)"
    )
    date_from: Optional[datetime] = Field(
        default=None,
        description="Inclusive start timestamp of the primary evaluation window (UTC)"
    )
    date_to: Optional[datetime] = Field(
        default=None,
        description="Inclusive end timestamp of the primary evaluation window (UTC)"
    )
    comparison_date_from: Optional[datetime] = Field(
        default=None,
        description="Start timestamp of comparison baseline period (e.g. prior month/year)"
    )
    comparison_date_to: Optional[datetime] = Field(
        default=None,
        description="End timestamp of comparison baseline period"
    )
    customer_ids: Optional[List[int]] = Field(
        default=None,
        description="Optional filter restricted to specific customer IDs"
    )
    product_ids: Optional[List[int]] = Field(
        default=None,
        description="Optional filter restricted to specific product IDs"
    )
    categories: Optional[List[str]] = Field(
        default=None,
        description="Optional filter restricted to specific product categories"
    )
    subcategories: Optional[List[str]] = Field(
        default=None,
        description="Optional filter restricted to specific product subcategories"
    )
    customer_segments: Optional[List[str]] = Field(
        default=None,
        description="Optional filter restricted to customer segments (e.g. Retail, Wholesale, Corporate, VIP)"
    )
    statuses: Optional[List[str]] = Field(
        default_factory=lambda: ["completed", "shipped"],
        description="Transaction statuses to include (default: completed, shipped; excludes cancelled/pending)"
    )
    granularity: PeriodGranularity = Field(
        default=PeriodGranularity.MONTHLY,
        description="Temporal aggregation bucket size"
    )

    @model_validator(mode="after")
    def sync_currency_symbol(self) -> "AnalysisContext":
        if self.currency and (not self.currency_symbol or self.currency_symbol == "$" and self.currency.upper() != "USD"):
            object.__setattr__(self, "currency_symbol", resolve_currency_symbol(self.currency))
        return self

    @model_validator(mode="after")
    def validate_date_intervals(self) -> "AnalysisContext":
        """Verify that date intervals are chronologically valid."""
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise InvalidContextError(
                f"date_from ({self.date_from}) cannot be after date_to ({self.date_to})"
            )
        if (
            self.comparison_date_from
            and self.comparison_date_to
            and self.comparison_date_from > self.comparison_date_to
        ):
            raise InvalidContextError(
                f"comparison_date_from ({self.comparison_date_from}) cannot be after comparison_date_to ({self.comparison_date_to})"
            )
        return self

    @property
    def has_comparison(self) -> bool:
        """True if comparison interval boundaries are defined."""
        return self.comparison_date_from is not None and self.comparison_date_to is not None

    def to_filter_dict(self) -> Dict[str, Any]:
        """Produce a clean JSON-serializable dictionary representation of active filters."""
        res: Dict[str, Any] = {}
        if self.business_id:
            res["business_id"] = self.business_id
        if self.date_from:
            res["date_from"] = self.date_from.isoformat()
        if self.date_to:
            res["date_to"] = self.date_to.isoformat()
        if self.comparison_date_from:
            res["comparison_date_from"] = self.comparison_date_from.isoformat()
        if self.comparison_date_to:
            res["comparison_date_to"] = self.comparison_date_to.isoformat()
        if self.customer_ids:
            res["customer_ids"] = self.customer_ids
        if self.product_ids:
            res["product_ids"] = self.product_ids
        if self.categories:
            res["categories"] = self.categories
        if self.subcategories:
            res["subcategories"] = self.subcategories
        if self.customer_segments:
            res["customer_segments"] = self.customer_segments
        if self.statuses:
            res["statuses"] = self.statuses
        res["granularity"] = self.granularity.value
        return res
