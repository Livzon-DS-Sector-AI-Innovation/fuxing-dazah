"""add line product links

Revision ID: 7bf1a1f4aa16
Revises: 21c784404a3e
Create Date: 2026-08-27 14:53:42.171099
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7bf1a1f4aa16'
down_revision: Union[str, None] = '21c784404a3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('line_product_links',
    sa.Column('line_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('ix_production_line_product_links_line', 'line_product_links', ['line_id'], unique=False, schema='production')
    op.create_index('ix_production_line_product_links_product', 'line_product_links', ['product_id'], unique=False, schema='production')
    op.create_index('uq_production_line_product_links', 'line_product_links', ['line_id', 'product_id'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_production_line_product_links', table_name='line_product_links', schema='production')
    op.drop_index('ix_production_line_product_links_product', table_name='line_product_links', schema='production')
    op.drop_index('ix_production_line_product_links_line', table_name='line_product_links', schema='production')
    op.drop_table('line_product_links', schema='production')
