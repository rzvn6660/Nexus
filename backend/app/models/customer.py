"""Customer ORM model for retail business domain."""

from datetime import date
from typing import List, TYPE_CHECKING
from sqlalchemy import String, Date, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
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
    customer_code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False, doc="Unique external business identifier"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    city: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    customer_segment: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, doc="Segment: Retail, Wholesale, VIP, Corporate"
    )
    acquisition_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)

    # Relationships
    sales: Mapped[List["Sale"]] = relationship(
        "Sale", back_populates="customer", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_customers_segment_city", "customer_segment", "city"),
    )

    def __repr__(self) -> str:
        return f"<Customer(id={self.id}, code='{self.customer_code}', name='{self.name}', segment='{self.customer_segment}')>"
