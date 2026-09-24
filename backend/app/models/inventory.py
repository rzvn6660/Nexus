"""Inventory ORM model tracking stock levels and reorder parameters."""

from typing import TYPE_CHECKING
from sqlalchemy import String, Integer, ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.product import Product


class Inventory(Base, TimestampMixin):
    """
    Represents current stock on hand and replenishment policy for a product SKU.
    """

    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    stock_quantity: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, doc="Current physically available stock units"
    )
    reorder_threshold: Mapped[int] = mapped_column(
        Integer, default=10, nullable=False, doc="Inventory level below which reorder is triggered"
    )
    warehouse_location: Mapped[str] = mapped_column(
        String(128), default="Main Warehouse", nullable=False, doc="Physical storage bin / zone"
    )

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="inventory")

    __table_args__ = (
        CheckConstraint("stock_quantity >= 0", name="chk_inventory_stock_quantity_non_negative"),
        CheckConstraint("reorder_threshold >= 0", name="chk_inventory_reorder_threshold_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<Inventory(id={self.id}, product_id={self.product_id}, stock={self.stock_quantity}, threshold={self.reorder_threshold})>"
