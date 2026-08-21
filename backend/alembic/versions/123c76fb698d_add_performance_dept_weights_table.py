"""add performance_dept_weights table

Revision ID: 123c76fb698d
Revises: dafa88c3f707
Create Date: 2026-08-04 14:21:48.216039
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '123c76fb698d'
down_revision: Union[str, None] = 'dafa88c3f707'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('performance_dept_weights',
    sa.Column('category_id', sa.Uuid(), nullable=False, comment='关联考核项目'),
    sa.Column('department', sa.String(length=128), nullable=False, comment='部门名称'),
    sa.Column('weight', sa.Float(), nullable=False, comment='该部门此项目权重(%)'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['hr.performance_categories.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_pdw_category_dept', 'performance_dept_weights', ['category_id', 'department'], unique=False, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_pdw_category_dept', table_name='performance_dept_weights', schema='hr')
    op.drop_table('performance_dept_weights', schema='hr')
