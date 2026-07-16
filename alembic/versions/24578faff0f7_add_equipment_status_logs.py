"""add equipment status logs

新增 equipment.equipment_status_logs 状态变更日志表（用于时间开动率统计），
并为存量设备按当前状态写入基线记录（source='init'）。

Revision ID: 24578faff0f7
Revises: 35aefefbedc4
Create Date: 2026-07-15 14:38:02.428151
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '24578faff0f7'
down_revision: str | None = '35aefefbedc4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS equipment")

    op.create_table(
        'equipment_status_logs',
        sa.Column('equipment_id', sa.Uuid(), nullable=False, comment='设备ID，逻辑引用 equipment.equipments.id'),
        sa.Column('old_status', sa.String(length=20), nullable=True, comment='变更前状态；基线记录为空'),
        sa.Column('new_status', sa.String(length=20), nullable=False, comment='变更后状态：在用/备用/维修中/停用/报废'),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False, comment='变更时间'),
        sa.Column('source', sa.String(length=20), nullable=False, comment='来源：init(基线)/create(新建)/manual(台账编辑)/work_order(工单联动)/import(Excel导入)'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='equipment',
    )
    op.create_index(
        'ix_equipment_status_logs_eq_time',
        'equipment_status_logs',
        ['equipment_id', 'changed_at'],
        schema='equipment',
    )

    # 存量设备基线记录：以迁移时刻的当前状态为起点，开动率只从此刻起算
    op.execute(
        """
        INSERT INTO equipment.equipment_status_logs
            (id, equipment_id, old_status, new_status, changed_at, source,
             created_at, updated_at, is_deleted)
        SELECT gen_random_uuid(), e.id, NULL, e.status, now(), 'init',
               now(), now(), false
        FROM equipment.equipments e
        WHERE e.is_deleted = false
        """
    )


def downgrade() -> None:
    op.drop_index(
        'ix_equipment_status_logs_eq_time',
        table_name='equipment_status_logs',
        schema='equipment',
    )
    op.drop_table('equipment_status_logs', schema='equipment')
