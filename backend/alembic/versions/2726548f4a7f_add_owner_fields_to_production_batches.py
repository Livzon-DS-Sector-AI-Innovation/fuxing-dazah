"""add owner fields to production batches

Revision ID: 2726548f4a7f
Revises: 7297b0bd733d
Create Date: 2026-08-13 16:36:20.706684
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2726548f4a7f'
down_revision: Union[str, None] = '7297b0bd733d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('batches', sa.Column('owner_user_id', sa.Uuid(), nullable=True, comment='批次归属人，接收/开始工序时写入；空=无主共享'), schema='production')
    op.add_column('batches', sa.Column('owner_name', sa.String(length=50), nullable=True, comment='归属人姓名快照'), schema='production')


def downgrade() -> None:
    op.drop_column('batches', 'owner_name', schema='production')
    op.drop_column('batches', 'owner_user_id', schema='production')
