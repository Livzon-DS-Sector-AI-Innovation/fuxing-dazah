"""quality env plans

Revision ID: aed7833e8cfb
Revises: 08660e45bc88
Create Date: 2026-11-02 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aed7833e8cfb'
down_revision: Union[str, None] = '08660e45bc88'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('quality_env_plans',
    sa.Column('plan_date', sa.String(length=10), nullable=False, comment='应测日期 YYYY-MM-DD'),
    sa.Column('point_id', sa.Uuid(), nullable=False, comment='监测点，逻辑引用 quality_env_points.id'),
    sa.Column('room', sa.String(length=128), nullable=False, comment='房间快照'),
    sa.Column('point_no', sa.String(length=64), nullable=False, comment='点位编号快照'),
    sa.Column('monitor_type', sa.String(length=32), nullable=False, comment='监测类型快照'),
    sa.Column('frequency', sa.String(length=32), nullable=True, comment='频次快照'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='quality'
    )
    op.create_index('ix_quality_env_plan_date', 'quality_env_plans', ['plan_date'], unique=False, schema='quality')
    op.create_index('uq_quality_env_plan_point_date', 'quality_env_plans', ['point_id', 'plan_date'], unique=True, schema='quality', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_quality_env_plan_point_date', table_name='quality_env_plans', schema='quality', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_quality_env_plan_date', table_name='quality_env_plans', schema='quality')
    op.drop_table('quality_env_plans', schema='quality')
