"""Pydantic schemas for Expense domain entity."""

from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class ExpenseBase(BaseModel):
    """Shared attributes for expense schemas."""

    expense_date: date = Field(..., description="Date expense was incurred")
    category: str = Field(..., max_length=128, description="Expense category (Rent, Payroll, Logistics, etc.)")
    description: str = Field(..., max_length=255, description="Description of expenditure")
    amount: Decimal = Field(..., ge=0, description="Amount spent in currency units")
    recurring: bool = Field(False, description="Whether expense is predictable recurring operational overhead")


class ExpenseCreate(ExpenseBase):
    """Schema for creating an expense record."""

    pass


class ExpenseResponse(ExpenseBase):
    """Schema for returning expense details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
