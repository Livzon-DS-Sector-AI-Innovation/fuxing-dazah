"""equipment status enum rework and running_status

设备状态枚举重构：在用/停用 → 完好（停用设备运行状态置停机），
新增设备运行状态字段 running_status（开机/停机）与状态日志 log_type 列，
并为存量设备写入运行状态基线记录（log_type='running', source='init'）。

Revision ID: a79d16d56870
Revises: 24578faff0f7
Create Date: 2026-07-15 16:47:27.988410
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a79d16d56870'
down_revision: str | None = '24578faff0f7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. 新增运行状态列（先可空，回填后收紧）
    op.add_column(
        'equipments',
        sa.Column('running_status', sa.String(length=10), nullable=True,
                  comment='运行状态：开机/停机'),
        schema='equipment',
    )
    # 2. 回填：在用 → 开机，其余（含停用）→ 停机
    op.execute(
        """
        UPDATE equipment.equipments
        SET running_status = CASE WHEN status = '在用' THEN '开机' ELSE '停机' END
        """
    )
    op.alter_column(
        'equipments', 'running_status',
        nullable=False, schema='equipment',
    )

    # 3. 设备状态枚举映射：先撤旧 CHECK 再改值（旧约束不含新枚举值）
    op.drop_constraint('ck_equipments_status', 'equipments', schema='equipment')
    op.execute(
        "UPDATE equipment.equipments SET status = '完好' WHERE status IN ('在用', '停用')"
    )

    # 4. 重建状态 CHECK 约束 + 新增运行状态 CHECK
    op.create_check_constraint(
        'ck_equipments_status',
        'equipments',
        "status IN ('完好', '备用', '故障待检', '维修中', '报废')",
        schema='equipment',
    )
    op.create_check_constraint(
        'ck_equipments_running_status',
        'equipments',
        "running_status IN ('开机', '停机')",
        schema='equipment',
    )

    # 5. 状态日志加 log_type 列（存量均为设备状态日志）
    op.add_column(
        'equipment_status_logs',
        sa.Column('log_type', sa.String(length=10), nullable=False,
                  server_default='status',
                  comment='日志类型：status(设备状态)/running(运行状态)'),
        schema='equipment',
    )

    # 6. 历史日志状态值映射
    op.execute(
        "UPDATE equipment.equipment_status_logs SET old_status = '完好' "
        "WHERE old_status IN ('在用', '停用')"
    )
    op.execute(
        "UPDATE equipment.equipment_status_logs SET new_status = '完好' "
        "WHERE new_status IN ('在用', '停用')"
    )

    # 7. 存量设备运行状态基线：开动率从此刻起算
    op.execute(
        """
        INSERT INTO equipment.equipment_status_logs
            (id, equipment_id, log_type, old_status, new_status, changed_at, source,
             created_at, updated_at, is_deleted)
        SELECT gen_random_uuid(), e.id, 'running', NULL, e.running_status, now(), 'init',
               now(), now(), false
        FROM equipment.equipments e
        WHERE e.is_deleted = false
        """
    )

    # 8. 工单快照字段同步映射（仅展示用途）
    op.execute(
        "UPDATE equipment.work_orders SET original_equipment_status = '完好' "
        "WHERE original_equipment_status IN ('在用', '停用')"
    )


def downgrade() -> None:
    # 运行状态日志删除；完好/故障待检 → 在用（停用信息不可逆，统一回在用）
    op.execute(
        "DELETE FROM equipment.equipment_status_logs WHERE log_type = 'running'"
    )
    op.drop_column('equipment_status_logs', 'log_type', schema='equipment')
    op.execute(
        "UPDATE equipment.equipment_status_logs SET old_status = '在用' "
        "WHERE old_status = '完好'"
    )
    op.execute(
        "UPDATE equipment.equipment_status_logs SET new_status = '在用' "
        "WHERE new_status = '完好'"
    )
    op.execute(
        "UPDATE equipment.work_orders SET original_equipment_status = '在用' "
        "WHERE original_equipment_status = '完好'"
    )
    op.drop_constraint('ck_equipments_running_status', 'equipments', schema='equipment')
    op.drop_constraint('ck_equipments_status', 'equipments', schema='equipment')
    op.execute(
        "UPDATE equipment.equipments SET status = '在用' "
        "WHERE status IN ('完好', '故障待检')"
    )
    op.create_check_constraint(
        'ck_equipments_status',
        'equipments',
        "status IN ('在用', '备用', '维修中', '停用', '报废')",
        schema='equipment',
    )
    op.drop_column('equipments', 'running_status', schema='equipment')
