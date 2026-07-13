"""seed SOP catalog and position trainings data

Revision ID: 21fda41cfdd4
Revises: 20fda41cfdd3
Create Date: 2026-07-13 20:40:00.000000
"""
from typing import Sequence, Union
from alembic import op
from pathlib import Path

revision: str = '21fda41cfdd4'
down_revision: Union[str, None] = '20fda41cfdd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SOP 和岗位培训数据量大（~8MB），alembic 逐行执行太慢
    # 请在服务器上部署后手动执行：
    #   psql -U postgres -d dazah -f scripts/seed_sop_data.sql
    pass


def downgrade() -> None:
    pass
