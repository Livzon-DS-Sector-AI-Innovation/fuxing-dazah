"""fix: change UniqueConstraint to partial unique indexes for soft-delete compatibility

Revision ID: 6917a7dadfe6
Revises: 897ee272491d
Create Date: 2026-07-03 16:58:55.178500
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6917a7dadfe6"
down_revision: str | None = "897ee272491d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 需要修复的约束列表：(constraint_name, table_name, columns)
_CONSTRAINTS = [
    ("uq_equipment_category_links", "equipment_category_links", ["equipment_id", "category_id"]),
    ("uq_equipment_personnel_category", "equipment_personnel_category", ["personnel_id", "role_id", "category_id"]),
    ("uq_equipment_personnel_role", "equipment_personnel_role", ["personnel_id", "role_id"]),
    ("uq_equipment_role_code", "equipment_role", ["code"]),
    ("uq_equipments_equipment_no", "equipments", ["equipment_no"]),
    ("uq_route_equipments_route_equipment", "inspection_route_equipments", ["route_id", "equipment_id"]),
    ("uq_route_schedules_route_cron_deleted", "inspection_route_schedules", ["route_id", "cron_expression"]),
    ("uq_inspection_routes_name", "inspection_routes", ["name"]),
    ("uq_inspection_tasks_task_no", "inspection_tasks", ["task_no"]),
    ("uq_work_orders_work_order_no", "work_orders", ["work_order_no"]),
]


def upgrade() -> None:
    for name, table, columns in _CONSTRAINTS:
        op.drop_constraint(name, table, schema="equipment", type_="unique")
        op.create_index(
            name,
            table,
            columns,
            unique=True,
            schema="equipment",
            postgresql_where=sa.text("is_deleted = false"),
        )


def downgrade() -> None:
    for name, table, columns in reversed(_CONSTRAINTS):
        op.drop_index(
            name,
            table_name=table,
            schema="equipment",
            postgresql_where=sa.text("is_deleted = false"),
        )
        op.create_unique_constraint(name, table, columns, schema="equipment")
