"""add sop_no and form_id to product_standards

Revision ID: c8ce652b75c2
Revises: a640beeddd5c
Create Date: 2026-09-02 17:22:49.976493
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8ce652b75c2'
down_revision: Union[str, None] = 'a640beeddd5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_standards",
        sa.Column("form_id", sa.String(100), nullable=True, comment="代号/表号（同一产品不同制剂/工艺的细分，如 3229）"),
        schema="quality",
    )
    op.add_column(
        "product_standards",
        sa.Column("sop_no", sa.String(64), nullable=True, comment="检验项目绑定的 SOP 编号（同名项目按 SOP 号区分匹配）"),
        schema="quality",
    )
    # 唯一约束扩展为 产品+代号+项目+SOP号
    op.drop_index("uq_quality_product_standards_item", table_name="product_standards", schema="quality")
    op.create_index(
        "uq_quality_product_standards_item",
        "product_standards",
        ["product_name", "form_id", "item_name", "sop_no"],
        unique=True,
        schema="quality",
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index("uq_quality_product_standards_item", table_name="product_standards", schema="quality")
    op.create_index(
        "uq_quality_product_standards_item",
        "product_standards",
        ["product_name", "item_name"],
        unique=True,
        schema="quality",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_column("product_standards", "sop_no", schema="quality")
    op.drop_column("product_standards", "form_id", schema="quality")
