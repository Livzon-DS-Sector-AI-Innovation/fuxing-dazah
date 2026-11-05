"""五金库二期 M5 —— 月度采购计划(头+行) + 温湿度日检三表

设计 docs/DESIGN-五金库系统原生模块-20261104.md §2.6：
- hardware_purchase_plans(+items)：25 日快照 + P7 公式草案（plan_month 唯一=
  同月重跑幂等键；is_edited 行人工值保留）+ ai_note 建议态注释
- hardware_env_logs：温湿度日检（log_date 唯一，每日一行）

Revision ID: e9f4a8c2d6e5
Revises: d8e2f6a4b8c1
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "e9f4a8c2d6e5"
down_revision: str | None = "d8e2f6a4b8c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"

_COMMON_COLUMNS = [
    sa.Column("id", UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("created_by", UUID(), nullable=True),
    sa.Column("updated_by", UUID(), nullable=True),
    sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
]


def upgrade() -> None:
    op.create_table(
        "hardware_purchase_plans",
        *_COMMON_COLUMNS,
        sa.Column("plan_month", sa.String(7), nullable=False, comment="计划月 YYYY-MM（幂等键）"),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft",
                  comment="draft/exported"),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=True, comment="25 日快照时间"),
        sa.Column("usage_window_days", sa.Integer(), nullable=False, server_default="30",
                  comment="月使用量回溯窗口"),
        sa.Column("annotated", sa.Boolean(), nullable=False, server_default=sa.text("false"),
                  comment="AI 注释是否已跑"),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exported_by", sa.String(100), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('draft', 'exported')",
                           name="ck_hardware_purchase_plans_status"),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_purchase_plans_month", "hardware_purchase_plans", ["plan_month"],
        unique=True, postgresql_where=sa.text("is_deleted = false"), schema=SCHEMA,
    )

    op.create_table(
        "hardware_purchase_plan_items",
        *_COMMON_COLUMNS,
        sa.Column("purchase_plan_id", UUID(), nullable=False),
        sa.Column("material_id", UUID(), nullable=False),
        sa.Column("code", sa.String(50), nullable=True, comment="物料编码快照"),
        sa.Column("name", sa.String(200), nullable=False, comment="品名快照"),
        sa.Column("spec", sa.String(200), nullable=True),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("monthly_demand_total", sa.Numeric(18, 3), nullable=False,
                  server_default="0", comment="月需求合计"),
        sa.Column("safety_stock", sa.Numeric(18, 3), nullable=False, server_default="0",
                  comment="安全库存量快照"),
        sa.Column("stock_on_25th", sa.Numeric(18, 3), nullable=False, server_default="0",
                  comment="当月 25 日库存量快照"),
        sa.Column("monthly_usage", sa.Numeric(18, 3), nullable=False, server_default="0",
                  comment="月使用量（近月出库聚合）"),
        sa.Column("purchase_qty", sa.Numeric(18, 3), nullable=False, server_default="0",
                  comment="月度采购量（P7 公式）"),
        sa.Column("ai_note", sa.String(500), nullable=True, comment="AI 用量注释（建议态）"),
        sa.Column("is_edited", sa.Boolean(), nullable=False, server_default=sa.text("false"),
                  comment="人工编辑标记（重跑保留）"),
        sa.Column("remark", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("purchase_qty >= 0", name="ck_hardware_plan_items_purchase"),
        sa.ForeignKeyConstraint(["purchase_plan_id"], ["warehouse.hardware_purchase_plans.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["warehouse.hardware_materials.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_hardware_plan_items_plan", "hardware_purchase_plan_items", ["purchase_plan_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_hardware_plan_items_material", "hardware_purchase_plan_items", ["material_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "hardware_env_logs",
        *_COMMON_COLUMNS,
        sa.Column("log_date", sa.Date(), nullable=False, comment="日期（每日一行）"),
        sa.Column("temperature", sa.Numeric(5, 1), nullable=True, comment="温度 ℃"),
        sa.Column("humidity", sa.Numeric(5, 1), nullable=True, comment="湿度 %RH"),
        sa.Column("checked_by", sa.String(100), nullable=True, comment="检查人"),
        sa.Column("abnormal_note", sa.String(500), nullable=True, comment="异常说明"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_env_logs_date", "hardware_env_logs", ["log_date"], unique=True,
        postgresql_where=sa.text("is_deleted = false"), schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("uq_hardware_env_logs_date", table_name="hardware_env_logs", schema=SCHEMA)
    op.drop_table("hardware_env_logs")

    op.drop_index("ix_hardware_plan_items_material", table_name="hardware_purchase_plan_items", schema=SCHEMA)
    op.drop_index("ix_hardware_plan_items_plan", table_name="hardware_purchase_plan_items", schema=SCHEMA)
    op.drop_table("hardware_purchase_plan_items")

    op.drop_index("uq_hardware_purchase_plans_month", table_name="hardware_purchase_plans", schema=SCHEMA)
    op.drop_table("hardware_purchase_plans")
