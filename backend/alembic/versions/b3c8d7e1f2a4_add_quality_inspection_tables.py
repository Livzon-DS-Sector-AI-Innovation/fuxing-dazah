"""add quality inspection tables

Revision ID: b3c8d7e1f2a4
Revises: a1a29614b41e
Create Date: 2026-07-28 11:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b3c8d7e1f2a4'
down_revision: Union[str, None] = 'a1a29614b41e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建质量管理模块的检验记录、杂质明细、报告单表。"""
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")

    # ── 检验记录表 ──
    op.create_table('inspection_records',
        # 基本信息
        sa.Column('product_name', sa.String(length=200), nullable=False, comment='产品名称'),
        sa.Column('batch_number', sa.String(length=100), nullable=False, comment='批号'),
        sa.Column('form_id', sa.String(length=100), nullable=True, comment='表格编号'),
        sa.Column('standard_type', sa.String(length=20), nullable=True, comment='标准类型'),
        # 峰面积
        sa.Column('total_peak_area_a_first', sa.Float(), nullable=True, comment='供试液A总峰面积1st'),
        sa.Column('total_peak_area_a_second', sa.Float(), nullable=True, comment='供试液A总峰面积2nd'),
        sa.Column('main_peak_area_a_first', sa.Float(), nullable=True, comment='供试液A主峰面积1st'),
        sa.Column('main_peak_area_a_second', sa.Float(), nullable=True, comment='供试液A主峰面积2nd'),
        sa.Column('total_impurity_area_first', sa.Float(), nullable=True, comment='杂质总峰面积At 1st'),
        sa.Column('total_impurity_area_second', sa.Float(), nullable=True, comment='杂质总峰面积At 2nd'),
        sa.Column('any_unknown_impurity_first', sa.Float(), nullable=True, comment='任何未知杂质Ax 1st'),
        sa.Column('any_unknown_impurity_second', sa.Float(), nullable=True, comment='任何未知杂质Ax 2nd'),
        sa.Column('main_peak_area_b_first', sa.Float(), nullable=True, comment='供试液B主峰面积1st'),
        sa.Column('main_peak_area_b_second', sa.Float(), nullable=True, comment='供试液B主峰面积2nd'),
        # 判定
        sa.Column('all_pass', sa.Boolean(), server_default='true', nullable=False, comment='是否全部合格'),
        sa.Column('has_oot', sa.Boolean(), server_default='false', nullable=False, comment='是否有超趋势'),
        # 原始数据
        sa.Column('raw_data', postgresql.JSONB(), nullable=True, comment='完整原始解析数据备份'),
        sa.Column('excel_filename', sa.String(length=255), nullable=True, comment='上传的原始Excel文件名'),
        # Base
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='quality'
    )
    op.create_index('uq_quality_inspection_records_batch', 'inspection_records',
                    ['product_name', 'batch_number'],
                    unique=True, schema='quality',
                    postgresql_where=sa.text('is_deleted = false'))
    op.create_index('ix_quality_inspection_records_product', 'inspection_records',
                    ['product_name'], unique=False, schema='quality')
    op.create_index('ix_quality_inspection_records_created', 'inspection_records',
                    ['created_at'], unique=False, schema='quality')

    # ── 检验杂质明细表 ──
    op.create_table('inspection_impurities',
        sa.Column('inspection_record_id', sa.Uuid(), nullable=False, comment='关联检验记录'),
        sa.Column('name', sa.String(length=100), nullable=False, comment='杂质名称'),
        sa.Column('first_percent', sa.Float(), nullable=True, comment='第一份百分比'),
        sa.Column('second_percent', sa.Float(), nullable=True, comment='第二份百分比'),
        sa.Column('limit_value', sa.Float(), nullable=True, comment='合格限度值'),
        sa.Column('oot_haf', sa.Float(), nullable=True, comment='OOT阈值HAF'),
        sa.Column('oot_haa', sa.Float(), nullable=True, comment='OOT阈值HAA'),
        sa.Column('is_pass', sa.Boolean(), server_default='true', nullable=False, comment='合格判定'),
        sa.Column('is_oot', sa.Boolean(), server_default='false', nullable=False, comment='OOT判定'),
        # Base
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='quality'
    )
    op.create_index('ix_quality_impurities_record', 'inspection_impurities',
                    ['inspection_record_id'], unique=False, schema='quality')

    # ── 报告单记录表 ──
    op.create_table('report_records',
        sa.Column('inspection_record_id', sa.Uuid(), nullable=False, comment='关联检验记录'),
        sa.Column('template_path', sa.String(length=500), nullable=False, comment='模板路径'),
        sa.Column('product_name', sa.String(length=200), nullable=False, comment='产品名称'),
        sa.Column('batch_number', sa.String(length=100), nullable=False, comment='批号'),
        sa.Column('file_path', sa.String(length=500), nullable=True, comment='生成的docx文件路径'),
        sa.Column('file_size', sa.Integer(), nullable=True, comment='文件大小字节'),
        # Base
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='quality'
    )
    op.create_index('ix_quality_report_record_inspection', 'report_records',
                    ['inspection_record_id'], unique=False, schema='quality')


def downgrade() -> None:
    """删除质量管理模块相关表。"""
    op.drop_table('report_records', schema='quality')
    op.drop_table('inspection_impurities', schema='quality')
    op.drop_table('inspection_records', schema='quality')
