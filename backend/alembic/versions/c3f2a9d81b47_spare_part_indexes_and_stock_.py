"""equipment spare part indexes and stock partial unique

备件功能优化配套迁移：
- 流水表（全系统增长最快的表之一）补 spare_part_id / work_order_id / created_at 索引
- 备件主数据补 department_id / category 索引（数据范围过滤与分类筛选）
- 设备-备件关联补 spare_part_id 软删条件索引（按备件反查关联）
- 库存表 spare_part_id 全表唯一约束改为软删条件部分唯一索引，
  消除「软删备件后无法重建库存行」的隐患

Revision ID: c3f2a9d81b47
Revises: a7ad46fc8f5b
Create Date: 2026-10-19 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3f2a9d81b47'
down_revision: Union[str, None] = 'a7ad46fc8f5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _stock_unique_constraint_name() -> str:
    """库存表 spare_part_id 唯一约束的实测名（建表时未显式命名，PG 自动命名）"""
    conn = op.get_bind()
    return conn.execute(sa.text(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = 'equipment.spare_part_stocks'::regclass "
        "AND contype = 'u'"
    )).scalar()


def upgrade() -> None:
    op.create_index(
        'ix_spare_part_transactions_spare_part_id',
        'spare_part_transactions', ['spare_part_id'], schema='equipment',
    )
    op.create_index(
        'ix_spare_part_transactions_work_order_id',
        'spare_part_transactions', ['work_order_id'], schema='equipment',
    )
    op.create_index(
        'ix_spare_part_transactions_created_at',
        'spare_part_transactions', ['created_at'], schema='equipment',
    )
    op.create_index(
        'ix_spare_parts_department_id',
        'spare_parts', ['department_id'], schema='equipment',
    )
    op.create_index(
        'ix_spare_parts_category',
        'spare_parts', ['category'], schema='equipment',
    )
    op.create_index(
        'ix_equipment_spare_parts_spare_part_id',
        'equipment_spare_parts', ['spare_part_id'], schema='equipment',
        postgresql_where=sa.text('is_deleted = false'),
    )

    # 全表唯一 → 软删条件部分唯一
    constraint_name = _stock_unique_constraint_name()
    if constraint_name:
        op.drop_constraint(
            constraint_name, 'spare_part_stocks', schema='equipment', type_='unique',
        )
    op.create_index(
        'uq_spare_part_stocks_spare_part_id',
        'spare_part_stocks', ['spare_part_id'], schema='equipment',
        unique=True, postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_spare_part_stocks_spare_part_id', table_name='spare_part_stocks',
        schema='equipment', postgresql_where=sa.text('is_deleted = false'),
    )
    op.create_unique_constraint(
        'spare_part_stocks_spare_part_id_key', 'spare_part_stocks',
        ['spare_part_id'], schema='equipment',
    )
    op.drop_index(
        'ix_equipment_spare_parts_spare_part_id', table_name='equipment_spare_parts',
        schema='equipment', postgresql_where=sa.text('is_deleted = false'),
    )
    op.drop_index(
        'ix_spare_parts_category', table_name='spare_parts', schema='equipment',
    )
    op.drop_index(
        'ix_spare_parts_department_id', table_name='spare_parts', schema='equipment',
    )
    op.drop_index(
        'ix_spare_part_transactions_created_at', table_name='spare_part_transactions',
        schema='equipment',
    )
    op.drop_index(
        'ix_spare_part_transactions_work_order_id', table_name='spare_part_transactions',
        schema='equipment',
    )
    op.drop_index(
        'ix_spare_part_transactions_spare_part_id', table_name='spare_part_transactions',
        schema='equipment',
    )
