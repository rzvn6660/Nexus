"""Product ORM model for retail business domain."""

from decimal import Decimal
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Boolean, Numeric, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.sale_item import SaleItem
    from app.models.inventory import Inventory


class Product(Base, TimestampMixin):
    """
    Represents an item or merchandise SKU offered by the business.
    
    Financial figures (unit_cost, selling_price) use fixed-point Decimal
    to prevent floating-point inaccuracies.
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, doc="Stock Keeping Unit code"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    subcategory: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, doc="Cost of Goods Sold (COGS) per unit"
    )
    selling_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, doc="Base retail catalog selling price"
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)

    # Relationships
    sale_items: Mapped[List["SaleItem"]] = relationship(
        "SaleItem", back_populates="product", lazy="selectin"
    )
    inventory: Mapped[Optional["Inventory"]] = relationship(
        "Inventory", back_populates="product", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("unit_cost >= 0", name="chk_product_unit_cost_non_negative"),
        CheckConstraint("selling_price >= 0", name="chk_product_selling_price_non_negative"),
        Index("ix_products_category_active", "category", "active"),
    )

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, sku='{self.sku}', name='{self.name}', price={self.selling_price})>"
