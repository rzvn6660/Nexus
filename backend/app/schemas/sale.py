"""Pydantic schemas for Sale and SaleItem domain entities."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SaleItemBase(BaseModel):
    """Shared attributes for sale line items."""

    product_id: int = Field(..., description="Foreign key to product entity")
    quantity: int = Field(..., gt=0, description="Quantity purchased (strictly positive)")
    unit_price: Decimal = Field(..., ge=0, description="Unit price at transaction time")
    discount_amount: Decimal = Field(Decimal("0.00"), ge=0, description="Line discount amount")
    line_total: Decimal = Field(..., ge=0, description="Net line total: qty * price - discount")


class SaleItemCreate(SaleItemBase):
    """Schema for creating a sale line item."""

    pass


class SaleItemResponse(SaleItemBase):
    """Schema for returning sale item details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sale_id: int
    created_at: datetime
    updated_at: datetime


class SaleBase(BaseModel):
    """Shared attributes for sale order transactions."""

    transaction_number: str = Field(..., max_length=64, description="Unique transaction invoice number")
    customer_id: int = Field(..., description="Foreign key to purchasing customer")
    transaction_date: datetime = Field(..., description="Timestamp when transaction occurred")
    status: str = Field("completed", max_length=32, description="Status: completed, pending, cancelled, refunded")
    subtotal: Decimal = Field(..., ge=0, description="Sum of line items before order discounts")
    discount_amount: Decimal = Field(Decimal("0.00"), ge=0, description="Order level discount")
    tax_amount: Decimal = Field(Decimal("0.00"), ge=0, description="Order level tax amount")
    total_amount: Decimal = Field(..., ge=0, description="Final billed net total")


class SaleCreate(SaleBase):
    """Schema for creating a sale with its line items."""

    items: List[SaleItemCreate] = Field(..., min_length=1, description="Associated transaction line items")


class SaleResponse(SaleBase):
    """Schema for returning sale header details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class SaleWithItemsResponse(SaleResponse):
    """Schema for returning sale header along with item details."""

    items: List[SaleItemResponse] = Field(default_factory=list)
