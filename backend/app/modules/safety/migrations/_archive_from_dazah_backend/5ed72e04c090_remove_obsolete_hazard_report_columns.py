"""remove obsolete hazard_report columns

Revision ID: 5ed72e04c090
Revises: b9716d201fa3
Create Date: 2026-06-18 15:35:45.155501
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5ed72e04c090'
down_revision: Union[str, None] = 'b9716d201fa3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除 HazardReport 中 Bitable 不存在的多余字段（6 列）+ 1 个 FK 约束"""

    # 1. 先删除外键约束
    op.drop_constraint(
        op.f('hazard_reports_verified_by_fkey'),
        'hazard_reports',
        schema='safety',
        type_='foreignkey',
    )

    # 2. 删除多余的业务列（Bitable 不存在对应列）
    op.drop_column('hazard_reports', 'control_measures', schema='safety')
    op.drop_column('hazard_reports', 'rectification_responsible_department', schema='safety')
    op.drop_column('hazard_reports', 'extended_deadline', schema='safety')
    op.drop_column('hazard_reports', 'verified_at', schema='safety')
    op.drop_column('hazard_reports', 'verified_by_name', schema='safety')
    op.drop_column('hazard_reports', 'verified_by', schema='safety')

    # 3. 更新字段注释（反映 Bitable 字段名）
    op.alter_column(
        'hazard_reports',
        'rectification_responsible_person_name',
        existing_type=sa.VARCHAR(length=100),
        comment='整改责任人姓名（Bitable「责任人」）',
        existing_comment='整改责任人姓名',
        existing_nullable=True,
        schema='safety',
    )


def downgrade() -> None:
    """回滚：恢复被删除的 6 列 + FK 约束"""

    # 1. 恢复列
    op.add_column(
        'hazard_reports',
        sa.Column(
            'verified_by',
            sa.UUID(),
            autoincrement=False,
            nullable=True,
            comment='验证人',
        ),
        schema='safety',
    )
    op.add_column(
        'hazard_reports',
        sa.Column(
            'verified_by_name',
            sa.VARCHAR(length=100),
            autoincrement=False,
            nullable=True,
            comment='验证人姓名',
        ),
        schema='safety',
    )
    op.add_column(
        'hazard_reports',
        sa.Column(
            'verified_at',
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
            comment='验证时间',
        ),
        schema='safety',
    )
    op.add_column(
        'hazard_reports',
        sa.Column(
            'extended_deadline',
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
            comment='延期完成日期（Bitable 已删除此字段，保留兼容）',
        ),
        schema='safety',
    )
    op.add_column(
        'hazard_reports',
        sa.Column(
            'rectification_responsible_department',
            sa.VARCHAR(length=100),
            autoincrement=False,
            nullable=True,
            comment='整改责任人部门',
        ),
        schema='safety',
    )
    op.add_column(
        'hazard_reports',
        sa.Column(
            'control_measures',
            sa.TEXT(),
            autoincrement=False,
            nullable=True,
            comment='管控措施',
        ),
        schema='safety',
    )

    # 2. 恢复外键约束
    op.create_foreign_key(
        op.f('hazard_reports_verified_by_fkey'),
        'hazard_reports',
        'users',
        ['verified_by'],
        ['id'],
        source_schema='safety',
        referent_schema='identity',
    )

    # 3. 回滚注释
    op.alter_column(
        'hazard_reports',
        'rectification_responsible_person_name',
        existing_type=sa.VARCHAR(length=100),
        comment='整改责任人姓名',
        existing_comment='整改责任人姓名（Bitable「责任人」）',
        existing_nullable=True,
        schema='safety',
    )
