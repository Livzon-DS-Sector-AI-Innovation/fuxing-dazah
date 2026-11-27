"""岗位库增加招聘岗位信息（岗位职责 / 任职要求）

每个岗位保存一份可复用的岗位描述，新建岗位需求时带出到需求上，不必每次重新填写。
同时把历史岗位需求里已经填过的描述回填到对应岗位（同一岗位招过多次取最近一次；
只回填岗位库，原有岗位需求不动）。

Revision ID: a498ba51f85a
Revises: b8d2e6a4c1f3
Create Date: 2026-11-27 13:48:54.731009
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a498ba51f85a'
down_revision: str | None = 'b8d2e6a4c1f3'
branch_labels: str | None = None
depends_on: str | None = None

# 只回填能对上岗位库的（部门, 岗位名）：需求上的岗位名可能手填，对不上的没有落点，不回填
_BACKFILL_SQL = """
UPDATE hr.positions AS p
SET recruitment_duties = src.duties,
    recruitment_requirements = src.requirements,
    updated_at = now()
FROM (
    SELECT DISTINCT ON (department, position_name)
           department, position_name, duties, requirements
    FROM hr.job_requirements
    WHERE is_deleted = false
      AND (COALESCE(duties, '') <> '' OR COALESCE(requirements, '') <> '')
    ORDER BY department, position_name, created_at DESC NULLS LAST
) AS src
WHERE p.is_deleted = false
  AND p.department = src.department
  AND p.name = src.position_name
"""


def upgrade() -> None:
    op.add_column(
        'positions',
        sa.Column('recruitment_duties', sa.Text(), nullable=True, comment='招聘岗位信息：岗位职责'),
        schema='hr',
    )
    op.add_column(
        'positions',
        sa.Column('recruitment_requirements', sa.Text(), nullable=True, comment='招聘岗位信息：任职要求'),
        schema='hr',
    )
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    op.drop_column('positions', 'recruitment_requirements', schema='hr')
    op.drop_column('positions', 'recruitment_duties', schema='hr')
