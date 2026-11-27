"""quality drop unqualified events

Revision ID: 4fc58ac5850d
Revises: 872cfda37ace
Create Date: 2026-09-17 17:02:23.344469
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4fc58ac5850d'
down_revision: Union[str, None] = '872cfda37ace'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_quality_unqualified_event_task', table_name='quality_unqualified_events', schema='quality')
    op.drop_index('ix_quality_unqualified_event_batch', table_name='quality_unqualified_events', schema='quality')
    op.drop_table('quality_unqualified_events', schema='quality')


def downgrade() -> None:
    op.create_table(
        'quality_unqualified_events',
        sa.Column('task_id', sa.Uuid(), nullable=True),
        sa.Column('product_name', sa.String(length=200), nullable=False),
        sa.Column('batch_number', sa.String(length=100), nullable=False),
        sa.Column('item_name', sa.String(length=200), nullable=False),
        sa.Column('sop_no', sa.String(length=64), nullable=True),
        sa.Column('result_value', sa.Float(), nullable=True),
        sa.Column('standard_text', sa.String(length=300), nullable=True),
        sa.Column('limit_text', sa.String(length=100), nullable=True),
        sa.Column('source', sa.String(length=20), server_default='manual', nullable=False),
        sa.Column('handled', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='quality',
    )
    op.create_index('ix_quality_unqualified_event_task', 'quality_unqualified_events', ['task_id'], unique=False, schema='quality')
    op.create_index('ix_quality_unqualified_event_batch', 'quality_unqualified_events', ['batch_number'], unique=False, schema='quality')
