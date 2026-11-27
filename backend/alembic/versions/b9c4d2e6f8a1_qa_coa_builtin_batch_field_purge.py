"""qa coa: 批次字段内置化存量清洗（品名/批号/流水号改代码常量，删同义键存量行）

Revision ID: b9c4d2e6f8a1
Revises: a1f3c8d5e7b2
Create Date: 2026-11-18 10:30:00.000000

品名/批号/流水号三字段改为代码常量（读时合并置顶、写路径拒绝），
库内只存自定义字段；本迁移删除历史导入产生的同义键行
（与 app.modules.qa.service.coa.common._BUILTIN_ALIASES 同口径的简化版归一）。
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b9c4d2e6f8a1'
down_revision: str | None = 'a1f3c8d5e7b2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# lower(key) 去空白/下划线/点/横线后比对的保留键及同义变体
_RESERVED_TOKENS = (
    # product_name
    'productname', 'product', '品名', '产品名称', '产品名',
    # batch_no
    'batchno', 'batchnumber', 'batch', 'lot', 'lotno', 'lotnumber',
    '批号', '批次号', '批次编号',
    # serial_no
    'serialno', 'serialnumber', 'sn', 'series', '流水号', '序列号',
)


def upgrade() -> None:
    tokens = ', '.join(f"'{t}'" for t in _RESERVED_TOKENS)
    for table in ('coa_product_fields', 'coa_standard_fields'):
        op.execute(
            rf"DELETE FROM qa.{table} "
            rf"WHERE regexp_replace(lower(key), '[\s._-]+', '', 'g') IN ({tokens})"
        )


def downgrade() -> None:
    # 数据清洗不可逆：内置字段由代码常量恒定提供，被删行无需恢复
    pass
