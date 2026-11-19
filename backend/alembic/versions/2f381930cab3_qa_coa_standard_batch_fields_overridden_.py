"""qa coa: 标准批次字段覆盖标志 + 删字段配置死列（is_active/remark）

Revision ID: 2f381930cab3
Revises: f2d7a9c3e5b1
Create Date: 2026-11-19 11:12:46.263717

「有没有行」无法区分「沿用产品默认」与「显式空自定义集」，改由标准上的
布尔标志表达：true 时即使 coa_standard_fields 无行也按空集（仅内置 3 字段），
不再回落产品默认。存量有覆盖行的标准回填 true。
字段配置的 is_active/remark 没有任何读路径（编辑器也无开关），一并删除。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2f381930cab3'
down_revision: str | None = 'f2d7a9c3e5b1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'coa_standards',
        sa.Column(
            'batch_fields_overridden',
            sa.Boolean(),
            server_default='false',
            nullable=False,
            comment='批次字段集是否自定义覆盖（true 时即使无行也按空自定义集）',
        ),
        schema='qa',
    )
    op.execute(
        "UPDATE qa.coa_standards SET batch_fields_overridden = true "
        "WHERE id IN ("
        "SELECT DISTINCT standard_id FROM qa.coa_standard_fields "
        "WHERE is_deleted = false)"
    )
    for table in ('coa_product_fields', 'coa_standard_fields'):
        op.drop_column(table, 'is_active', schema='qa')
        op.drop_column(table, 'remark', schema='qa')


def downgrade() -> None:
    for table in ('coa_product_fields', 'coa_standard_fields'):
        op.add_column(
            table,
            sa.Column(
                'is_active',
                sa.Boolean(),
                server_default='true',
                nullable=False,
                comment='停用后阶段二不再渲染该字段',
            ),
            schema='qa',
        )
        op.add_column(
            table,
            sa.Column('remark', sa.String(length=500), nullable=True, comment='备注'),
            schema='qa',
        )
    op.drop_column('coa_standards', 'batch_fields_overridden', schema='qa')
