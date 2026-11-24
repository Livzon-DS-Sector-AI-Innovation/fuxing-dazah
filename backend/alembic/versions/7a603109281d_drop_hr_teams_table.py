"""drop hr teams table

班组管理整链下线（hr.teams 表 0 数据、无业务依赖；员工/入职台账的「班组」
文本列是飞书源表同步快照，与班组管理功能无关，保留不动）。

Revision ID: 7a603109281d
Revises: 5142d97887e4
Create Date: 2026-11-23 11:31:07.662466
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7a603109281d'
down_revision: Union[str, None] = '5142d97887e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # drop table 隐式删除表上索引（ix_teams_department_id / ix_teams_name）
    op.drop_table('teams', schema='hr')


def downgrade() -> None:
    op.create_table(
        'teams',
        sa.Column('name', sa.String(length=64), nullable=False, comment='班组名称'),
        sa.Column('code', sa.String(length=32), nullable=True, comment='班组编码'),
        sa.Column('description', sa.String(length=256), nullable=True, comment='班组描述'),
        sa.Column('department_id', sa.Uuid(), nullable=False, comment='所属部门ID'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['department_id'], ['hr.departments.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='hr',
    )
    op.create_index('ix_teams_department_id', 'teams', ['department_id'], unique=False, schema='hr')
    op.create_index('ix_teams_name', 'teams', ['name'], unique=False, schema='hr')
