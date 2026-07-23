"""add email logs and offer tokens

Revision ID: 7f04ac1de356
Revises: 815c338bf916
Create Date: 2026-07-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '7f04ac1de356'
down_revision: Union[str, None] = '815c338bf916'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table('email_logs',
    sa.Column('email_type', sa.String(length=32), nullable=False, comment='类型: offer / departure_cert'),
    sa.Column('employee_id', sa.Uuid(), nullable=True, comment='员工ID'),
    sa.Column('employee_name', sa.String(length=64), nullable=True),
    sa.Column('recipient', sa.String(length=256), nullable=False, comment='收件邮箱'),
    sa.Column('subject', sa.String(length=256), nullable=False, comment='邮件主题'),
    sa.Column('status', sa.String(length=16), server_default='sent', nullable=False, comment='sent / failed'),
    sa.Column('error_message', sa.Text(), nullable=True, comment='失败原因'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_email_logs_employee_id', 'email_logs', ['employee_id'], unique=False, schema='hr')
    op.create_table('offer_tokens',
    sa.Column('token', sa.String(length=64), nullable=False, comment='唯一Token'),
    sa.Column('employee_id', sa.Uuid(), nullable=True),
    sa.Column('employee_name', sa.String(length=64), nullable=False),
    sa.Column('candidate_email', sa.String(length=256), nullable=False),
    sa.Column('offer_details', sa.JSON(), nullable=True, comment='Offer 内容快照'),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False, comment='pending / accepted / declined'),
    sa.Column('declined_reason', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, comment='过期时间'),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token'),
    schema='hr'
    )
    op.create_index('ix_offer_tokens_token', 'offer_tokens', ['token'], unique=True, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_offer_tokens_token', table_name='offer_tokens', schema='hr')
    op.drop_table('offer_tokens', schema='hr')
    op.drop_index('ix_email_logs_employee_id', table_name='email_logs', schema='hr')
    op.drop_table('email_logs', schema='hr')
