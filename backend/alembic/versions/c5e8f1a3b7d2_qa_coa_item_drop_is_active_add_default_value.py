"""qa coa: 检测项目删 is_active（项目必然启用），加 text 型 default_value 预填默认值

Revision ID: c5e8f1a3b7d2
Revises: b9c4d2e6f8a1
Create Date: 2026-11-18 15:20:00.000000

移除项统一软删让号（原「被值引用的停用保留」语义随 is_active 一并废除，
历史值行 FK 仍有效）。default_value 供登记 COA 时对 text 型项目快捷预填。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c5e8f1a3b7d2'
down_revision: str | None = 'b9c4d2e6f8a1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 旧「停用保留」的项目改按新语义软删：否则删掉 is_active 后它们会重新
    # 变成有效项目（标准详情/矩阵列/导入缺失项都会复活）。值行仍引用原 id。
    op.execute(
        "UPDATE qa.coa_standard_items SET is_deleted = true WHERE is_active = false"
    )
    op.add_column(
        'coa_standard_items',
        sa.Column('default_value', sa.String(length=200), nullable=True,
                  comment='text 型项目登记时的预填默认值（如 符合规定），number 型禁用'),
        schema='qa',
    )
    op.drop_column('coa_standard_items', 'is_active', schema='qa')


def downgrade() -> None:
    op.add_column(
        'coa_standard_items',
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False,
                  comment='停用后矩阵不再显示该列'),
        schema='qa',
    )
    op.drop_column('coa_standard_items', 'default_value', schema='qa')
