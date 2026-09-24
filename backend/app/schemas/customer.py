"""Pydantic schemas for Customer domain entity."""

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class CustomerBase(BaseModel):
    """Shared attributes for customer schemas."""

    customer_code: str = Field(..., max_length=32, description="Unique customer identifier code")
    name: str = Field(..., max_length=255, description="Full customer or business name")
    email: str = Field(..., max_length=255, description="Valid contact email address")

    phone: Optional[str] = Field(None, max_length=64, description="Contact phone number")
    city: str = Field(..., max_length=128, description="Primary city/location")
    customer_segment: str = Field(..., max_length=64, description="Segment: Retail, Wholesale, VIP, Corporate")
    acquisition_date: date = Field(..., description="Customer acquisition date")


class CustomerCreate(CustomerBase):
    """Schema for customer creation payloads."""

    pass


class CustomerResponse(CustomerBase):
    """Schema for customer representation responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
