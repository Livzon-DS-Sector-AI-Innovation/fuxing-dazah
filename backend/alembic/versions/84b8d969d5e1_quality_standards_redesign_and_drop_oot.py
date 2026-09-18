"""quality standards redesign and drop oot

Revision ID: 84b8d969d5e1
Revises: 8366b089eadd
Create Date: 2026-09-02 17:58:02.663560
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '84b8d969d5e1'
down_revision: Union[str, None] = '8366b089eadd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")

    # ── 标准表重设计：文档表 + 项目行表（替换旧 product_standards）──
    op.create_table(
        "quality_standard_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("file_no", sa.String(100), nullable=False, comment="文件编号，如 SOP.02.3292.003"),
        sa.Column("product_name", sa.String(200), nullable=False, comment="产品名称"),
        sa.Column("product_code", sa.String(64), nullable=True, comment="产品代号，如 HAS"),
        sa.Column("product_internal_code", sa.String(64), nullable=True, comment="产品代码，如 30205"),
        sa.Column("specification", sa.String(200), nullable=True, comment="产品规格"),
        sa.Column("valid_years", sa.String(32), nullable=True, comment="有效期"),
        sa.Column("effective_date", sa.String(32), nullable=True, comment="生效日期"),
        sa.Column("version", sa.String(32), nullable=True, comment="版本号"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        schema="quality",
    )
    op.create_index(
        "uq_quality_std_doc_file_no",
        "quality_standard_documents",
        ["file_no"],
        unique=True,
        schema="quality",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_quality_std_doc_product",
        "quality_standard_documents",
        ["product_name"],
        schema="quality",
    )

    op.create_table(
        "quality_standard_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), nullable=False, comment="关联标准文档"),
        sa.Column("seq", sa.Integer(), nullable=True, comment="序号"),
        sa.Column("category", sa.String(100), nullable=True, comment="检验项目大类"),
        sa.Column("item_name", sa.String(200), nullable=False, comment="子项目名称（匹配以 SOP 号为准）"),
        sa.Column("sop_no", sa.String(64), nullable=False, comment="检验方法 SOP 编号（匹配键）"),
        sa.Column("standard_text", sa.String(300), nullable=False, comment="合格标准原文"),
        sa.Column("operator", sa.String(10), nullable=True, comment="比较运算符"),
        sa.Column("limit_min", sa.Float(), nullable=True, comment="限度下限"),
        sa.Column("limit_max", sa.Float(), nullable=True, comment="限度上限"),
        sa.Column("method_source", sa.String(64), nullable=True, comment="方法来源"),
        sa.Column("remark", sa.String(200), nullable=True, comment="备注"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        schema="quality",
    )
    op.create_index(
        "ix_quality_std_item_doc",
        "quality_standard_items",
        ["document_id"],
        schema="quality",
    )
    op.create_index(
        "uq_quality_std_item_sop",
        "quality_standard_items",
        ["document_id", "sop_no"],
        unique=True,
        schema="quality",
        postgresql_where=sa.text("is_deleted = false"),
    )

    # 旧标准表下线（数据未发布，直接丢弃）
    op.drop_table("product_standards", schema="quality")

    # ── OOT 全删 ──
    op.drop_column("inspection_records", "has_oot", schema="quality")
    op.drop_column("inspection_impurities", "oot_haf", schema="quality")
    op.drop_column("inspection_impurities", "oot_haa", schema="quality")
    op.drop_column("inspection_impurities", "is_oot", schema="quality")


def downgrade() -> None:
    # 重设计不回滚（旧 product_standards 结构见历史迁移）
    pass
