"""add tech domain to title applications

Revision ID: a169a1c2deaa
Revises: fb560f5ad3c8
Create Date: 2026-08-21 15:30:00.000000

职称评审对齐管理办法第四条：技术职级分"研发/生产技术类"与"技术服务类"两个领域。
仅 hr 表变更，其他模块无关变更已清理。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a169a1c2deaa'
down_revision: Union[str, None] = 'fb560f5ad3c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('title_review_applications', sa.Column('tech_domain', sa.String(length=32), nullable=True, comment='技术领域：研发/生产技术类、技术服务类（技术职级适用）'), schema='hr')


def downgrade() -> None:
    op.drop_column('title_review_applications', 'tech_domain', schema='hr')
