"""qa coa drop conclusion

结论列全链路移除（报告头不再有检验结论固定字段；模板确需结论可配
批次字段，值进 batch_data 不再镜像写列）。

Revision ID: 71e1f8b48a9b
Revises: 4edbb1090f67
Create Date: 2026-11-23 17:20:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '71e1f8b48a9b'
down_revision: Union[str, None] = '4edbb1090f67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('coa_reports', 'conclusion', schema='qa')


def downgrade() -> None:
    op.add_column(
        'coa_reports',
        sa.Column('conclusion', sa.String(length=500), nullable=True, comment='结论'),
        schema='qa',
    )
