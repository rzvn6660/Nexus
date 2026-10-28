"""Pydantic schemas for Customer domain entity."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CustomerBase(BaseModel):
    """Shared attributes for customer schemas."""

    customer_code: str = Field(..., max_length=32, description="Unique customer identifier code")
    name: str = Field(..., max_length=255, description="Full customer or business name")
    email: str = Field(..., max_length=255, description="Valid contact email address")

    phone: str | None = Field(None, max_length=64, description="Contact phone number")
    city: str = Field(..., max_length=128, description="Primary city/location")
    customer_segment: str = Field(..., max_length=64, description="Segment: Retail, Wholesale, VIP, Corporate")
    acquisition_date: date = Field(..., description="Customer acquisition date")

    @field_validator("customer_code", mode="before")
    @classmethod
    def normalize_code(cls, v: str | None) -> str | None:
        if v is not None:
            return str(v).strip()
        return v

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str | None) -> str | None:
        if v is not None:
            return str(v).strip().lower()
        return v


class CustomerCreate(CustomerBase):
    """Schema for customer creation payloads."""



class CustomerResponse(CustomerBase):
    """Schema for customer representation responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
