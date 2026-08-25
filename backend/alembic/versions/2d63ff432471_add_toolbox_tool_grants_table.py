"""add_toolbox_tool_grants_table

Revision ID: 2d63ff432471
Revises: 7260d1dedfbf
Create Date: 2026-08-25 11:28:27.591151
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2d63ff432471'
down_revision: str | None = '7260d1dedfbf'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS toolbox")
    op.create_table('tool_grants',
        sa.Column('user_id', sa.Uuid(), nullable=False, comment='用户 ID (identity.users)'),
        sa.Column('tool_id', sa.String(length=64), nullable=False, comment='工具 ID（如 attendance-check）'),
        sa.Column('can_use', sa.Boolean(), server_default='false', nullable=False, comment='是否可使用该工具'),
        sa.Column('can_config', sa.Boolean(), server_default='false', nullable=False, comment='是否可修改该工具配置'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'tool_id', name='uq_toolbox_tool_grants_user_tool'),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        schema='toolbox'
    )
    op.create_index('ix_toolbox_tool_grants_tool_id', 'tool_grants', ['tool_id'], unique=False, schema='toolbox')


def downgrade() -> None:
    op.drop_index('ix_toolbox_tool_grants_tool_id', table_name='tool_grants', schema='toolbox')
    op.drop_table('tool_grants', schema='toolbox')
