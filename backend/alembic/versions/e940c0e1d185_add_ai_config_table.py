"""add_ai_config_table

Revision ID: e940c0e1d185
Revises: f67967375be0
Create Date: 2026-07-02 14:19:19.104708
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e940c0e1d185'
down_revision: Union[str, None] = 'f67967375be0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('ai_config',
        sa.Column('api_url', sa.String(length=500), nullable=False, comment='OpenAI 兼容 API 端点'),
        sa.Column('api_key', sa.String(length=500), nullable=False, comment='API 密钥'),
        sa.Column('model', sa.String(length=200), server_default="'MiniMax-M2.5'::varchar", nullable=False, comment='模型名'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='meter'
    )


def downgrade() -> None:
    op.drop_table('ai_config', schema='meter')
