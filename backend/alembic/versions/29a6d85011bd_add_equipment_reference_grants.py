"""add equipment reference grants and production equipment snapshots

Revision ID: 29a6d85011bd
Revises: 1b19dee8bb0f
Create Date: 2026-09-15 12:30:26.809703
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "29a6d85011bd"
down_revision: str | None = "1b19dee8bb0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS equipment")
    op.create_table(
        "equipment_reference_grants",
        sa.Column("equipment_id", sa.Uuid(), nullable=False, comment="设备ID"),
        sa.Column(
            "target_module",
            sa.String(length=64),
            nullable=False,
            comment="目标业务模块编码",
        ),
        sa.Column(
            "source",
            sa.String(length=20),
            server_default="manual",
            nullable=False,
            comment="授权来源：manual/auto_association",
        ),
        sa.Column("granted_by", sa.Uuid(), nullable=True, comment="授权操作人ID"),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="授权时间",
        ),
        sa.Column("revoked_by", sa.Uuid(), nullable=True, comment="撤销操作人ID"),
        sa.Column(
            "revoked_at", sa.DateTime(timezone=True), nullable=True, comment="撤销时间"
        ),
        sa.Column("remark", sa.Text(), nullable=True, comment="授权备注"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        # 与 BaseModel 的审计字段保持一致；设备/目标模块本身仍是逻辑引用，
        # 不建立跨业务表外键。
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "equipment_id",
            "target_module",
            name="uq_equipment_reference_grants_equipment_module",
        ),
        schema="equipment",
    )
    op.create_index(
        "ix_equipment_reference_grants_module_active",
        "equipment_reference_grants",
        ["target_module", "revoked_at"],
        unique=False,
        schema="equipment",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_equipment_reference_grants_equipment",
        "equipment_reference_grants",
        ["equipment_id"],
        unique=False,
        schema="equipment",
    )
    # 计划项保留新关联设备的服务端摘要快照；历史行保持 NULL，不做回填。
    op.add_column(
        "plan_items",
        sa.Column(
            "equipment_no",
            sa.String(length=50),
            nullable=True,
            comment="目标设备编号快照",
        ),
        schema="production",
    )
    op.add_column(
        "plan_items",
        sa.Column(
            "equipment_name",
            sa.String(length=200),
            nullable=True,
            comment="目标设备名称快照",
        ),
        schema="production",
    )


def downgrade() -> None:
    op.drop_column("plan_items", "equipment_name", schema="production")
    op.drop_column("plan_items", "equipment_no", schema="production")
    op.drop_index(
        "ix_equipment_reference_grants_equipment",
        table_name="equipment_reference_grants",
        schema="equipment",
    )
    op.drop_index(
        "ix_equipment_reference_grants_module_active",
        table_name="equipment_reference_grants",
        schema="equipment",
    )
    op.drop_table("equipment_reference_grants", schema="equipment")
