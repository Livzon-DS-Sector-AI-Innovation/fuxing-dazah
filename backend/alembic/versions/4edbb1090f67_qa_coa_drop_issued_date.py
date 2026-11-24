"""qa coa drop issued_date

出具日期列无实际意义（流水号已含日期与编号信息），删除该列；
列表排序索引改为 (product_id, created_at)。

Revision ID: 4edbb1090f67
Revises: b3e5c8f1a240
Create Date: 2026-11-23 16:56:23.988375
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4edbb1090f67'
down_revision: Union[str, None] = 'b3e5c8f1a240'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_qa_coa_reports_product', table_name='coa_reports', schema='qa')
    op.drop_column('coa_reports', 'issued_date', schema='qa')
    op.create_index(
        'ix_qa_coa_reports_product',
        'coa_reports',
        ['product_id', 'created_at'],
        schema='qa',
    )


def downgrade() -> None:
    op.drop_index('ix_qa_coa_reports_product', table_name='coa_reports', schema='qa')
    op.add_column(
        'coa_reports',
        sa.Column('issued_date', sa.Date(), nullable=True, comment='出具日期（人工填写）'),
        schema='qa',
    )
    op.create_index(
        'ix_qa_coa_reports_product',
        'coa_reports',
        ['product_id', 'issued_date'],
        schema='qa',
    )
