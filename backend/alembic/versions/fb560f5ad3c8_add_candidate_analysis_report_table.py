"""add candidate analysis report table

Revision ID: fb560f5ad3c8
Revises: f581cbc54678
Create Date: 2026-08-21 10:00:00.000000

招聘：候选人胜任度多维分析报告表。仅 hr 表，其他模块无关变更已清理。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fb560f5ad3c8'
down_revision: Union[str, None] = 'f581cbc54678'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table('candidate_analysis_reports',
    sa.Column('candidate_id', sa.Uuid(), nullable=False, comment='候选人ID'),
    sa.Column('job_requirement_id', sa.Uuid(), nullable=True, comment='关联岗位需求'),
    sa.Column('interview_id', sa.Uuid(), nullable=False, comment='关联面试记录'),
    sa.Column('dimensions', sa.JSON(), nullable=True, comment='维度评估 [{name, score, star, assessment}]'),
    sa.Column('strengths', sa.JSON(), nullable=True, comment='核心优势 [str]'),
    sa.Column('risks', sa.JSON(), nullable=True, comment='潜在风险 [str]'),
    sa.Column('total_score', sa.Float(), nullable=True, comment='综合胜任度评分（0-100）'),
    sa.Column('recommend_level', sa.String(length=16), nullable=True, comment='推荐等级：强烈推荐/推荐/待定/不推荐'),
    sa.Column('interview_suggestions', sa.JSON(), nullable=True, comment='面试建议 [str]（联动写入面试备注）'),
    sa.Column('training_suggestions', sa.JSON(), nullable=True, comment='录用后培养建议 [str]'),
    sa.Column('raw_text', sa.Text(), nullable=True, comment='AI 原始输出'),
    sa.Column('model_version', sa.String(length=32), nullable=True, comment='模型版本'),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True, comment='生成时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_car_candidate', 'candidate_analysis_reports', ['candidate_id'], unique=False, schema='hr')
    op.create_index('uq_car_interview', 'candidate_analysis_reports', ['interview_id'], unique=True, schema='hr', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_car_interview', table_name='candidate_analysis_reports', schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_car_candidate', table_name='candidate_analysis_reports', schema='hr')
    op.drop_table('candidate_analysis_reports', schema='hr')
