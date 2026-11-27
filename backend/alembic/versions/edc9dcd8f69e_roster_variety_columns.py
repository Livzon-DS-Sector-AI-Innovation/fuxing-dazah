"""roster variety columns

培训人员名单增加品种/兼任品种（签到表品种筛选所需，业务属性非隐私）。

Revision ID: edc9dcd8f69e
Revises: ba9d84f68fee
Create Date: 2026-11-10

说明：autogenerate 吸入的其他模块 drift 已按规范清理，只保留本模块 DDL + 回填。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'edc9dcd8f69e'
down_revision: Union[str, None] = 'ba9d84f68fee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('training_roster_profiles',
                  sa.Column('variety', sa.String(length=64), nullable=True, comment='品种'),
                  schema='hr')
    op.add_column('training_roster_profiles',
                  sa.Column('concurrent_variety', sa.String(length=256), nullable=True, comment='兼任品种'),
                  schema='hr')
    # 存量回填：从员工总表复制初值
    op.execute("""
        UPDATE hr.training_roster_profiles p
        SET variety = e.variety, concurrent_variety = e.concurrent_variety
        FROM hr.employees e
        WHERE p.employee_number = e.employee_number AND p.is_deleted = false
    """)


def downgrade() -> None:
    op.drop_column('training_roster_profiles', 'concurrent_variety', schema='hr')
    op.drop_column('training_roster_profiles', 'variety', schema='hr')
