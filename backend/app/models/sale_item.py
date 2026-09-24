"""SaleItem ORM model representing individual transaction line items."""

from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy import Integer, Numeric, ForeignKey, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.sale import Sale
    from app.models.product import Product


class SaleItem(Base, TimestampMixin):
    """
    Represents an individual product line item within a sale transaction.
    
    Line total reconciles with quantity * unit_price - discount_amount.
    Quantity is constrained to strictly positive integers.
    """

    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, doc="Units purchased in this transaction line"
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, doc="Agreed sale price per unit at transaction time"
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False, doc="Line item discount"
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, doc="Net line amount: (quantity * unit_price) - discount"
    )

    # Relationships
    sale: Mapped["Sale"] = relationship("Sale", back_populates="items")
    product: Mapped["Product"] = relationship("Product", back_populates="sale_items")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="chk_sale_item_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="chk_sale_item_unit_price_non_negative"),
        CheckConstraint("discount_amount >= 0", name="chk_sale_item_discount_non_negative"),
        CheckConstraint("line_total >= 0", name="chk_sale_item_line_total_non_negative"),
        Index("ix_sale_items_product_sale", "product_id", "sale_id"),
    )

    def __repr__(self) -> str:
        return f"<SaleItem(id={self.id}, sale_id={self.sale_id}, product_id={self.product_id}, qty={self.quantity}, total={self.line_total})>"
