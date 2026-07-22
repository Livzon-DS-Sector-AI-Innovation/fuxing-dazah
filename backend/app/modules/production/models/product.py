"""产品主数据 ORM。"""

from sqlalchemy import Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class Product(BaseModel):
    """产品主数据"""

    __tablename__ = "products"
    __table_args__ = (
        Index(
            "uq_production_products_name",
            "product_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "production"},
    )

    product_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="产品编码（可选辅助标识）"
    )
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称（唯一）")
    unit: Mapped[str] = mapped_column(String(20), default="kg", comment="默认计量单位")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
