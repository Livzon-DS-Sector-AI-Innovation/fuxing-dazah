"""update_instrument_status_idle_to_overdue

Revision ID: 6a2b07b83bb1
Revises: 3b3833d6e568
Create Date: 2026-07-03 15:04:53.435513
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6a2b07b83bb1'
down_revision: Union[str, None] = '3b3833d6e568'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """将状态为'闲置'的仪表改为'超期'。

    同时'超期'也由系统动态判定：仅当存储状态为'在用'且下次检定日期已过期时显示为'超期'。
    '停用'为人工手动设置，检定过期也不会变为'超期'。
    """
    op.execute("""
        UPDATE meter.instrument_records
        SET status = '超期'
        WHERE status = '闲置' AND is_deleted = false
    """)


def downgrade() -> None:
    """注意：无法准确还原哪些'超期'原本是'闲置'，仅做占位。"""
    pass
