"""巡检设备现场说明表

计划外突发现象的自由文字记录（不属任何检查项），挂在巡检任务×设备粒度，
支持同设备多条追加。入口：机器人提交/补记、Web 执行页随设备提交。

Revision ID: a7c3d91e4f20
Revises: 2f381930cab3
Create Date: 2026-11-19

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7c3d91e4f20"
down_revision = "2f381930cab3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inspection_equipment_notes",
        sa.Column("task_id", sa.Uuid(), nullable=False, comment="巡检任务ID"),
        sa.Column("equipment_id", sa.Uuid(), nullable=False, comment="设备ID"),
        sa.Column("content", sa.Text(), nullable=False, comment="现场说明内容"),
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
        sa.Column(
            "is_deleted", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["identity.users.id"]
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"], ["equipment.equipments.id"]
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["equipment.inspection_tasks.id"]
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["identity.users.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="equipment",
    )
    op.create_index(
        "ix_inspection_equipment_notes_task_equipment",
        "inspection_equipment_notes",
        ["task_id", "equipment_id"],
        schema="equipment",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inspection_equipment_notes_task_equipment",
        table_name="inspection_equipment_notes",
        schema="equipment",
    )
    op.drop_table("inspection_equipment_notes", schema="equipment")
