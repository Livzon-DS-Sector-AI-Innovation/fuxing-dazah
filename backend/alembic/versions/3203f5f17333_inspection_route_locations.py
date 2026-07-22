"""inspection_route_locations

Revision ID: 3203f5f17333
Revises: 68fbc17ff5e2
Create Date: 2026-06-18 09:23:24.014975
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3203f5f17333"
down_revision: Union[str, None] = "68fbc17ff5e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === 1. New tables ===
    op.create_table(
        "route_locations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("route_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("uq_route_locations_active", "route_id", "location_id",
                 unique=True, postgresql_where=sa.text("is_deleted = false")),
        schema="equipment",
    )
    op.create_table(
        "route_location_equipments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("route_location_id", sa.Uuid(), nullable=False),
        sa.Column("equipment_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("uq_route_location_equipments_active", "route_location_id", "equipment_id",
                 unique=True, postgresql_where=sa.text("is_deleted = false")),
        schema="equipment",
    )
    op.create_table(
        "route_equipment_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("route_equipment_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("uq_route_equipment_templates_active", "route_equipment_id", "template_id",
                 unique=True, postgresql_where=sa.text("is_deleted = false")),
        schema="equipment",
    )

    # === 2. inspection_records: add route_location_id ===
    op.add_column("inspection_records",
                  sa.Column("route_location_id", sa.Uuid(), nullable=True,
                            comment="关联线路地点（线路巡检时标记）"),
                  schema="equipment")

    # === 3. inspection_routes: drop area and template_id ===
    op.drop_column("inspection_routes", "area", schema="equipment")
    op.drop_column("inspection_routes", "template_id", schema="equipment")

    # === 4. inspection_tasks: template_id -> template_ids ===
    op.add_column("inspection_tasks",
                  sa.Column("template_ids", sa.JSON(), nullable=True,
                            comment="设备巡检绑定的模板ID列表"),
                  schema="equipment")
    op.execute(
        sa.text(
            "UPDATE equipment.inspection_tasks "
            "SET template_ids = CASE "
            "  WHEN template_id IS NOT NULL THEN jsonb_build_array(template_id::text) "
            "  ELSE NULL END"
        )
    )
    op.drop_column("inspection_tasks", "template_id", schema="equipment")

    # === 5. inspection_tasks: planned_date -> planned_time ===
    op.add_column("inspection_tasks",
                  sa.Column("planned_time", sa.DateTime(timezone=True), nullable=True,
                            comment="计划巡检时间"),
                  schema="equipment")
    op.execute(
        sa.text(
            "UPDATE equipment.inspection_tasks "
            "SET planned_time = (planned_date::text || ' 00:00:00+08')::timestamptz "
            "WHERE planned_date IS NOT NULL AND planned_time IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE equipment.inspection_tasks "
            "SET planned_time = created_at "
            "WHERE planned_time IS NULL"
        )
    )
    op.alter_column("inspection_tasks", "planned_time", nullable=False, schema="equipment")
    op.drop_column("inspection_tasks", "planned_date", schema="equipment")


def downgrade() -> None:
    op.add_column("inspection_tasks",
                  sa.Column("planned_date", sa.Date(), nullable=True), schema="equipment")
    op.execute(
        sa.text(
            "UPDATE equipment.inspection_tasks "
            "SET planned_date = planned_time::date "
            "WHERE planned_time IS NOT NULL"
        )
    )
    op.alter_column("inspection_tasks", "planned_date", nullable=False, schema="equipment")
    op.drop_column("inspection_tasks", "planned_time", schema="equipment")

    op.add_column("inspection_tasks",
                  sa.Column("template_id", sa.Uuid(), nullable=True), schema="equipment")
    op.execute(
        sa.text(
            "UPDATE equipment.inspection_tasks "
            "SET template_id = (template_ids->>0)::uuid "
            "WHERE template_ids IS NOT NULL AND jsonb_array_length(template_ids) > 0"
        )
    )
    op.drop_column("inspection_tasks", "template_ids", schema="equipment")

    op.add_column("inspection_routes",
                  sa.Column("area", sa.String(100), nullable=True), schema="equipment")
    op.add_column("inspection_routes",
                  sa.Column("template_id", sa.Uuid(), nullable=True), schema="equipment")

    op.drop_column("inspection_records", "route_location_id", schema="equipment")

    op.drop_table("route_equipment_templates", schema="equipment")
    op.drop_table("route_location_equipments", schema="equipment")
    op.drop_table("route_locations", schema="equipment")
