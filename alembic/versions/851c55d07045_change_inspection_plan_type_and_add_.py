"""change_inspection_plan_type_and_add_route_check

Revision ID: 851c55d07045
Revises: e2b2fab66547
Create Date: 2026-06-10 09:29:19.049164
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '851c55d07045'
down_revision: Union[str, None] = 'e2b2fab66547'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 先删除旧约束，否则 UPDATE 会触发约束检查
    op.execute(
        "ALTER TABLE equipment.inspection_tasks "
        "DROP CONSTRAINT IF EXISTS ck_inspection_tasks_plan_type"
    )

    # 2. 数据迁移：旧类型映射为新类型
    op.execute(
        "UPDATE equipment.inspection_tasks "
        "SET plan_type = '设备巡检' "
        "WHERE plan_type IN ('日常巡检', '周巡检', '月巡检', '专项巡检')"
    )

    # 3. 添加新约束
    op.execute(
        "ALTER TABLE equipment.inspection_tasks "
        "ADD CONSTRAINT ck_inspection_tasks_plan_type "
        "CHECK (plan_type IN ('线路巡检', '设备巡检'))"
    )

    # 4. inspection_photos.equipment_id 改为可空
    op.alter_column('inspection_photos', 'equipment_id',
               existing_type=sa.UUID(),
               nullable=True,
               comment='设备ID（线路巡检时可为空）',
               existing_comment='设备ID',
               schema='equipment')

    # 5. 新增 route_summary 列
    op.add_column('inspection_tasks',
        sa.Column('route_summary', sa.Text(), nullable=True, comment='线路巡检现场描述'),
        schema='equipment')

    # 6. 更新 plan_type 列注释
    op.alter_column('inspection_tasks', 'plan_type',
               existing_type=sa.VARCHAR(length=20),
               comment='巡检类型：线路巡检/设备巡检',
               existing_comment='巡检类型：日常巡检/周巡检/月巡检/专项巡检',
               existing_nullable=False,
               schema='equipment')


def downgrade() -> None:
    # 1. 恢复 plan_type 列注释
    op.alter_column('inspection_tasks', 'plan_type',
               existing_type=sa.VARCHAR(length=20),
               comment='巡检类型：日常巡检/周巡检/月巡检/专项巡检',
               existing_comment='巡检类型：线路巡检/设备巡检',
               existing_nullable=False,
               schema='equipment')

    # 2. 删除 route_summary 列
    op.drop_column('inspection_tasks', 'route_summary', schema='equipment')

    # 3. 恢复 inspection_photos.equipment_id 为非空
    op.alter_column('inspection_photos', 'equipment_id',
               existing_type=sa.UUID(),
               nullable=False,
               comment='设备ID',
               existing_comment='设备ID（线路巡检时可为空）',
               schema='equipment')

    # 4. 删除新约束，添加旧约束（不恢复数据）
    op.execute(
        "ALTER TABLE equipment.inspection_tasks "
        "DROP CONSTRAINT IF EXISTS ck_inspection_tasks_plan_type"
    )
    op.execute(
        "ALTER TABLE equipment.inspection_tasks "
        "ADD CONSTRAINT ck_inspection_tasks_plan_type "
        "CHECK (plan_type IN ('日常巡检', '周巡检', '月巡检', '专项巡检'))"
    )
