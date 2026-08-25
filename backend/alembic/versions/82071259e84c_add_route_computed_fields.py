"""add route_computed_fields

Revision ID: 82071259e84c
Revises: 0728ff9db81f
Create Date: 2026-08-20 15:59:42.824028
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '82071259e84c'
down_revision: str | None = '0728ff9db81f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('route_computed_fields',
    sa.Column('route_id', sa.Uuid(), nullable=False, comment='所属路线'),
    sa.Column('node_id', sa.Uuid(), nullable=False, comment='展示归属节点'),
    sa.Column('field_key', sa.String(length=50), nullable=False, comment='字段键，路线内唯一，可被其他计算字段引用'),
    sa.Column('field_label', sa.String(length=100), nullable=False, comment='显示名'),
    sa.Column('unit', sa.String(length=20), nullable=True, comment='单位，纯展示'),
    sa.Column('formula', sa.Text(), nullable=False, comment='公式，如 {G1.A1} * 0.9 + {G2.B2}'),
    sa.Column('sort_order', sa.Integer(), nullable=False, comment='排序'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('uq_production_route_computed_fields', 'route_computed_fields', ['route_id', 'field_key'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_production_route_computed_fields', table_name='route_computed_fields', schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('route_computed_fields', schema='production')
