"""maintenance: executor_id rename, category_id, drop inspection order_type

Revision ID: 00b1b23aab64
Revises: 241f68a331ab
Create Date: 2026-06-25 10:32:05.433752
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '00b1b23aab64'
down_revision: Union[str, None] = '241f68a331ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS equipment")

    conn = op.get_bind()

    # 1. Rename responsible_person_id → executor_id on maintenance_plans
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'equipment' AND table_name = 'maintenance_plans' "
            "AND column_name = 'responsible_person_id'"
        )
    )
    if result.fetchone():
        op.alter_column(
            "maintenance_plans",
            "responsible_person_id",
            new_column_name="executor_id",
            existing_type=sa.dialects.postgresql.UUID(),
            schema="equipment",
        )

    # 2. Add category_id column if not exists
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'equipment' AND table_name = 'maintenance_plans' "
            "AND column_name = 'category_id'"
        )
    )
    if not result.fetchone():
        op.add_column(
            "maintenance_plans",
            sa.Column("category_id", sa.dialects.postgresql.UUID(), nullable=True),
            schema="equipment",
        )

    # 3. Make equipment_id nullable
    op.alter_column(
        "maintenance_plans",
        "equipment_id",
        existing_type=sa.dialects.postgresql.UUID(),
        nullable=True,
        schema="equipment",
    )

    # 4. Drop + recreate constraint to remove '巡检' from order_type
    op.execute(
        "ALTER TABLE equipment.work_orders "
        "DROP CONSTRAINT IF EXISTS ck_work_orders_order_type"
    )
    op.create_check_constraint(
        "ck_work_orders_order_type",
        "work_orders",
        "order_type IN ('故障维修', '计划维护', '校准', '异常处理', '日常维护')",
        schema="equipment",
    )


def downgrade() -> None:
    # 4. Restore original order_type constraint (with 巡检)
    op.execute(
        "ALTER TABLE equipment.work_orders "
        "DROP CONSTRAINT IF EXISTS ck_work_orders_order_type"
    )
    op.create_check_constraint(
        "ck_work_orders_order_type",
        "work_orders",
        "order_type IN ('故障维修', '计划维护', '巡检', '校准', '异常处理', '日常维护')",
        schema="equipment",
    )

    # 3. Make equipment_id not nullable
    op.alter_column(
        "maintenance_plans",
        "equipment_id",
        existing_type=sa.dialects.postgresql.UUID(),
        nullable=False,
        schema="equipment",
    )

    # 2. Drop category_id
    op.drop_column("maintenance_plans", "category_id", schema="equipment")

    # 1. Rename executor_id back to responsible_person_id
    op.alter_column(
        "maintenance_plans",
        "executor_id",
        new_column_name="responsible_person_id",
        existing_type=sa.dialects.postgresql.UUID(),
        schema="equipment",
    )
