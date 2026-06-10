"""fix_equipment_category_links_unique_constraint

Revision ID: dcb4574b9b80
Revises: d53088ef2a74
Create Date: 2026-06-10 10:34:55.214539
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dcb4574b9b80'
down_revision: Union[str, None] = 'd53088ef2a74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 清理重复数据：同一 (equipment_id, category_id) 保留一条 active 记录，删除其余
    op.execute("""
        DELETE FROM equipment.equipment_category_links
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY equipment_id, category_id
                           ORDER BY is_deleted ASC, created_at ASC
                       ) AS rn
                FROM equipment.equipment_category_links
            ) AS ranked
            WHERE rn > 1
        )
    """)

    # 2. 删除旧约束（含 is_deleted），创建新约束（不含 is_deleted）
    op.drop_constraint(
        op.f('uq_equipment_category_links'), 'equipment_category_links',
        schema='equipment', type_='unique',
    )
    op.create_unique_constraint(
        'uq_equipment_category_links', 'equipment_category_links',
        ['equipment_id', 'category_id'], schema='equipment',
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_equipment_category_links', 'equipment_category_links',
        schema='equipment', type_='unique',
    )
    op.create_unique_constraint(
        op.f('uq_equipment_category_links'), 'equipment_category_links',
        ['equipment_id', 'category_id', 'is_deleted'], schema='equipment',
        postgresql_nulls_not_distinct=False,
    )
