"""add emergency drill tables

Revision ID: e1b2375757dd
Revises: a86dfab27598
Create Date: 2026-07-16 08:35:17.346989
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'e1b2375757dd'
down_revision: Union[str, None] = 'a86dfab27598'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    # ── emergency_drill_plans ──
    op.create_table(
        'emergency_drill_plans',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='飞书 Bitable 记录 ID（同步主键）'),
        sa.Column('plan_no', sa.String(length=32), nullable=True, comment='计划编号（YL-YYYY-NNNN）'),
        sa.Column('title', sa.String(length=256), nullable=False, comment='演练标题'),
        sa.Column('drill_type', sa.String(length=32), nullable=True, comment='演练类型: tabletop/functional/full_scale/comprehensive'),
        sa.Column('drill_format', sa.String(length=32), nullable=True, comment='演练形式: 桌面演练/实战演练/问答研讨'),
        sa.Column('drill_purpose', sa.String(length=32), nullable=True, comment='演练目的: 检验性/示范性/研究性'),
        sa.Column('scenario_category', sa.String(length=64), nullable=True, comment='场景类别'),
        sa.Column('scenario_description', sa.Text(), nullable=True, comment='情景描述'),
        sa.Column('department', sa.String(length=128), nullable=True, comment='组织部门'),
        sa.Column('location', sa.String(length=256), nullable=True, comment='演练地点'),
        sa.Column('scheduled_at', sa.Date(), nullable=True, comment='计划日期'),
        sa.Column('start_time', sa.Time(), nullable=True, comment='开始时间'),
        sa.Column('end_time', sa.Time(), nullable=True, comment='结束时间'),
        sa.Column('participants_count', sa.Integer(), nullable=True, comment='计划参与人数'),
        sa.Column('commander', sa.String(length=64), nullable=True, comment='总指挥'),
        sa.Column('status', sa.String(length=32), server_default='draft', nullable=False, comment='状态: draft/scheduled/in_progress/completed/archived'),
        sa.Column('requirements', sa.Text(), nullable=True, comment='演练需求/目标'),
        sa.Column('preparation_notes', sa.Text(), nullable=True, comment='准备工作备注'),
        sa.Column('created_by_name', sa.String(length=64), nullable=True, comment='创建人姓名'),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
    )
    op.create_index('idx_drill_plans_feishu_record', 'emergency_drill_plans', ['feishu_record_id'], unique=False, schema='safety')
    op.create_index('idx_drill_plans_status', 'emergency_drill_plans', ['status'], unique=False, schema='safety')
    op.create_index('idx_drill_plans_department', 'emergency_drill_plans', ['department'], unique=False, schema='safety')
    op.create_index('idx_drill_plans_scheduled_at', 'emergency_drill_plans', ['scheduled_at'], unique=False, schema='safety')
    op.create_index('idx_drill_plans_scenario', 'emergency_drill_plans', ['scenario_category'], unique=False, schema='safety')

    # ── emergency_drill_records ──
    op.create_table(
        'emergency_drill_records',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='飞书 Bitable 记录 ID（同步主键）'),
        sa.Column('plan_id', sa.Uuid(), nullable=True, comment='关联演练计划 ID'),
        sa.Column('plan_no', sa.String(length=32), nullable=True, comment='关联计划编号'),
        sa.Column('record_no', sa.String(length=32), nullable=True, comment='记录编号（YL-JL-YYYY-NNNN）'),
        sa.Column('title', sa.String(length=256), nullable=False, comment='记录标题'),
        sa.Column('drill_type', sa.String(length=32), nullable=True, comment='演练类型'),
        sa.Column('scenario_category', sa.String(length=64), nullable=True, comment='场景类别'),
        sa.Column('department', sa.String(length=128), nullable=True, comment='组织部门'),
        sa.Column('location', sa.String(length=256), nullable=True, comment='演练地点'),
        sa.Column('executed_at', sa.Date(), nullable=True, comment='实际执行日期'),
        sa.Column('start_time', sa.Time(), nullable=True, comment='实际开始时间'),
        sa.Column('end_time', sa.Time(), nullable=True, comment='实际结束时间'),
        sa.Column('participants_count', sa.Integer(), nullable=True, comment='实际参与人数'),
        sa.Column('participants_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='参与人员明细'),
        sa.Column('commander', sa.String(length=64), nullable=True, comment='总指挥'),
        sa.Column('process_description', sa.Text(), nullable=True, comment='演练过程描述'),
        sa.Column('issues_found', sa.Text(), nullable=True, comment='发现的问题'),
        sa.Column('corrective_actions', sa.Text(), nullable=True, comment='整改措施'),
        sa.Column('plan_suitability', sa.String(length=32), nullable=True, comment='预案适用性'),
        sa.Column('plan_adequacy', sa.String(length=32), nullable=True, comment='预案充分性'),
        sa.Column('assessment_score', sa.Integer(), nullable=True, comment='评估分数（0-100）'),
        sa.Column('assessment_grade', sa.String(length=16), nullable=True, comment='评估等级: excellent/good/average/fail'),
        sa.Column('supplies_status', sa.Text(), nullable=True, comment='物资准备情况'),
        sa.Column('coordination_evaluation', sa.Text(), nullable=True, comment='协同评估'),
        sa.Column('effectiveness_summary', sa.Text(), nullable=True, comment='效果总结'),
        sa.Column('photos', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='现场照片（文件路径数组）'),
        sa.Column('attachments', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='附件（文件路径数组）'),
        sa.Column('recorded_by', sa.String(length=64), nullable=True, comment='记录人'),
        sa.Column('status', sa.String(length=32), server_default='draft', nullable=False, comment='状态: draft/completed/archived'),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
    )
    op.create_index('idx_drill_records_feishu_record', 'emergency_drill_records', ['feishu_record_id'], unique=False, schema='safety')
    op.create_index('idx_drill_records_plan_id', 'emergency_drill_records', ['plan_id'], unique=False, schema='safety')
    op.create_index('idx_drill_records_status', 'emergency_drill_records', ['status'], unique=False, schema='safety')
    op.create_index('idx_drill_records_department', 'emergency_drill_records', ['department'], unique=False, schema='safety')
    op.create_index('idx_drill_records_executed_at', 'emergency_drill_records', ['executed_at'], unique=False, schema='safety')
    op.create_index('idx_drill_records_scenario', 'emergency_drill_records', ['scenario_category'], unique=False, schema='safety')

    # ── emergency_drill_documents ──
    op.create_table(
        'emergency_drill_documents',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('resource_type', sa.String(length=32), nullable=False, comment='关联类型: plan/record'),
        sa.Column('resource_id', sa.Uuid(), nullable=False, comment='关联资源 ID'),
        sa.Column('doc_type', sa.String(length=32), nullable=False, comment='文档类型: drill_plan/drill_report'),
        sa.Column('title', sa.String(length=256), nullable=False, comment='文档标题'),
        sa.Column('content', sa.Text(), nullable=True, comment='文档正文（Markdown）'),
        sa.Column('content_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='结构化内容'),
        sa.Column('generation_params', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='AI 生成参数快照'),
        sa.Column('cited_regulations', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='引用的法规列表'),
        sa.Column('ai_model', sa.String(length=64), nullable=True, comment='使用的 AI 模型'),
        sa.Column('ai_tokens_used', sa.Integer(), nullable=True, comment='Token 消耗'),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False, comment='版本号'),
        sa.Column('status', sa.String(length=16), server_default='draft', nullable=False, comment='状态: draft/published'),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
    )
    op.create_index('idx_drill_docs_resource', 'emergency_drill_documents', ['resource_type', 'resource_id'], unique=False, schema='safety')
    op.create_index('idx_drill_docs_type', 'emergency_drill_documents', ['doc_type'], unique=False, schema='safety')


def downgrade() -> None:
    op.drop_index('idx_drill_docs_type', table_name='emergency_drill_documents', schema='safety')
    op.drop_index('idx_drill_docs_resource', table_name='emergency_drill_documents', schema='safety')
    op.drop_table('emergency_drill_documents', schema='safety')

    op.drop_index('idx_drill_records_scenario', table_name='emergency_drill_records', schema='safety')
    op.drop_index('idx_drill_records_executed_at', table_name='emergency_drill_records', schema='safety')
    op.drop_index('idx_drill_records_department', table_name='emergency_drill_records', schema='safety')
    op.drop_index('idx_drill_records_status', table_name='emergency_drill_records', schema='safety')
    op.drop_index('idx_drill_records_plan_id', table_name='emergency_drill_records', schema='safety')
    op.drop_index('idx_drill_records_feishu_record', table_name='emergency_drill_records', schema='safety')
    op.drop_table('emergency_drill_records', schema='safety')

    op.drop_index('idx_drill_plans_scenario', table_name='emergency_drill_plans', schema='safety')
    op.drop_index('idx_drill_plans_scheduled_at', table_name='emergency_drill_plans', schema='safety')
    op.drop_index('idx_drill_plans_department', table_name='emergency_drill_plans', schema='safety')
    op.drop_index('idx_drill_plans_status', table_name='emergency_drill_plans', schema='safety')
    op.drop_index('idx_drill_plans_feishu_record', table_name='emergency_drill_plans', schema='safety')
    op.drop_table('emergency_drill_plans', schema='safety')
