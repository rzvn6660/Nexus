"""Expense ORM model tracking operational overhead and business expenditures."""

from datetime import date
from decimal import Decimal
from sqlalchemy import String, Date, Boolean, Numeric, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class Expense(Base, TimestampMixin):
    """
    Represents an operational expense incurred by the business.
    
    Includes category classification (Rent, Payroll, Logistics, Utilities, Marketing),
    recurrence status, and exact monetary amount.
    """

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    expense_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    category: Mapped[str] = mapped_column(
        String(128), index=True, nullable=False, doc="Category: Rent, Utilities, Payroll, Marketing, Logistics, Supplies"
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, doc="Monetary cost incurred in currency units"
    )
    recurring: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, doc="True if predictable recurring operational overhead"
    )

    __table_args__ = (
        CheckConstraint("amount >= 0", name="chk_expense_amount_non_negative"),
        Index("ix_expenses_category_date", "category", "expense_date"),
    )

    def __repr__(self) -> str:
        return f"<Expense(id={self.id}, date={self.expense_date}, category='{self.category}', amount={self.amount})>"
