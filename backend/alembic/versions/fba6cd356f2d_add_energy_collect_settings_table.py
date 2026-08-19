"""add energy_collect_settings table

Revision ID: fba6cd356f2d
Revises: db50a555822f
Create Date: 2026-08-18 15:39:22.975297
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'fba6cd356f2d'
down_revision: Union[str, None] = 'db50a555822f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS energy")
    op.create_table('energy_collect_settings',
    sa.Column('setting_key', sa.String(length=64), nullable=False, comment='配置键'),
    sa.Column('setting_value', sa.Text(), nullable=False, comment='配置值'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('setting_key', 'is_deleted', name='uq_energy_collect_setting_key'),
    schema='energy'
    )


def downgrade() -> None:
    op.drop_table('energy_collect_settings', schema='energy')
