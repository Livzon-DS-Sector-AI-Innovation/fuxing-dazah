"""add inspection_route_schedules and drop route period columns

Revision ID: 0447bceeb298
Revises: 706fdf53f046
Create Date: 2026-06-23 17:46:01.925331
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0447bceeb298'
down_revision: Union[str, None] = '706fdf53f046'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS equipment")

    op.create_table('inspection_route_schedules',
        sa.Column('route_id', sa.Uuid(), nullable=False, comment='路线ID'),
        sa.Column('cron_expression', sa.String(length=50), nullable=False,
                  comment='cron 表达式'),
        sa.Column('assigned_to', sa.Uuid(), nullable=True,
                  comment='巡检人员ID'),
        sa.Column('is_active', sa.Boolean(), server_default='true',
                  nullable=False, comment='是否启用'),
        sa.Column('last_triggered_at', sa.DateTime(timezone=True),
                  nullable=True, comment='上次触发时间'),
        sa.Column('next_trigger_at', sa.DateTime(timezone=True),
                  nullable=True, comment='下次触发时间'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false',
                  nullable=False),
        sa.ForeignKeyConstraint(['assigned_to'], ['identity.users.id']),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id']),
        sa.ForeignKeyConstraint(
            ['route_id'], ['equipment.inspection_routes.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('route_id', 'cron_expression', 'assigned_to',
                            'is_deleted',
                            name='uq_route_schedules_route_cron_assignee'),
        schema='equipment'
    )

    op.drop_column('inspection_routes', 'period_value', schema='equipment')
    op.drop_column('inspection_routes', 'period_type', schema='equipment')


def downgrade() -> None:
    op.add_column('inspection_routes',
                  sa.Column('period_type', sa.String(length=20),
                            server_default=sa.text("'每日'::character varying"),
                            nullable=False, comment='巡检周期类型'),
                  schema='equipment')
    op.add_column('inspection_routes',
                  sa.Column('period_value', sa.Integer(), nullable=True,
                            comment='周期数值'),
                  schema='equipment')

    op.drop_table('inspection_route_schedules', schema='equipment')
