"""五金库呆滞季度快照名单表 —— hardware_stale_items

季度清单设计（docs/DESIGN-五金库呆滞清单季度自动更新-20261120.md）：
每季一张呆滞名单快照（(quarter_label, material_id) 软删唯一=同季重跑
幂等键），历史季度保留可查；status 四态跨季滚动（disposing 继承 /
退名单自动翻 consumed）由 planning.snapshot_stale_quarter 驱动。

⚠️ down_revision 挂 n9c2e4f6a8b1（并行 WIP 迁移「领用申请指定审批人」，
dev 库已应用该迁移；其文件随主仓库 WIP commit 落库，本文件 commit 顺序
须在其后，否则链头短暂悬空）。

Revision ID: c3e5a7b9d1f4
Revises: n9c2e4f6a8b1
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "c3e5a7b9d1f4"
down_revision: str | None = "n9c2e4f6a8b1"
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
        "hardware_stale_items",
        *_COMMON_COLUMNS,
        sa.Column("quarter_label", sa.String(8), nullable=False,
                  comment="季度标签（幂等键），如 2026Q4"),
        sa.Column("material_id", UUID(), nullable=False),
        sa.Column("code", sa.String(100), nullable=True, comment="编码快照"),
        sa.Column("name", sa.String(200), nullable=False, comment="品名快照"),
        sa.Column("spec", sa.String(200), nullable=True, comment="规格快照"),
        sa.Column("unit", sa.String(20), nullable=True, comment="单位快照"),
        sa.Column("on_hand", sa.Numeric(18, 3), server_default="0", nullable=False,
                  comment="快照时点库存"),
        sa.Column("last_issue_at", sa.DateTime(timezone=True), nullable=True,
                  comment="最近领用时间（从未领用为空）"),
        sa.Column("base_time", sa.DateTime(timezone=True), nullable=False,
                  comment="呆滞起算锚点（最近领用 ?? 最近入库）"),
        sa.Column("silent_days", sa.Integer(), nullable=False, comment="快照时点呆滞天数"),
        sa.Column("status", sa.String(16), server_default="stale", nullable=False,
                  comment="stale/consumed/disposing/scrapped"),
        sa.Column("status_note", sa.String(500), nullable=True,
                  comment="处置说明/自动对账留痕"),
        sa.Column("status_by", sa.String(100), nullable=True, comment="标记人（姓名）"),
        sa.Column("status_at", sa.DateTime(timezone=True), nullable=True, comment="标记时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('stale', 'consumed', 'disposing', 'scrapped')",
                           name="ck_hardware_stale_items_status"),
        sa.ForeignKeyConstraint(["material_id"], ["warehouse.hardware_materials.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_stale_items_quarter_material", "hardware_stale_items",
        ["quarter_label", "material_id"], unique=True,
        postgresql_where=sa.text("is_deleted = false"), schema=SCHEMA,
    )
    op.create_index(
        "ix_hardware_stale_items_material", "hardware_stale_items", ["material_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_hardware_stale_items_material", schema=SCHEMA,
                  table_name="hardware_stale_items")
    op.drop_index("uq_hardware_stale_items_quarter_material", schema=SCHEMA,
                  table_name="hardware_stale_items")
    op.drop_table("hardware_stale_items", schema=SCHEMA)
