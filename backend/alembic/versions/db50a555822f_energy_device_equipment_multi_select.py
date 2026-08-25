"""energy device equipment multi-select

Revision ID: db50a555822f
Revises: 7297b0bd733d
Create Date: 2026-08-14 11:32:58.611783
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'db50a555822f'
down_revision: Union[str, None] = '7297b0bd733d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 单值 equipment_id/equipment_name → 多值 equipment_ids/equipment_names（JSONB 字符串数组）
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "ADD COLUMN equipment_ids JSONB NOT NULL DEFAULT '[]', "
        "ADD COLUMN equipment_names JSONB NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "COMMENT ON COLUMN energy.energy_device_configs.equipment_ids IS "
        "'关联设备ID列表（设备台账，JSON 字符串数组）'"
    )
    op.execute(
        "COMMENT ON COLUMN energy.energy_device_configs.equipment_names IS "
        "'关联设备名称列表（冗余存储，便于展示）'"
    )
    # 回填：把旧的单值迁移到单元素数组
    op.execute(
        "UPDATE energy.energy_device_configs SET "
        "equipment_ids = CASE WHEN equipment_id IS NOT NULL "
        "  THEN jsonb_build_array(equipment_id::text) ELSE '[]'::jsonb END, "
        "equipment_names = CASE WHEN equipment_name IS NOT NULL "
        "  THEN jsonb_build_array(equipment_name) ELSE '[]'::jsonb END"
    )
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "DROP COLUMN equipment_id, DROP COLUMN equipment_name"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "ADD COLUMN equipment_id UUID, ADD COLUMN equipment_name VARCHAR(200)"
    )
    # 多值 → 单值：仅取首元素（多选数据在回滚时会丢失其余元素）
    op.execute(
        "UPDATE energy.energy_device_configs SET "
        "equipment_id = (equipment_ids->>0)::uuid, "
        "equipment_name = equipment_names->>0"
    )
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "DROP COLUMN equipment_ids, DROP COLUMN equipment_names"
    )
