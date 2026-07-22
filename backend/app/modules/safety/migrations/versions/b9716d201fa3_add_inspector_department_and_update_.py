"""add_inspector_department_and_update_hazard_columns

Revision ID: b9716d201fa3
Revises: 97bd41dc097a
Create Date: 2026-06-18 09:10:22.305286
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b9716d201fa3'
down_revision: Union[str, None] = '97bd41dc097a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加 inspector_department 列，同步 hazard_reports 列类型和注释与 Bitable 一致。"""
    # ── 新增列 ──
    op.add_column(
        'hazard_reports',
        sa.Column(
            'inspector_department',
            sa.String(length=500),
            nullable=True,
            comment='检查人员部门（Bitable 多选，逗号分隔，如「EHS部, 生产部」）',
        ),
        schema='safety',
    )

    # ── 修改列类型 ──
    op.alter_column(
        'hazard_reports', 'inspection_category',
        existing_type=sa.VARCHAR(length=64),
        type_=sa.String(length=128),
        comment='检查类别（Bitable 多选，逗号分隔，如「月度安全检查, 周检」）',
        existing_comment='检查类别（日常检查/专项检查…）',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'key_defect',
        existing_type=sa.VARCHAR(length=100),
        type_=sa.Text(),
        comment='隐患描述（AI）',
        existing_comment='重点缺陷',
        existing_nullable=True,
        schema='safety',
    )

    # ── 列注释同步（无类型变更，仅注释）──
    op.alter_column(
        'hazard_reports', 'hazard_type',
        existing_type=sa.VARCHAR(length=32),
        comment='隐患分类（AI）：人的不安全行为/物的不安全状态/环境的不安全因素/管理的缺陷',
        existing_comment='隐患分类（人/物/环/管）',
        existing_nullable=False,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'hazard_level',
        existing_type=sa.VARCHAR(length=16),
        comment='隐患等级（AI）：一般隐患/较大隐患/重大隐患',
        existing_comment='隐患等级（一般/较大/重大）',
        existing_nullable=False,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'hazard_category',
        existing_type=sa.VARCHAR(length=32),
        comment='隐患类别（AI）：设备设施/危化储存/仪表+电气/…（13种）',
        existing_comment='隐患类别（设备设施/危化储存…）',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'discovered_by_name',
        existing_type=sa.VARCHAR(length=100),
        comment='检查人员姓名',
        existing_comment='发现人姓名',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'discovered_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='检查日期',
        existing_comment='发现时间',
        existing_nullable=False,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'major_hazard_basis',
        existing_type=sa.TEXT(),
        comment='隐患判定依据（AI）',
        existing_comment='重大隐患判定依据',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'deadline',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='整改期限',
        existing_comment='计划完成时间',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'actual_completion_date',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='整改完成时间',
        existing_comment='实际完成时间',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'extended_deadline',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='延期完成日期（Bitable 已删除此字段，保留兼容）',
        existing_comment='延期完成日期',
        existing_nullable=True,
        schema='safety',
    )
    # ── 三级复核列注释同步 ──
    op.alter_column(
        'hazard_reports', 'verify_level_1_status',
        existing_type=sa.VARCHAR(length=20),
        comment='部门负责人复核状态 (Bitable「部门负责人复核」): pending/approved/rejected',
        existing_comment='一级复核状态: pending/approved/rejected',
        existing_nullable=False,
        existing_server_default=sa.text("'pending'::character varying"),
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_1_by',
        existing_type=sa.UUID(),
        comment='部门负责人复核人ID',
        existing_comment='一级复核人ID',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_1_by_name',
        existing_type=sa.VARCHAR(length=100),
        comment='部门负责人复核人姓名',
        existing_comment='一级复核人姓名',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_1_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='部门负责人复核时间',
        existing_comment='一级复核时间',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_1_opinion',
        existing_type=sa.TEXT(),
        comment='部门负责人复核意见',
        existing_comment='一级复核意见',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_2_status',
        existing_type=sa.VARCHAR(length=20),
        comment='分管领导复核状态 (Bitable「分管领导复核」): pending/approved/rejected',
        existing_comment='二级复核状态: pending/approved/rejected',
        existing_nullable=False,
        existing_server_default=sa.text("'pending'::character varying"),
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_2_by',
        existing_type=sa.UUID(),
        comment='分管领导复核人ID',
        existing_comment='二级复核人ID',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_2_by_name',
        existing_type=sa.VARCHAR(length=100),
        comment='分管领导复核人姓名',
        existing_comment='二级复核人姓名',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_2_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='分管领导复核时间',
        existing_comment='二级复核时间',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_2_opinion',
        existing_type=sa.TEXT(),
        comment='分管领导复核意见',
        existing_comment='二级复核意见',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_3_status',
        existing_type=sa.VARCHAR(length=20),
        comment='检查人员复核状态 (Bitable「检查人员复核」): pending/approved/rejected',
        existing_comment='三级复核状态: pending/approved/rejected',
        existing_nullable=False,
        existing_server_default=sa.text("'pending'::character varying"),
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_3_by',
        existing_type=sa.UUID(),
        comment='检查人员复核人ID',
        existing_comment='三级复核人ID',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_3_by_name',
        existing_type=sa.VARCHAR(length=100),
        comment='检查人员复核人姓名',
        existing_comment='三级复核人姓名',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_3_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='检查人员复核时间',
        existing_comment='三级复核时间',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_3_opinion',
        existing_type=sa.TEXT(),
        comment='检查人员复核意见',
        existing_comment='三级复核意见',
        existing_nullable=True,
        schema='safety',
    )


