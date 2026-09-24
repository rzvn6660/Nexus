"""Pydantic schemas for Inventory domain entity."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class InventoryBase(BaseModel):
    """Shared attributes for inventory schemas."""

    product_id: int = Field(..., description="Foreign key to product entity")
    stock_quantity: int = Field(..., ge=0, description="Available stock quantity units")
    reorder_threshold: int = Field(10, ge=0, description="Minimum stock threshold triggering reorder")
    warehouse_location: str = Field("Main Warehouse", max_length=128, description="Warehouse storage location")


class InventoryCreate(InventoryBase):
    """Schema for creating an inventory record."""

    pass


class InventoryResponse(InventoryBase):
    """Schema for returning inventory details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
