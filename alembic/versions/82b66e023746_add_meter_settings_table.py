"""add meter_settings table

Revision ID: 82b66e023746
Revises: 717564ddd4e0
Create Date: 2026-07-07 18:23:10.402229
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82b66e023746'
down_revision: Union[str, None] = '717564ddd4e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('meter_settings',
        sa.Column('notify_time', sa.Time(), server_default=sa.text("'17:45'::time"), nullable=False, comment='每日提醒时间'),
        sa.Column('last_notify_date', sa.Date(), nullable=True, comment='上次发送日期，防止同一天重复发送'),
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
    op.drop_table('meter_settings', schema='meter')