def downgrade() -> None:
    """回退 hazard_reports 变更。"""
    # ── 三级复核注释回退 ──
    op.alter_column(
        'hazard_reports', 'verify_level_3_opinion',
        existing_type=sa.TEXT(),
        comment='三级复核意见',
        existing_comment='检查人员复核意见',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_3_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='三级复核时间',
        existing_comment='检查人员复核时间',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_3_by_name',
        existing_type=sa.VARCHAR(length=100),
        comment='三级复核人姓名',
        existing_comment='检查人员复核人姓名',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_3_by',
        existing_type=sa.UUID(),
        comment='三级复核人ID',
        existing_comment='检查人员复核人ID',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_3_status',
        existing_type=sa.VARCHAR(length=20),
        comment='三级复核状态: pending/approved/rejected',
        existing_comment='检查人员复核状态 (Bitable「检查人员复核」): pending/approved/rejected',
        existing_nullable=False,
        existing_server_default=sa.text("'pending'::character varying"),
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_2_opinion',
        existing_type=sa.TEXT(),
        comment='二级复核意见',
        existing_comment='分管领导复核意见',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_2_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='二级复核时间',
        existing_comment='分管领导复核时间',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_2_by_name',
        existing_type=sa.VARCHAR(length=100),
        comment='二级复核人姓名',
        existing_comment='分管领导复核人姓名',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_2_by',
        existing_type=sa.UUID(),
        comment='二级复核人ID',
        existing_comment='分管领导复核人ID',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_2_status',
        existing_type=sa.VARCHAR(length=20),
        comment='二级复核状态: pending/approved/rejected',
        existing_comment='分管领导复核状态 (Bitable「分管领导复核」): pending/approved/rejected',
        existing_nullable=False,
        existing_server_default=sa.text("'pending'::character varying"),
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_1_opinion',
        existing_type=sa.TEXT(),
        comment='一级复核意见',
        existing_comment='部门负责人复核意见',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_1_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='一级复核时间',
        existing_comment='部门负责人复核时间',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_1_by_name',
        existing_type=sa.VARCHAR(length=100),
        comment='一级复核人姓名',
        existing_comment='部门负责人复核人姓名',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_1_by',
        existing_type=sa.UUID(),
        comment='一级复核人ID',
        existing_comment='部门负责人复核人ID',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'verify_level_1_status',
        existing_type=sa.VARCHAR(length=20),
        comment='一级复核状态: pending/approved/rejected',
        existing_comment='部门负责人复核状态 (Bitable「部门负责人复核」): pending/approved/rejected',
        existing_nullable=False,
        existing_server_default=sa.text("'pending'::character varying"),
        schema='safety',
    )
    # ── 其他注释回退 ──
    op.alter_column(
        'hazard_reports', 'extended_deadline',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='延期完成日期',
        existing_comment='延期完成日期（Bitable 已删除此字段，保留兼容）',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'actual_completion_date',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='实际完成时间',
        existing_comment='整改完成时间',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'deadline',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='计划完成时间',
        existing_comment='整改期限',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'major_hazard_basis',
        existing_type=sa.TEXT(),
        comment='重大隐患判定依据',
        existing_comment='隐患判定依据（AI）',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'discovered_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment='发现时间',
        existing_comment='检查日期',
        existing_nullable=False,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'discovered_by_name',
        existing_type=sa.VARCHAR(length=100),
        comment='发现人姓名',
        existing_comment='检查人员姓名',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'hazard_category',
        existing_type=sa.VARCHAR(length=32),
        comment='隐患类别（设备设施/危化储存…）',
        existing_comment='隐患类别（AI）：设备设施/危化储存/仪表+电气/…（13种）',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'hazard_level',
        existing_type=sa.VARCHAR(length=16),
        comment='隐患等级（一般/较大/重大）',
        existing_comment='隐患等级（AI）：一般隐患/较大隐患/重大隐患',
        existing_nullable=False,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'hazard_type',
        existing_type=sa.VARCHAR(length=32),
        comment='隐患分类（人/物/环/管）',
        existing_comment='隐患分类（AI）：人的不安全行为/物的不安全状态/环境的不安全因素/管理的缺陷',
        existing_nullable=False,
        schema='safety',
    )
    # ── 列类型/注释回退 ──
    op.alter_column(
        'hazard_reports', 'key_defect',
        existing_type=sa.Text(),
        type_=sa.VARCHAR(length=100),
        comment='重点缺陷',
        existing_comment='隐患描述（AI）',
        existing_nullable=True,
        schema='safety',
    )
    op.alter_column(
        'hazard_reports', 'inspection_category',
        existing_type=sa.String(length=128),
        type_=sa.VARCHAR(length=64),
        comment='检查类别（日常检查/专项检查…）',
        existing_comment='检查类别（Bitable 多选，逗号分隔，如「月度安全检查, 周检」）',
        existing_nullable=True,
        schema='safety',
    )
    op.drop_column('hazard_reports', 'inspector_department', schema='safety')
