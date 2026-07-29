"""add recruitment models: Candidate fields, JobRequirement fields, new tables

Revision ID: 4a36bb508376
Revises: 3128a2a1e622
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4a36bb508376'
down_revision: Union[str, None] = '3128a2a1e622'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")

    # ── candidates 表新增字段 ──
    op.add_column('candidates', sa.Column('candidate_type', sa.String(8), server_default='职能', nullable=False, comment='候选人类型'), schema='hr')
    op.add_column('candidates', sa.Column('offer_status', sa.String(16), nullable=True, comment='Offer状态'), schema='hr')
    op.add_column('candidates', sa.Column('offer_sent_at', sa.Date(), nullable=True, comment='Offer发送时间'), schema='hr')
    op.add_column('candidates', sa.Column('source', sa.String(32), nullable=True, comment='简历来源'), schema='hr')
    op.add_column('candidates', sa.Column('expected_salary', sa.String(32), nullable=True, comment='期望薪资'), schema='hr')
    op.add_column('candidates', sa.Column('current_company', sa.String(128), nullable=True, comment='当前公司'), schema='hr')
    op.add_column('candidates', sa.Column('work_years', sa.Integer(), nullable=True, comment='工作年限'), schema='hr')
    op.add_column('candidates', sa.Column('notes', sa.Text(), nullable=True, comment='备注'), schema='hr')
    op.create_index('ix_candidates_job_requirement_id', 'candidates', ['job_requirement_id'], unique=False, schema='hr')

    # ── job_requirements 表新增字段 ──
    op.add_column('job_requirements', sa.Column('urgency', sa.String(8), nullable=True, comment='紧急程度'), schema='hr')
    op.add_column('job_requirements', sa.Column('owner', sa.String(64), nullable=True, comment='招聘负责人'), schema='hr')
    op.add_column('job_requirements', sa.Column('deadline', sa.Date(), nullable=True, comment='期望到岗日期'), schema='hr')

    # ── candidate_status_logs 表 ──
    op.create_table('candidate_status_logs',
        sa.Column('candidate_id', sa.Uuid(), nullable=False, comment='候选人ID'),
        sa.Column('from_status', sa.String(16), nullable=True, comment='原状态'),
        sa.Column('to_status', sa.String(16), nullable=False, comment='新状态'),
        sa.Column('operator', sa.String(64), nullable=True, comment='操作人'),
        sa.Column('remark', sa.String(256), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='hr'
    )
    op.create_index('ix_csl_candidate_id', 'candidate_status_logs', ['candidate_id'], unique=False, schema='hr')

    # ── interviews 表 ──
    op.create_table('interviews',
        sa.Column('candidate_id', sa.Uuid(), nullable=False, comment='候选人ID'),
        sa.Column('job_requirement_id', sa.Uuid(), nullable=True, comment='关联岗位需求'),
        sa.Column('interview_type', sa.String(16), server_default='初试', nullable=False, comment='初试/复试/终试'),
        sa.Column('interview_date', sa.Date(), nullable=True, comment='面试日期'),
        sa.Column('interviewer', sa.String(64), nullable=True, comment='面试官'),
        sa.Column('location', sa.String(256), nullable=True, comment='面试地点'),
        sa.Column('status', sa.String(16), server_default='待安排', nullable=False, comment='待安排/已安排/已完成/已取消'),
        sa.Column('transcript_text', sa.Text(), nullable=True, comment='面试逐字稿'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='hr'
    )
    op.create_index('ix_interviews_candidate_id', 'interviews', ['candidate_id'], unique=False, schema='hr')
    op.create_index('ix_interviews_interview_date', 'interviews', ['interview_date'], unique=False, schema='hr')

    # ── candidate_ai_evaluations 表 ──
    op.create_table('candidate_ai_evaluations',
        sa.Column('candidate_id', sa.Uuid(), nullable=False, comment='候选人ID'),
        sa.Column('job_requirement_id', sa.Uuid(), nullable=True, comment='关联岗位需求'),
        sa.Column('interview_id', sa.Uuid(), nullable=True, comment='关联面试记录'),
        sa.Column('jd_match_score', sa.Float(), nullable=True, comment='JD匹配度'),
        sa.Column('professional_score', sa.Float(), nullable=True, comment='专业能力'),
        sa.Column('communication_score', sa.Float(), nullable=True, comment='沟通表达'),
        sa.Column('learning_score', sa.Float(), nullable=True, comment='学习能力'),
        sa.Column('stability_score', sa.Float(), nullable=True, comment='稳定性评估'),
        sa.Column('overall_score', sa.Float(), nullable=True, comment='综合评分'),
        sa.Column('strengths', sa.Text(), nullable=True, comment='优势'),
        sa.Column('weaknesses', sa.Text(), nullable=True, comment='不足'),
        sa.Column('ai_summary', sa.Text(), nullable=True, comment='AI综合评价'),
        sa.Column('risk_flags', sa.Text(), nullable=True, comment='风险提示'),
        sa.Column('jd_text_snapshot', sa.Text(), nullable=True, comment='评估时JD快照'),
        sa.Column('transcript_snapshot', sa.Text(), nullable=True, comment='评估时逐字稿快照'),
        sa.Column('model_version', sa.String(32), nullable=True, comment='AI模型版本'),
        sa.Column('evaluated_at', sa.DateTime(), nullable=True, comment='评估时间'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='hr'
    )
    op.create_index('ix_cae_candidate_id', 'candidate_ai_evaluations', ['candidate_id'], unique=False, schema='hr')
    op.create_index('ix_cae_interview_id', 'candidate_ai_evaluations', ['interview_id'], unique=False, schema='hr')


def downgrade() -> None:
    # ── candidate_ai_evaluations ──
    op.drop_index('ix_cae_interview_id', table_name='candidate_ai_evaluations', schema='hr')
    op.drop_index('ix_cae_candidate_id', table_name='candidate_ai_evaluations', schema='hr')
    op.drop_table('candidate_ai_evaluations', schema='hr')

    # ── interviews ──
    op.drop_index('ix_interviews_interview_date', table_name='interviews', schema='hr')
    op.drop_index('ix_interviews_candidate_id', table_name='interviews', schema='hr')
    op.drop_table('interviews', schema='hr')

    # ── candidate_status_logs ──
    op.drop_index('ix_csl_candidate_id', table_name='candidate_status_logs', schema='hr')
    op.drop_table('candidate_status_logs', schema='hr')

    # ── job_requirements 回退 ──
    op.drop_column('job_requirements', 'deadline', schema='hr')
    op.drop_column('job_requirements', 'owner', schema='hr')
    op.drop_column('job_requirements', 'urgency', schema='hr')

    # ── candidates 回退 ──
    op.drop_index('ix_candidates_job_requirement_id', table_name='candidates', schema='hr')
    op.drop_column('candidates', 'notes', schema='hr')
    op.drop_column('candidates', 'work_years', schema='hr')
    op.drop_column('candidates', 'current_company', schema='hr')
    op.drop_column('candidates', 'expected_salary', schema='hr')
    op.drop_column('candidates', 'source', schema='hr')
    op.drop_column('candidates', 'offer_sent_at', schema='hr')
    op.drop_column('candidates', 'offer_status', schema='hr')
    op.drop_column('candidates', 'candidate_type', schema='hr')
