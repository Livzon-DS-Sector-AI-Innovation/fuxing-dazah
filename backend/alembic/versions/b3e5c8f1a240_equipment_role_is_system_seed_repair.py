"""设备角色加 is_system 内置标记 + 幂等种子 repair 维修工角色

repair 编码是工单自动派单/维修候选人筛选的硬依赖（service.personnel.
REPAIR_ROLE_CODE），此前纯靠用户手建、可被随手删除。本次：
1. equipment_role 加 is_system 列（内置角色不可删/停用，编码与作用域锁定）；
2. 已有未删除的 code=repair 角色仅补 is_system=true（保留原 id 与人员绑定）；
3. 没有则种子一条「维修工」，description 写明该角色服务的业务场景。

Revision ID: b3e5c8f1a240
Revises: a7c3d91e4f20
Create Date: 2026-11-20

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b3e5c8f1a240"
down_revision = "hr_iv_score_push_001"
branch_labels = None
depends_on = None

REPAIR_ROLE_DESCRIPTION = (
    "系统内置·维修工：设备工单自动派单（巡检异常建单、维护计划）与负责人"
    "指派维修人时，均从持有此角色的人员中筛选候选人。请将维修工加入设备"
    "人员池并分配此角色，人员部门须与设备所属部门一致，可在人员管理中"
    "追加设备分类约束专长范围。此角色不可删除或停用。"
)


def upgrade() -> None:
    op.add_column(
        "equipment_role",
        sa.Column(
            "is_system",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="系统内置角色（不可删除/停用，编码与作用域锁定）",
        ),
        schema="equipment",
    )
    # 幂等种子：存量未删除的 repair 角色补标记，描述为空时补业务说明（不覆盖自定义描述）
    op.execute(
        sa.text(
            """
            UPDATE equipment.equipment_role
               SET is_system = true,
                   description = COALESCE(description, :desc)
             WHERE code = 'repair' AND is_deleted = false
            """
        ).bindparams(desc=REPAIR_ROLE_DESCRIPTION)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO equipment.equipment_role
                (id, name, code, description, scope, is_active, is_system,
                 is_deleted, created_at, updated_at)
            SELECT gen_random_uuid(), '维修工', 'repair', :desc, 'maintenance',
                   true, true, false, now(), now()
            WHERE NOT EXISTS (
                SELECT 1 FROM equipment.equipment_role
                 WHERE code = 'repair' AND is_deleted = false
            )
            """
        ).bindparams(desc=REPAIR_ROLE_DESCRIPTION)
    )


def downgrade() -> None:
    # 种子角色保留（可能已有人员绑定），仅回滚标记列
    op.drop_column("equipment_role", "is_system", schema="equipment")
