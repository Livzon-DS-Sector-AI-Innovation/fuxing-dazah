"""candidate_analysis_report_add_basic_info_jd_review

Revision ID: 9ce7cc860598
Revises: b7d2e6f40a13
Create Date: 2026-11-13 15:08:44.644594
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ce7cc860598'
down_revision: Union[str, None] = 'b7d2e6f40a13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 仅本模块变更：胜任度报告表加候选人基本信息与岗位要求回顾（autogenerate 混入的其他模块 DDL 已手动清理）
    op.add_column('candidate_analysis_reports', sa.Column('basic_info', sa.JSON(), nullable=True, comment='候选人基本信息 [{label, value}]（AI 从简历正文/面试记录提取）'), schema='hr')
    op.add_column('candidate_analysis_reports', sa.Column('jd_review', sa.Text(), nullable=True, comment='岗位要求回顾原文（生成时从JD拷贝存档）'), schema='hr')


def downgrade() -> None:
    op.drop_column('candidate_analysis_reports', 'jd_review', schema='hr')
    op.drop_column('candidate_analysis_reports', 'basic_info', schema='hr')
