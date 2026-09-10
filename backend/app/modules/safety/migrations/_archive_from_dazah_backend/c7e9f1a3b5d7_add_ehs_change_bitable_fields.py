"""add ehs_change bitable fields (source/feishu_record_id/ai_review etc)

Revision ID: c7e9f1a3b5d7
Revises: 8750117df552
Create Date: 2026-08-03
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7e9f1a3b5d7'
down_revision: str | None = '8750117df552'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'ehs_changes',
        sa.Column('source', sa.String(length=16), nullable=False, server_default='manual',
                  comment='数据来源: manual(手动)/bitable(飞书同步)'),
        schema='safety',
    )
    op.add_column(
        'ehs_changes',
        sa.Column('feishu_record_id', sa.String(length=64), nullable=True,
                  comment='飞书 Bitable 记录 ID（同步主键）'),
        schema='safety',
    )
    op.add_column(
        'ehs_changes',
        sa.Column('feishu_table_id', sa.String(length=32), nullable=True,
                  comment='飞书表类型: approval(变更审批)/acceptance(变更验收)'),
        schema='safety',
    )
    op.add_column(
        'ehs_changes',
        sa.Column('bt_change_no', sa.String(length=64), nullable=True,
                  comment='Bitable 变更申请编号/变更编号（展示用）'),
        schema='safety',
    )
    op.add_column(
        'ehs_changes',
        sa.Column('bt_change_status', sa.String(length=64), nullable=True,
                  comment='Bitable 变更状态（待安装/问题整改中等，审批表专用）'),
        schema='safety',
    )
    op.add_column(
        'ehs_changes',
        sa.Column('bt_plan_content', sa.Text(), nullable=True,
                  comment='Bitable 变更计划内容（审批表专用）'),
        schema='safety',
    )
    op.add_column(
        'ehs_changes',
        sa.Column('bt_risk_measures', sa.Text(), nullable=True,
                  comment='Bitable 变更风险评估及建议措施（审批表专用）'),
        schema='safety',
    )
    op.add_column(
        'ehs_changes',
        sa.Column('bt_acceptance_comment', sa.Text(), nullable=True,
                  comment='Bitable 验收意见（验收表专用，可另附验收报告）'),
        schema='safety',
    )
    op.add_column(
        'ehs_changes',
        sa.Column('bt_extra', sa.JSON(), nullable=True,
                  comment='Bitable 其他字段 JSONB（can_reflect/gmp_change_no/current_handler/approval_node/source_id/related_approval/approval_flow/acceptance_date）'),
        schema='safety',
    )
    op.add_column(
        'ehs_changes',
        sa.Column('ai_review_status', sa.String(length=32), nullable=False, server_default='none',
                  comment='AI审核状态: none/completed（审批表专用）'),
        schema='safety',
    )
    op.add_column(
        'ehs_changes',
        sa.Column('ai_review_result', sa.JSON(), nullable=True,
                  comment='AI审核结果 JSONB（审批表四维度）{reason:{conclusion,report}, plan:{...}, effect:{...}, risk:{...}, pre_review:...}'),
        schema='safety',
    )
    # 部分唯一索引：软删除/空值不参与唯一约束
    op.create_index(
        'uq_ehs_changes_feishu_record_id',
        'ehs_changes',
        ['feishu_record_id'],
        unique=True,
        postgresql_where=sa.text("is_deleted = false AND feishu_record_id IS NOT NULL"),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_index('uq_ehs_changes_feishu_record_id', table_name='ehs_changes', schema='safety')
    op.drop_column('ehs_changes', 'ai_review_result', schema='safety')
    op.drop_column('ehs_changes', 'ai_review_status', schema='safety')
    op.drop_column('ehs_changes', 'bt_extra', schema='safety')
    op.drop_column('ehs_changes', 'bt_acceptance_comment', schema='safety')
    op.drop_column('ehs_changes', 'bt_risk_measures', schema='safety')
    op.drop_column('ehs_changes', 'bt_plan_content', schema='safety')
    op.drop_column('ehs_changes', 'bt_change_status', schema='safety')
    op.drop_column('ehs_changes', 'bt_change_no', schema='safety')
    op.drop_column('ehs_changes', 'feishu_table_id', schema='safety')
    op.drop_column('ehs_changes', 'feishu_record_id', schema='safety')
    op.drop_column('ehs_changes', 'source', schema='safety')
