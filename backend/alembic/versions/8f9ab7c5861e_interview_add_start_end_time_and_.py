"""interview add start end time and conflict index

面试表新增起止钟点字段与面试官+日期冲突查询索引。

Revision ID: 8f9ab7c5861e
Revises: d8f4b2c61e90
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f9ab7c5861e'
down_revision: Union[str, None] = 'd8f4b2c61e90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 仅保留 hr.interviews 的变更（autogenerate 混入的其他模块差异已按规范清理）
    op.add_column('interviews', sa.Column('start_time', sa.Time(), nullable=True, comment='面试开始时间（钟点）'), schema='hr')
    op.add_column('interviews', sa.Column('end_time', sa.Time(), nullable=True, comment='面试结束时间（钟点）'), schema='hr')
    op.create_index('ix_interviews_interviewer_date', 'interviews', ['interviewer', 'interview_date'], schema='hr')


def downgrade() -> None:
    op.drop_index('ix_interviews_interviewer_date', table_name='interviews', schema='hr')
    op.drop_column('interviews', 'end_time', schema='hr')
    op.drop_column('interviews', 'start_time', schema='hr')
