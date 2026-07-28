"""rename plan_items to product, add batch_no, nullable qty/unit

Revision ID: d54a9f883c32
Revises: b4f717ac6a45
Create Date: 2026-07-24 16:13:59.627000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd54a9f883c32'
down_revision: Union[str, None] = 'b4f717ac6a45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS production")
    op.alter_column('plan_items', 'intermediate_type_id', new_column_name='product_id', schema='production')
    op.alter_column('plan_items', 'intermediate_type_name', new_column_name='product_name', schema='production')
    op.add_column('plan_items', sa.Column('batch_no', sa.String(50), nullable=True), schema='production')
    op.alter_column('plan_items', 'planned_quantity', existing_type=sa.Float(), nullable=True, schema='production')
    op.alter_column('plan_items', 'unit', existing_type=sa.String(20), nullable=True, schema='production')


def downgrade() -> None:
    op.alter_column('plan_items', 'planned_quantity', existing_type=sa.Float(), nullable=False, schema='production')
    op.alter_column('plan_items', 'unit', existing_type=sa.String(20), nullable=False, schema='production')
    op.drop_column('plan_items', 'batch_no', schema='production')
    op.alter_column('plan_items', 'product_name', new_column_name='intermediate_type_name', schema='production')
    op.alter_column('plan_items', 'product_id', new_column_name='intermediate_type_id', schema='production')
