"""add inherent_risk_level_fj to hazard_identifications

Revision ID: 5932b971f04b
Revises: 4468fb610098
Create Date: 2026-08-13 10:53:51.667463

脚本3.5 福建固有风险评级：在 safety.hazard_identifications 新增
inherent_risk_level_fj 列，存福建表5-1 七指标综合固有风险等级中文名
（低风险/一般风险/较大风险/重大风险），由脚本3 成功后附属触发。
不进状态机、不占审核环节、存量不回填。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5932b971f04b'
down_revision: str | None = '4468fb610098'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增 safety.hazard_identifications.inherent_risk_level_fj 列。"""
    op.add_column(
        'hazard_identifications',
        sa.Column(
            'inherent_risk_level_fj',
            sa.String(length=50),
            nullable=True,
            comment='固有风险等级（福建）',
        ),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_column(
        'hazard_identifications',
        'inherent_risk_level_fj',
        schema='safety',
    )
