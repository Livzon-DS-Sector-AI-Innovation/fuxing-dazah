"""五金库三期 M7 —— 报废两表 + 实物照片初筛列 + 初筛场景种子

设计 docs/DESIGN-五金库系统原生模块-20261104.md §十一 三期/§9.1：
- hardware_scraps(+items)：报废单（四条件单选+留证照片；两步审批
  draft→pending_dept→pending_final→approved 销账/rejected；零动账红线）
- hardware_receipt_items.photo_screening JSONB：L1 vision 实物照片初筛
  advisory 标记（只标记不拦截不代改——MSDS 模式红线；null=未初筛）
- ai_scenario_configs 播种 hardware_photo_screening（沿 f2a8c4e6d9b3 先例，
  不播种则 live 播种行数断言不一致）

Revision ID: a7b3c9d1e2f4
Revises: g4c6e8f0a2b5
Create Date: 2026-11-05
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.modules.warehouse.ai_config import scenario_registry

revision: str = "a7b3c9d1e2f4"
down_revision: str | None = "g4c6e8f0a2b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"
SCENARIO = "hardware_photo_screening"

_COMMON_COLUMNS = [
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("created_by", sa.Uuid(), nullable=True),
    sa.Column("updated_by", sa.Uuid(), nullable=True),
    sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
]


def upgrade() -> None:
    op.create_table(
        "hardware_scraps",
        *_COMMON_COLUMNS,
        sa.Column("scrap_no", sa.String(50), nullable=False, comment="报废单号 WJK-BF-YYMMDD-序号"),
        sa.Column("dept_name", sa.String(100), nullable=False, comment="发起部门（使用部门或仓储部）"),
        sa.Column("requested_by", sa.String(100), nullable=False, comment="发起人"),
        sa.Column("requested_by_open_id", sa.String(100), nullable=True, comment="发起人 open_id"),
        sa.Column("scrap_reason", sa.String(20), nullable=False,
                  comment="报废条件四选一（制度5.6）：expired/damaged/obsolete/appraisal"),
        sa.Column("reason_note", sa.String(500), nullable=True, comment="报废原因说明"),
        sa.Column("attachments", postgresql.JSONB(), nullable=True, comment="留证照片 file tokens"),
        sa.Column("approval_channel", sa.String(10), nullable=True, comment="审批通道 feishu/manual"),
        sa.Column("approval_instance_code", sa.String(100), nullable=True, comment="飞书审批实例 code"),
        sa.Column("approval_status", sa.String(20), nullable=True, comment="审批结果映射"),
        sa.Column("dept_confirmed_by", sa.String(100), nullable=True, comment="①部门主管确认"),
        sa.Column("dept_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(100), nullable=True, comment="②仓储负责人终审（通过即销账）"),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.String(100), nullable=True, comment="驳回人（任一步可驳）"),
        sa.Column("rejected_reason", sa.String(500), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft",
                  comment="draft/pending_dept/pending_final/approved/rejected/cancelled"),
        sa.Column("scrapped_at", sa.DateTime(timezone=True), nullable=True, comment="销账时间"),
        sa.Column("lot_allocations", postgresql.JSONB(), nullable=True,
                  comment="销账批次扣减结果 [{material, lot_no, mode: preferred/fifo, qty}]"),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "scrap_reason IN ('expired', 'damaged', 'obsolete', 'appraisal')",
            name="ck_hardware_scraps_reason",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'pending_dept', 'pending_final', 'approved', 'rejected', 'cancelled')",
            name="ck_hardware_scraps_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_scraps_no", "hardware_scraps", ["scrap_no"], unique=True,
        postgresql_where=sa.text("is_deleted = false"), schema=SCHEMA,
    )
    op.create_index("ix_hardware_scraps_status", "hardware_scraps", ["status"], schema=SCHEMA)

    op.create_table(
        "hardware_scrap_items",
        *_COMMON_COLUMNS,
        sa.Column("scrap_id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False, comment="报废数量（>0）"),
        sa.Column("preferred_lot_id", sa.Uuid(), nullable=True,
                  comment="指定批次（可选；空=FIFO 自动扣）"),
        sa.Column("name", sa.String(200), nullable=False, comment="品名快照"),
        sa.Column("spec", sa.String(200), nullable=True),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=True, comment="单价快照（报废金额）"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantity > 0", name="ck_hardware_scrap_items_qty"),
        sa.ForeignKeyConstraint(["scrap_id"], ["warehouse.hardware_scraps.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["warehouse.hardware_materials.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index("ix_hardware_scrap_items_scrap", "hardware_scrap_items", ["scrap_id"], schema=SCHEMA)
    op.create_index(
        "ix_hardware_scrap_items_material", "hardware_scrap_items", ["material_id"], schema=SCHEMA,
    )

    # 实物照片初筛 advisory 标记（null=未初筛；只标记不拦截）
    op.add_column(
        "hardware_receipt_items",
        sa.Column("photo_screening", postgresql.JSONB(), nullable=True,
                  comment="实物照片初筛结论 {flagged, findings[], screened_at, scenario}"
                          "（advisory 只标记，不拦截不代改）"),
        schema=SCHEMA,
    )

    # 初筛场景种子（沿 f2a8c4e6d9b3 先例）
    now = datetime.now(UTC)
    scenario_rows = sa.table(
        "ai_scenario_configs",
        sa.column("id", sa.Uuid()), sa.column("scenario", sa.String(64)),
        sa.column("enabled", sa.Boolean()), sa.column("model_profile", sa.String(32)),
        sa.column("is_deleted", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        schema=SCHEMA,
    )
    op.execute(postgresql.insert(scenario_rows).values([
        {"id": uuid4(), "scenario": info.scenario, "enabled": True,
         "model_profile": None, "is_deleted": False, "created_at": now, "updated_at": now}
        for info in scenario_registry.iter_scenarios()
        if info.scenario == SCENARIO
    ]).on_conflict_do_nothing())


def downgrade() -> None:
    op.execute(f"DELETE FROM {SCHEMA}.ai_scenario_configs WHERE scenario = '{SCENARIO}'")
    op.drop_column("hardware_receipt_items", "photo_screening", schema=SCHEMA)
    op.drop_index("ix_hardware_scrap_items_material", table_name="hardware_scrap_items", schema=SCHEMA)
    op.drop_index("ix_hardware_scrap_items_scrap", table_name="hardware_scrap_items", schema=SCHEMA)
    op.drop_table("hardware_scrap_items", schema=SCHEMA)
    op.drop_index("ix_hardware_scraps_status", table_name="hardware_scraps", schema=SCHEMA)
    op.drop_index("uq_hardware_scraps_no", table_name="hardware_scraps", schema=SCHEMA)
    op.drop_table("hardware_scraps", schema=SCHEMA)
