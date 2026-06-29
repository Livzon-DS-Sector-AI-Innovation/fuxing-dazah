"""add batch_id, stage_name, chapter7_context to hazard_identifications

Revision ID: b9c0d1e2f3a4
Revises: a2b3c4d5e6f7
Create Date: 2026-06-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'hazard_identifications',
        sa.Column('batch_id', sa.Uuid(), nullable=True, comment='批次ID，同一regulation多工段同时创建时共享'),
        schema='safety',
    )
    op.add_column(
        'hazard_identifications',
        sa.Column('stage_name', sa.String(255), nullable=True, comment='工艺阶段名称（Chapter 7 H2 标题）'),
        schema='safety',
    )
    op.add_column(
        'hazard_identifications',
        sa.Column('chapter7_context', sa.Text(), nullable=True, comment='该工段对应的 Chapter 7 节选 Markdown（供Script 1使用）'),
        schema='safety',
    )
    # Index for batch_id lookups
    op.create_index(
        'ix_hazard_identifications_batch_id',
        'hazard_identifications',
        ['batch_id'],
        schema='safety',
    )
    # Composite index for listing all records in a regulation's batch
    op.create_index(
        'ix_hazard_identifications_regulation_batch',
        'hazard_identifications',
        ['regulation_id', 'batch_id'],
        schema='safety',
    )


def downgrade() -> None:
    op.drop_index('ix_hazard_identifications_regulation_batch', table_name='hazard_identifications', schema='safety')
    op.drop_index('ix_hazard_identifications_batch_id', table_name='hazard_identifications', schema='safety')
    op.drop_column('hazard_identifications', 'chapter7_context', schema='safety')
    op.drop_column('hazard_identifications', 'stage_name', schema='safety')
    op.drop_column('hazard_identifications', 'batch_id', schema='safety')
