"""qa deviation root cause categories

偏差根本原因分类由单选 String(32) 改为 JSONB 多选 root_cause_categories；
存量单值迁移为单元素数组。分类进 JSONB 后无法参与 btree 等值，重复偏差
识别索引改为锚定部门/组别/发现日期窗口。

Revision ID: e7b41d0c6a92
Revises: 71e1f8b48a9b
Create Date: 2026-11-24 10:30:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e7b41d0c6a92'
down_revision: str | None = '71e1f8b48a9b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = 'deviations'
_SCHEMA = 'qa'
_CATEGORIES = 'root_cause_categories'
_CATEGORY = 'root_cause_category'


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            _CATEGORIES,
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment='根本原因分类（多选，RootCauseCategory 值列表）',
        ),
        schema=_SCHEMA,
    )
    # 存量单值 → 单元素数组（含软删行，避免 downgrade 往返丢数据）。
    op.execute(
        f"UPDATE {_SCHEMA}.{_TABLE} "
        f"SET {_CATEGORIES} = jsonb_build_array({_CATEGORY}) "
        f"WHERE {_CATEGORY} IS NOT NULL"
    )
    op.drop_constraint(
        'ck_qa_deviations_root_cause_category', _TABLE, schema=_SCHEMA, type_='check'
    )
    op.drop_index('ix_qa_deviations_repeat_key', schema=_SCHEMA)
    op.create_index(
        'ix_qa_deviations_repeat_key',
        _TABLE,
        ['department_name', 'group_name', 'discovery_date'],
        schema=_SCHEMA,
    )
    op.drop_column(_TABLE, _CATEGORY, schema=_SCHEMA)


def downgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(_CATEGORY, sa.String(length=32), nullable=True, comment='根本原因分类'),
        schema=_SCHEMA,
    )
    # 多值无法无损回单值，取首个分类（保序，与升级前首选一致）。
    op.execute(
        f"UPDATE {_SCHEMA}.{_TABLE} "
        f"SET {_CATEGORY} = {_CATEGORIES}->>0 "
        f"WHERE jsonb_array_length({_CATEGORIES}) > 0"
    )
    op.drop_index('ix_qa_deviations_repeat_key', schema=_SCHEMA)
    op.create_index(
        'ix_qa_deviations_repeat_key',
        _TABLE,
        ['department_name', 'group_name', _CATEGORY],
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        'ck_qa_deviations_root_cause_category',
        _TABLE,
        f"{_CATEGORY} IS NULL OR {_CATEGORY} IN "
        "('personnel', 'equipment', 'material', 'method', 'environment', 'other')",
        schema=_SCHEMA,
    )
    op.drop_column(_TABLE, _CATEGORIES, schema=_SCHEMA)
