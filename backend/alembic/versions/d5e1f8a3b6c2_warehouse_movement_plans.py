"""warehouse movement plans

出入库计划单表：到货/领料的预计单据，状态机 planned → in_progress →
completed（完成时回填 movement_id），非完成态可取消（必填原因）。

Revision ID: d5e1f8a3b6c2
Revises: c9d4e7f2a8b1
Create Date: 2026-09-15
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd5e1f8a3b6c2'
down_revision: str | None = 'c9d4e7f2a8b1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    """BaseModel 公共列（与 app/shared/base_model.py 对齐）。"""
    return [
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    ]


def _base_fks() -> list:
    return [
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id']),
        sa.PrimaryKeyConstraint('id'),
    ]


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS warehouse')

    op.create_table('movement_plans',
        sa.Column('plan_no', sa.String(length=50), nullable=False, comment='计划单号'),
        sa.Column('direction', sa.String(length=20), nullable=False, comment='方向: inbound入库/outbound出库'),
        sa.Column('source_type', sa.String(length=20), nullable=False, comment='业务来源'),
        sa.Column('material_id', sa.Uuid(), nullable=False),
        sa.Column('material_code', sa.String(length=50), nullable=False, comment='物料编码（冗余）'),
        sa.Column('material_name', sa.String(length=200), nullable=False, comment='物料名称（冗余）'),
        sa.Column('batch_no', sa.String(length=100), server_default='', nullable=False, comment='批次号，空表示无批次'),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=False, comment='计划数量，恒为正'),
        sa.Column('location_id', sa.Uuid(), nullable=False),
        sa.Column('location_code', sa.String(length=50), nullable=False, comment='库位编码（冗余）'),
        sa.Column('location_name', sa.String(length=200), nullable=False, comment='库位名称（冗余）'),
        sa.Column('planned_date', sa.Date(), nullable=True, comment='预计日期'),
        sa.Column('status', sa.String(length=20), server_default='planned', nullable=False, comment='planned/in_progress/completed/cancelled'),
        sa.Column('cancel_reason', sa.Text(), nullable=True, comment='取消原因'),
        sa.Column('movement_id', sa.Uuid(), nullable=True, comment='生成登记后回填的出入库记录ID'),
        sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
        *_base_columns(), *_base_fks(),
        sa.CheckConstraint("direction IN ('inbound', 'outbound')", name='ck_warehouse_movement_plans_direction'),
        sa.CheckConstraint("status IN ('planned', 'in_progress', 'completed', 'cancelled')", name='ck_warehouse_movement_plans_status'),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_movement_plans_status', 'movement_plans', ['status'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_movement_plans_no', 'movement_plans', ['plan_no'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_warehouse_movement_plans_no', table_name='movement_plans', schema='warehouse')
    op.drop_index('ix_warehouse_movement_plans_status', table_name='movement_plans', schema='warehouse')
    op.drop_table('movement_plans', schema='warehouse')
