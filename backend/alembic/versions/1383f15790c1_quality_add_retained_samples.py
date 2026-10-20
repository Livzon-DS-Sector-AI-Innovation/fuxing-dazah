"""quality add retained samples

Revision ID: 1383f15790c1
Revises: 0b97cb96e058
Create Date: 2026-10-20 14:22:15.060534
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1383f15790c1'
down_revision: str | None = '0b97cb96e058'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.create_table(
        'quality_retained_samples',
        sa.Column('source_type', sa.String(length=32), nullable=False, comment='product 成品 / material 物料'),
        sa.Column('batch_no', sa.String(length=100), nullable=False, comment='批号'),
        sa.Column('sample_name', sa.String(length=200), nullable=False, comment='名称/品名'),
        sa.Column('qty', sa.String(length=50), nullable=True, comment='留样量（如 2 瓶）'),
        sa.Column('location', sa.String(length=50), nullable=True, comment='贮存位置（柜号）'),
        sa.Column('retained_at', sa.String(length=32), nullable=True, comment='留样日期 YYYY-MM-DD'),
        sa.Column('destroy_due_date', sa.String(length=32), nullable=True, comment='销毁到期日 YYYY-MM-DD（到期提醒依据）'),
        sa.Column('destroyed_at', sa.String(length=32), nullable=True, comment='实际销毁日期'),
        sa.Column('destroyed_by', sa.Uuid(), nullable=True, comment='销毁登记人'),
        sa.Column('destroy_confirm_by', sa.Uuid(), nullable=True, comment='销毁双人确认第二人'),
        sa.Column('status', sa.String(length=32), server_default='active', nullable=False, comment='active 在留 / destroyed 已销毁'),
        sa.Column('remark', sa.String(length=200), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='quality',
    )
    op.create_index('ix_quality_retained_batch', 'quality_retained_samples', ['batch_no'], unique=False, schema='quality')
    op.create_index('ix_quality_retained_destroy_due', 'quality_retained_samples', ['destroy_due_date'], unique=False, schema='quality')


def downgrade() -> None:
    op.drop_index('ix_quality_retained_destroy_due', table_name='quality_retained_samples', schema='quality')
    op.drop_index('ix_quality_retained_batch', table_name='quality_retained_samples', schema='quality')
    op.drop_table('quality_retained_samples', schema='quality')
