"""add maintenance plan auto-workorder fields

Revision ID: f81e0b223a81
Revises: f9ca70c25836
Create Date: 2026-06-15 16:12:23.007758
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f81e0b223a81'
down_revision: Union[str, None] = 'f9ca70c25836'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. maintenance_plans 表新增 last_generated_date 列
    op.add_column(
        'maintenance_plans',
        sa.Column(
            'last_generated_date',
            sa.Date(),
            nullable=True,
            comment='最后生成工单的周期日期，用于防重',
        ),
        schema='equipment',
    )
    # 2. work_orders 表 reporter_id 改为 nullable
    op.alter_column(
        'work_orders',
        'reporter_id',
        existing_type=sa.UUID(),
        nullable=True,
        comment='报修人ID，系统自动生成的工单可为空',
        existing_comment='报修人ID',
        schema='equipment',
    )


def downgrade() -> None:
    op.alter_column(
        'work_orders',
        'reporter_id',
        existing_type=sa.UUID(),
        nullable=False,
        comment='报修人ID',
        existing_comment='报修人ID，系统自动生成的工单可为空',
        schema='equipment',
    )
    op.drop_column('maintenance_plans', 'last_generated_date', schema='equipment')
