"""add_source_to_onboarding_records

Revision ID: cebe04fbaf3e
Revises: ff36e7e1856e
Create Date: 2026-07-20 00:14:01.626527
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'cebe04fbaf3e'
down_revision: Union[str, None] = 'ff36e7e1856e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('onboarding_records', sa.Column('source', sa.String(length=32), nullable=True, comment='来源: feishu/approval'), schema='hr')
    # 现有记录默认标记为 feishu
    op.execute("UPDATE hr.onboarding_records SET source = 'feishu' WHERE source IS NULL")


def downgrade() -> None:
    op.drop_column('onboarding_records', 'source', schema='hr')
