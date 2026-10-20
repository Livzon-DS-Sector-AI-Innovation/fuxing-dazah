"""quality add micro records

Revision ID: 0b97cb96e058
Revises: 6dd0f0874f55
Create Date: 2026-10-20 09:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0b97cb96e058'
down_revision: Union[str, None] = '6dd0f0874f55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('quality_micro_records',
        sa.Column('sample_name', sa.String(length=200), nullable=False, comment='样品名称/品名'),
        sa.Column('batch_number', sa.String(length=100), nullable=True, comment='样品批号'),
        sa.Column('sample_date', sa.String(length=32), nullable=True, comment='检测日期 YYYY-MM-DD'),
        sa.Column('colony_count', sa.Integer(), nullable=True, comment='菌落计数（人工确认数，判定依据）'),
        sa.Column('ai_count', sa.Integer(), nullable=True, comment='AI 预计数（视觉模型插件预留，不作判定依据）'),
        sa.Column('alert_limit', sa.Float(), nullable=True, comment='警戒线'),
        sa.Column('action_limit', sa.Float(), nullable=True, comment='标准限（行动限）'),
        sa.Column('judge', sa.String(length=16), nullable=True, comment='pass 合格 / alert 超警戒 / action 超标准（按人工确认数判定）'),
        sa.Column('photo_keys', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='平皿照片对象键列表（MinIO/本地兜底）'),
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
        schema='quality'
        )
    op.create_index('ix_quality_micro_batch', 'quality_micro_records', ['batch_number'], unique=False, schema='quality')
    op.create_index('ix_quality_micro_sample_date', 'quality_micro_records', ['sample_date'], unique=False, schema='quality')


def downgrade() -> None:
    op.drop_index('ix_quality_micro_sample_date', table_name='quality_micro_records', schema='quality')
    op.drop_index('ix_quality_micro_batch', table_name='quality_micro_records', schema='quality')
    op.drop_table('quality_micro_records', schema='quality')
