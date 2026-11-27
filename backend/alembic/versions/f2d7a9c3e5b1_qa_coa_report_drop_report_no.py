"""qa coa: 报告表删 report_no（业务不用编号，批次即业务键）

Revision ID: f2d7a9c3e5b1
Revises: d7b3f2a9c4e1
Create Date: 2026-11-18 17:30:00.000000

报告编号对业务无用：唯一性由 (product, standard, batch_no) 保证；
docx 里印的编号仅留作导入解析的匹配锚点与 raw_extract 留底，不再存档。
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2d7a9c3e5b1'
down_revision: str | None = 'd7b3f2a9c4e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index('uq_qa_coa_reports_no', table_name='coa_reports', schema='qa')
    op.drop_column('coa_reports', 'report_no', schema='qa')


def downgrade() -> None:
    raise NotImplementedError('报告编号字段已按业务决策移除，不回滚')
