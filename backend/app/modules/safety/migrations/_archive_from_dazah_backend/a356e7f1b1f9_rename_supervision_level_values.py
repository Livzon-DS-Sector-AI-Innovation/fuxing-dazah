"""rename_supervision_level_values

Revision ID: a356e7f1b1f9
Revises: 314f6e376dc1
Create Date: 2026-07-29 15:45:13.442915

数据迁移：督办等级 old values → new values
  overdue / 超期 → 红色预警
  normal  / 一般 → 一般预警
  warning / 预警 → 一般预警
  closed  / 已关闭 → closed（不变）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a356e7f1b1f9'
down_revision: Union[str, None] = '314f6e376dc1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE safety.hazard_reports SET supervision_level = '红色预警' WHERE supervision_level IN ('overdue', 'urgent', '超期')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE safety.hazard_reports SET supervision_level = '一般预警' WHERE supervision_level IN ('normal', 'warning', '预警', '一般')"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE safety.hazard_reports SET supervision_level = 'overdue' WHERE supervision_level = '红色预警'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE safety.hazard_reports SET supervision_level = 'normal'  WHERE supervision_level = '一般预警'"
        )
    )
