"""drop_hazard_revision_tables

Revision ID: 824fbcebd3f2
Revises: a7b8c9d0e1f2
Create Date: 2026-06-08 14:48:57.137446
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '824fbcebd3f2'
down_revision: Union[str, None] = '63e0261d5871'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("hazard_revision_records", schema="safety")
    op.drop_table("hazard_revision_archives", schema="safety")


def downgrade() -> None:
    # 删除表是不可逆操作，降级时无法恢复表结构和数据
    # 如需恢复，需要从备份重建
    pass
