"""drop cas_no from chemical inventory records

删除总表 CAS号 字段（同时前端/规则引擎已移除，缺MSDS 规则一并取消）。

Revision ID: 38387c4de6c6
Revises: 3e458ad42c52
Create Date: 2026-08-24 17:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '38387c4de6c6'
down_revision: Union[str, None] = '3e458ad42c52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('chemical_inventory_records', 'cas_no', schema='safety')


def downgrade() -> None:
    op.add_column(
        'chemical_inventory_records',
        sa.Column('cas_no', sa.String(length=64), nullable=True, comment='CAS号'),
        schema='safety',
    )
