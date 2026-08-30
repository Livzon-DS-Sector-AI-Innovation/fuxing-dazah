"""fix batch2: widen result_text + unique index on employee_tags

Revision ID: b2fix0000001
Revises: c20d75e382ef
Create Date: 2026-08-28 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2fix0000001'
down_revision: str | None = 'c20d75e382ef'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 成绩说明列改为不限长文本（错题多时不再截断）
    op.alter_column(
        'qa_assessment_scores', 'result_text',
        existing_type=sa.String(length=16),
        type_=sa.Text(),
        existing_nullable=True,
        schema='hr',
    )
    # 员工标签去重（同一工号+标签仅保留最早一条；去首尾空格后比较，
    # 防止「A」与「A 」这类伪重复在随后建唯一索引时失败）
    op.execute(
        "DELETE FROM hr.employee_tags WHERE is_deleted = false AND id NOT IN "
        "(SELECT MIN(id::text)::uuid FROM hr.employee_tags WHERE is_deleted = false "
        "GROUP BY employee_number, btrim(tag_name))"
    )
    # 活跃行唯一（并发转训/批量打标防重复）
    op.create_index(
        'uq_employee_tags_active',
        'employee_tags',
        ['employee_number', 'tag_name'],
        unique=True,
        schema='hr',
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index('uq_employee_tags_active', table_name='employee_tags', schema='hr')
    op.alter_column(
        'qa_assessment_scores', 'result_text',
        existing_type=sa.Text(),
        type_=sa.String(length=16),
        existing_nullable=True,
        schema='hr',
    )
