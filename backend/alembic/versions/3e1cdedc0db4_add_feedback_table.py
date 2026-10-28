"""新增系统反馈表 feedback.feedbacks

顶栏新增「反馈」入口：全员可提交反馈（bug/优化体验/新增功能）并回看自己的反馈，
持 system:feedback:manage（超管默认拥有）可查看全部反馈并切换「已处理」开关。
autogenerate 产物中夹带的其他模块漂移（quality/hr/equipment 的注释与外键等）
已按惯例剔除，仅保留本表 DDL。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3e1cdedc0db4'
down_revision: str | None = '7bdb531a07b1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # autogenerate 不生成建 schema 语句，空库部署依赖此处显式创建
    op.execute("CREATE SCHEMA IF NOT EXISTS feedback")
    op.create_table('feedbacks',
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('page_path', sa.String(length=512), nullable=True),
    sa.Column('submitter_name', sa.String(length=100), nullable=False),
    sa.Column('submitter_department', sa.String(length=200), nullable=True),
    sa.Column('is_handled', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('handled_by', sa.Uuid(), nullable=True),
    sa.Column('handled_by_name', sa.String(length=100), nullable=True),
    sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("type IN ('bug', 'ux', 'feature')", name='ck_feedback_feedbacks_type'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='feedback'
    )
    op.create_index('ix_feedback_feedbacks_created_at', 'feedbacks', ['created_at'], unique=False, schema='feedback')
    op.create_index('ix_feedback_feedbacks_created_by', 'feedbacks', ['created_by'], unique=False, schema='feedback')
    op.create_index('ix_feedback_feedbacks_handled_created', 'feedbacks', ['is_handled', 'created_at'], unique=False, schema='feedback')


def downgrade() -> None:
    op.drop_index('ix_feedback_feedbacks_handled_created', table_name='feedbacks', schema='feedback')
    op.drop_index('ix_feedback_feedbacks_created_by', table_name='feedbacks', schema='feedback')
    op.drop_index('ix_feedback_feedbacks_created_at', table_name='feedbacks', schema='feedback')
    op.drop_table('feedbacks', schema='feedback')
    op.execute("DROP SCHEMA IF EXISTS feedback")
