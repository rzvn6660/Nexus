"""Registry and factory for diagnostic investigation strategies."""

from app.investigation.models import InvestigationType
from app.investigation.strategies.base import BaseInvestigationStrategy
from app.investigation.strategies.customer import CustomerInvestigationStrategy
from app.investigation.strategies.expense import ExpenseInvestigationStrategy
from app.investigation.strategies.generic import GenericDiagnosticStrategy
from app.investigation.strategies.inventory import InventoryInvestigationStrategy
from app.investigation.strategies.margin import MarginInvestigationStrategy
from app.investigation.strategies.product import ProductInvestigationStrategy
from app.investigation.strategies.profit import ProfitInvestigationStrategy
from app.investigation.strategies.revenue import RevenueInvestigationStrategy


def get_investigation_strategy(
    investigation_type: InvestigationType,
) -> BaseInvestigationStrategy:
    """Return the designated diagnostic strategy handler for an investigation type."""
    if investigation_type == InvestigationType.REVENUE_DECLINE:
        return RevenueInvestigationStrategy(is_decline=True)
    if investigation_type == InvestigationType.REVENUE_GROWTH:
        return RevenueInvestigationStrategy(is_decline=False)
    if investigation_type == InvestigationType.PROFIT_DECLINE:
        return ProfitInvestigationStrategy(is_decline=True)
    if investigation_type == InvestigationType.PROFIT_GROWTH:
        return ProfitInvestigationStrategy(is_decline=False)
    if investigation_type in (InvestigationType.MARGIN_CHANGE, InvestigationType.DISCOUNT_CHANGE):
        return MarginInvestigationStrategy()
    if investigation_type in (
        InvestigationType.PRODUCT_PERFORMANCE_CHANGE,
        InvestigationType.CATEGORY_PERFORMANCE_CHANGE,
        InvestigationType.SALES_CHANGE,
    ):
        return ProductInvestigationStrategy()
    if investigation_type == InvestigationType.CUSTOMER_CHANGE:
        return CustomerInvestigationStrategy()
    if investigation_type == InvestigationType.INVENTORY_ISSUE:
        return InventoryInvestigationStrategy()
    if investigation_type == InvestigationType.EXPENSE_CHANGE:
        return ExpenseInvestigationStrategy()

    return GenericDiagnosticStrategy()


__all__ = [
    "BaseInvestigationStrategy",
    "CustomerInvestigationStrategy",
    "ExpenseInvestigationStrategy",
    "GenericDiagnosticStrategy",
    "InventoryInvestigationStrategy",
    "MarginInvestigationStrategy",
    "ProductInvestigationStrategy",
    "ProfitInvestigationStrategy",
    "RevenueInvestigationStrategy",
    "get_investigation_strategy",
]
