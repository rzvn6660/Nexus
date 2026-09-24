"""Sale / Transaction ORM model for retail business domain."""

from datetime import datetime
from decimal import Decimal
from typing import List, TYPE_CHECKING
from sqlalchemy import String, DateTime, Numeric, ForeignKey, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.sale_item import SaleItem


class Sale(Base, TimestampMixin):
    """
    Represents an overarching order or retail transaction.
    
    Includes subtotal, aggregate discounts, tax, and final net total amount.
    All financial totals are stored as exact fixed-point Decimals.
    """

    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    transaction_number: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, doc="Invoice / receipt identifier"
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    transaction_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), index=True, default="completed", nullable=False, doc="Status: completed, pending, cancelled, refunded"
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, doc="Gross sum of line items before order-level discounts"
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False, doc="Order-level promotional discount"
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False, doc="Sales tax / VAT amount"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, doc="Final billed net total: subtotal - discount + tax"
    )

    # Relationships
    customer: Mapped["Customer"] = relationship("Customer", back_populates="sales")
    items: Mapped[List["SaleItem"]] = relationship(
        "SaleItem", back_populates="sale", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="chk_sales_subtotal_non_negative"),
        CheckConstraint("discount_amount >= 0", name="chk_sales_discount_non_negative"),
        CheckConstraint("tax_amount >= 0", name="chk_sales_tax_non_negative"),
        CheckConstraint("total_amount >= 0", name="chk_sales_total_non_negative"),
        Index("ix_sales_date_status", "transaction_date", "status"),
        Index("ix_sales_customer_date", "customer_id", "transaction_date"),
    )

    def __repr__(self) -> str:
        return f"<Sale(id={self.id}, tx='{self.transaction_number}', total={self.total_amount}, status='{self.status}')>"
