"""add production notification_configs

Revision ID: 286c8ec29dd9
Revises: a7e3c91d5f02
Create Date: 2026-09-07 16:56:41.762318
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '286c8ec29dd9'
down_revision: Union[str, None] = 'a7e3c91d5f02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('notification_configs',
    sa.Column('notify_type', sa.String(length=50), nullable=False, comment='通知类型编码'),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='是否启用'),
    sa.Column('extra_recipients', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='额外通知人员 user_id 列表'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('uq_production_notification_configs', 'notification_configs', ['notify_type'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_production_notification_configs', table_name='notification_configs', schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('notification_configs', schema='production')
