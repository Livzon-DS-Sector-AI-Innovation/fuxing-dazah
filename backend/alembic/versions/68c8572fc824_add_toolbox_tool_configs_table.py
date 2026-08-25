"""add toolbox tool_configs table

Revision ID: 68c8572fc824
Revises: 2d63ff432471
Create Date: 2026-08-25 17:17:50.324456
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '68c8572fc824'
down_revision: Union[str, None] = '2d63ff432471'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('tool_configs',
    sa.Column('tool_id', sa.String(length=64), nullable=False, comment='工具 ID（如 attendance-check）'),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='工具配置 JSON（整体读写）'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tool_id', 'is_deleted', name='uq_toolbox_tool_configs_tool_id'),
    schema='toolbox'
    )


def downgrade() -> None:
    op.drop_table('tool_configs', schema='toolbox')
