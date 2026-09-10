"""add hazard_level_manual to hazard_reports

Revision ID: 3f9a7c1b5d2f
Revises: 3f9a7c1b5d2e
Create Date: 2026-08-06 10:30:00.000000

新增隐患等级（人工）字段 hazard_level_manual：
  - 由 Bitable「隐患级别」字段同步（人工填写，权威等级）
  - 督办等级判定以此为唯一依据（不再用 AI 判定的 hazard_level）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f9a7c1b5d2f'
down_revision: Union[str, None] = '3f9a7c1b5d2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hazard_reports",
        sa.Column(
            "hazard_level_manual",
            sa.String(16),
            nullable=True,
            comment="隐患等级（人工）：一般隐患/较大隐患/重大隐患（Bitable 隐患级别字段同步，督办判定以此为准）",
        ),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("hazard_reports", "hazard_level_manual", schema="safety")
