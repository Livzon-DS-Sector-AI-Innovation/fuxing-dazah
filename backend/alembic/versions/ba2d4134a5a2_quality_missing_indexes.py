"""quality: missing indexes

Revision ID: ba2d4134a5a2
Revises: d4819835e97d
Create Date: 2026-09-21 15:57:25.285100
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ba2d4134a5a2'
down_revision: Union[str, None] = 'd4819835e97d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES: list[tuple[str, str, list[str]]] = [
    # (索引名, 表名, 列)
    ("ix_quality_report_record_created", "report_records", ["created_at"]),
    ("ix_quality_report_record_task", "report_records", ["test_task_id"]),
    ("ix_quality_test_task_report_date", "quality_test_tasks", ["report_date"]),
    ("ix_quality_test_result_item_name", "quality_test_results", ["item_name"]),
    ("ix_quality_std_item_sop", "quality_standard_items", ["sop_no"]),
]


def upgrade() -> None:
    # 高频查询索引补齐：流水号计数/按日汇总、任务出报查询、每日推送/看板、趋势、SOP 关联
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols, unique=False, schema="quality")


def downgrade() -> None:
    for name, table, _cols in _INDEXES:
        op.drop_index(name, table_name=table, schema="quality")
