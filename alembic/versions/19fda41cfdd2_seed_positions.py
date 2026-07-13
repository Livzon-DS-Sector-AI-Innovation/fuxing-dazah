"""seed positions data

Revision ID: 19fda41cfdd2
Revises: 06e6fb808f47
Create Date: 2026-07-13 18:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = '19fda41cfdd2'
down_revision: Union[str, None] = '06e6fb808f47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 种子数据由 scripts/seed_positions.sql 提供，服务器部署时手动执行
    pass


def downgrade() -> None:
    pass
