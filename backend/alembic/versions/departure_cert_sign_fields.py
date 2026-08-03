"""add cert sign fields to departure_records

Revision ID: departure_cert_sign_001
Revises: 852441e765d4
Create Date: 2026-08-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'departure_cert_sign_001'
down_revision: Union[str, None] = '852441e765d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('departure_records', sa.Column('cert_sign_token', sa.String(64), nullable=True, comment='签署链接 token'), schema='hr')
    op.add_column('departure_records', sa.Column('cert_sign_status', sa.String(16), nullable=True, comment='签署状态: pending / signed'), schema='hr')
    op.add_column('departure_records', sa.Column('cert_signed_at', sa.DateTime(timezone=True), nullable=True, comment='签署时间'), schema='hr')
    op.add_column('departure_records', sa.Column('cert_sign_image', sa.Text(), nullable=True, comment='手写签名图片 base64'), schema='hr')
    op.add_column('departure_records', sa.Column('cert_sign_name', sa.String(64), nullable=True, comment='签署人确认姓名'), schema='hr')
    op.create_index('ix_departure_cert_sign_token', 'departure_records', ['cert_sign_token'], unique=True, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_departure_cert_sign_token', table_name='departure_records', schema='hr')
    op.drop_column('departure_records', 'cert_sign_name', schema='hr')
    op.drop_column('departure_records', 'cert_sign_image', schema='hr')
    op.drop_column('departure_records', 'cert_signed_at', schema='hr')
    op.drop_column('departure_records', 'cert_sign_status', schema='hr')
    op.drop_column('departure_records', 'cert_sign_token', schema='hr')
