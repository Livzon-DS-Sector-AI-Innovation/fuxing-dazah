"""quality add test tasks and results

Revision ID: 5f25b7332b4b
Revises: 84b8d969d5e1
Create Date: 2026-09-03 13:40:08.875544

手工清理说明：autogenerate 混入了其他模块（safety/hr/equipment 等）的无关 DDL 与
外键约束，已全部移除，仅保留 quality 模块两张新表。本项目约定不建外键约束。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5f25b7332b4b'
down_revision: Union[str, None] = '84b8d969d5e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")

    op.create_table(
        'quality_test_tasks',
        sa.Column('product_name', sa.String(length=200), nullable=False, comment='产品名称'),
        sa.Column('batch_number', sa.String(length=100), nullable=False, comment='批号'),
        sa.Column('test_date', sa.String(length=32), nullable=True, comment='检验日期（YYYY-MM-DD）'),
        sa.Column('form_id', sa.String(length=100), nullable=True, comment='COA 表格编号，如 EX-HA-5246-001'),
        sa.Column('standard_document_id', sa.Uuid(), nullable=True,
                  comment='快照来源标准文档，逻辑引用 quality.quality_standard_documents.id（多文档时为主文档）'),
        sa.Column('status', sa.String(length=20), server_default='in_progress', nullable=False,
                  comment='任务状态：in_progress 填报中 / completed 已完成 / void 已作废'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='quality',
    )
    op.create_index('uq_quality_test_task_product_batch', 'quality_test_tasks',
                    ['product_name', 'batch_number'], unique=True, schema='quality',
                    postgresql_where=sa.text('is_deleted = false'))
    op.create_index('ix_quality_test_task_product', 'quality_test_tasks', ['product_name'],
                    unique=False, schema='quality')
    op.create_index('ix_quality_test_task_status', 'quality_test_tasks', ['status'],
                    unique=False, schema='quality')

    op.create_table(
        'quality_test_results',
        sa.Column('task_id', sa.Uuid(), nullable=False,
                  comment='关联检验任务，逻辑引用 quality.quality_test_tasks.id'),
        sa.Column('standard_item_id', sa.Uuid(), nullable=True,
                  comment='快照来源标准行，逻辑引用 quality.quality_standard_items.id（临时新增行为空）'),
        sa.Column('seq', sa.Integer(), nullable=True, comment='标准库序号快照（排序用）'),
        sa.Column('category', sa.String(length=100), nullable=True, comment='检验项目大类快照'),
        sa.Column('item_name', sa.String(length=200), nullable=False, comment='项目名称快照'),
        sa.Column('sop_no', sa.String(length=64), nullable=True, comment='SOP 号快照（P1 解析映射键之一）'),
        sa.Column('standard_text', sa.String(length=300), nullable=True, comment='合格标准原文快照（文字标准为纯文字）'),
        sa.Column('operator', sa.String(length=10), nullable=True, comment='比较运算符快照：≤ ≥ < > 范围'),
        sa.Column('limit_min', sa.Float(), nullable=True, comment='限度下限快照'),
        sa.Column('limit_max', sa.Float(), nullable=True, comment='限度上限快照'),
        sa.Column('method_source', sa.String(length=64), nullable=True, comment='方法来源快照'),
        sa.Column('remark', sa.String(length=200), nullable=True, comment='备注快照，如 加*每年仅1批'),
        sa.Column('result_text', sa.String(length=300), nullable=True, comment='填报结果原文（文字型判定用）'),
        sa.Column('result_value', sa.Float(), nullable=True, comment='填报数值（数值型判定用）'),
        sa.Column('is_pass', sa.Boolean(), nullable=True, comment='合格判定（未填报为 NULL）'),
        sa.Column('judge_mode', sa.String(length=10), server_default='auto', nullable=False,
                  comment='判定方式：auto 数值自动判定 / manual 人工判定'),
        sa.Column('source', sa.String(length=10), server_default='manual', nullable=False,
                  comment='数据来源：manual 手工填报 / parse 液相解析映射'),
        sa.Column('inspection_record_id', sa.Uuid(), nullable=True,
                  comment='关联液相解析记录，逻辑引用 quality.inspection_records.id（P1 预留）'),
        sa.Column('filled_by', sa.Uuid(), nullable=True,
                  comment='最近填报人，逻辑引用 identity.users.id（P0 不注入）'),
        sa.Column('filled_at', sa.DateTime(timezone=True), nullable=True, comment='最近填报时间'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='quality',
    )
    op.create_index('uq_quality_test_result_task_sop', 'quality_test_results',
                    ['task_id', 'sop_no'], unique=True, schema='quality',
                    postgresql_where=sa.text('is_deleted = false'))
    op.create_index('ix_quality_test_result_task', 'quality_test_results', ['task_id'],
                    unique=False, schema='quality')
    op.create_index('ix_quality_test_result_standard_item', 'quality_test_results', ['standard_item_id'],
                    unique=False, schema='quality')


def downgrade() -> None:
    op.drop_table('quality_test_results', schema='quality')
    op.drop_table('quality_test_tasks', schema='quality')
