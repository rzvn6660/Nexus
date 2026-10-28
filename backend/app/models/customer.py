"""Customer ORM model for retail business domain."""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.sale import Sale


class Customer(Base, TimestampMixin):
    """
    Represents an individual or corporate buyer in the retail/distribution business.
    
    Customers belong to distinct market segments (Retail, Wholesale, VIP, Corporate)
    which drive purchasing volume and discount patterns.
    """

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    business_id: Mapped[str | None] = mapped_column(
        String(36), index=True, nullable=True, doc="Tenant business ownership"
    )
    customer_code: Mapped[str] = mapped_column(
        String(32), index=True, nullable=False, doc="Unique external business identifier within tenant"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255), index=True, nullable=False, doc="Contact email address within tenant"
    )
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    city: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    customer_segment: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, doc="Segment: Retail, Wholesale, VIP, Corporate"
    )
    acquisition_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)

    # Relationships
    sales: Mapped[list["Sale"]] = relationship(
        "Sale", back_populates="customer", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_customers_segment_city", "customer_segment", "city"),
        UniqueConstraint("business_id", "customer_code", name="uq_customers_business_customer_code"),
        UniqueConstraint("business_id", "email", name="uq_customers_business_email"),
    )

    @validates("customer_code")
    def validate_customer_code(self, key: str, value: str | None) -> str | None:
        """Trim whitespace from customer code; preserves None for unassigned inputs."""
        if value is None:
            return None
        return str(value).strip()

    @validates("email")
    def validate_email(self, key: str, value: str | None) -> str | None:
        """Trim whitespace and lowercase email; preserves None for unassigned inputs."""
        if value is None:
            return None
        return str(value).strip().lower()

    def __repr__(self) -> str:
        return f"<Customer(id={self.id}, code='{self.customer_code}', name='{self.name}', segment='{self.customer_segment}')>"
