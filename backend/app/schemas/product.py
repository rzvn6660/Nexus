"""Pydantic schemas for Product domain entity."""

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class ProductBase(BaseModel):
    """Shared attributes for product schemas."""

    sku: str = Field(..., max_length=64, description="Unique SKU code")
    name: str = Field(..., max_length=255, description="Product catalog name")
    category: str = Field(..., max_length=128, description="Primary product category")
    subcategory: str = Field(..., max_length=128, description="Secondary product subcategory")
    unit_cost: Decimal = Field(..., ge=0, description="Cost of Goods Sold (COGS) per unit")
    selling_price: Decimal = Field(..., ge=0, description="Catalog unit selling price")
    active: bool = Field(True, description="Whether product is active for sales")


class ProductCreate(ProductBase):
    """Schema for product creation payloads."""

    pass


class ProductResponse(ProductBase):
    """Schema for product representation responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
