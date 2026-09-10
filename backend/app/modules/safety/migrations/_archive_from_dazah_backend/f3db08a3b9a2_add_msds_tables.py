"""add_msds_tables

为 MSDS 智能提取入库新增 3 张表：
  - msds_collection_records  （供应商资料表采集镜像 + 解析结果）
  - msds_documents           （MSDS 表台账镜像，29 字段）
  - msds_training_tasks      （学习任务，仅建表预留，分发/培训闭环阶段使用）

Revision ID: f3db08a3b9a2
Revises: fa7c46ad5c00
Create Date: 2026-08-06 15:56:21.195753
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3db08a3b9a2'
down_revision: Union[str, None] = 'fa7c46ad5c00'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    # ── 表 1：供应商资料采集镜像 ──
    op.create_table('msds_collection_records',
    sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='Bitable 记录 ID（供应商资料表同步主键）'),
    sa.Column('source_date', sa.Date(), nullable=True, comment='上传日期'),
    sa.Column('attachment', sa.JSON(), nullable=True, comment='供应商资料附件'),
    sa.Column('attachment_path', sa.String(length=512), nullable=True, comment='附件本地下载路径'),
    sa.Column('person_data', sa.JSON(), nullable=True, comment='人员(供应商联系人, 含 open_id)'),
    sa.Column('parse_status', sa.String(length=16), server_default='pending', nullable=False, comment='解析状态: pending/parsed/failed'),
    sa.Column('parse_error', sa.Text(), nullable=True, comment='解析失败原因'),
    sa.Column('parse_result', sa.JSON(), nullable=True, comment='AI 提取的 28 字段【数组】, 一个化学品一条'),
    sa.Column('msds_table_record_ids', sa.JSON(), nullable=True, comment='创建的 MSDS 表记录 feishu_record_id 数组（回写，1:N）'),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True, comment='写回 MSDS 表时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='safety'
    )
    op.create_index('idx_msds_collect_feishu', 'msds_collection_records', ['feishu_record_id'], unique=False, schema='safety')
    op.create_index('idx_msds_collect_status', 'msds_collection_records', ['parse_status'], unique=False, schema='safety')

    # ── 表 2：MSDS 台账镜像（29 字段）──
    op.create_table('msds_documents',
    sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='Bitable 记录 ID（MSDS 表同步主键）'),
    sa.Column('collection_record_id', sa.UUID(), nullable=True, comment='关联 msds_collection_records.id（溯源）'),
    sa.Column('source_date', sa.Date(), nullable=True, comment='日期'),
    sa.Column('name', sa.String(length=256), nullable=True, comment='物质名称'),
    sa.Column('cas_no', sa.String(length=64), nullable=True, comment='CAS号'),
    sa.Column('molecular_formula', sa.String(length=256), nullable=True, comment='分子式'),
    sa.Column('un_no', sa.String(length=64), nullable=True, comment='UN编号'),
    sa.Column('hazard_class', sa.String(length=32), nullable=True, comment='危险分级: normal/hazardous_1/hazardous_2（分发阶段用）'),
    sa.Column('hazard_statement', sa.Text(), nullable=True, comment='危险性说明'),
    sa.Column('label_elements', sa.Text(), nullable=True, comment='标签要素（仅平台存档, 写回 Bitable 丢弃）'),
    sa.Column('appearance', sa.Text(), nullable=True, comment='外观与现状'),
    sa.Column('solubility', sa.Text(), nullable=True, comment='溶解性'),
    sa.Column('melting_point', sa.Text(), nullable=True, comment='熔点'),
    sa.Column('boiling_point', sa.Text(), nullable=True, comment='沸点'),
    sa.Column('flash_point', sa.Text(), nullable=True, comment='闪点'),
    sa.Column('relative_density', sa.Text(), nullable=True, comment='相对密度'),
    sa.Column('explosion_upper_limit', sa.Text(), nullable=True, comment='爆炸上限(%)'),
    sa.Column('explosion_lower_limit', sa.Text(), nullable=True, comment='爆炸下限(%)'),
    sa.Column('autoignition_temperature', sa.Text(), nullable=True, comment='自燃温度'),
    sa.Column('decomposition_temperature', sa.Text(), nullable=True, comment='分解温度'),
    sa.Column('pc_twa', sa.Text(), nullable=True, comment='PC-TWA (mg/m3)'),
    sa.Column('pc_stel', sa.Text(), nullable=True, comment='PC-STEL (mg/m3)'),
    sa.Column('mac', sa.Text(), nullable=True, comment='MAC (mg/m3)'),
    sa.Column('health_hazard', sa.Text(), nullable=True, comment='健康危害'),
    sa.Column('environmental_hazard', sa.Text(), nullable=True, comment='环境危害'),
    sa.Column('first_aid', sa.Text(), nullable=True, comment='急救措施'),
    sa.Column('fire_fighting', sa.Text(), nullable=True, comment='消防措施'),
    sa.Column('leakage_response', sa.Text(), nullable=True, comment='泄漏应急处理'),
    sa.Column('waste_disposal', sa.Text(), nullable=True, comment='废弃处置'),
    sa.Column('exposure_controls', sa.Text(), nullable=True, comment='接触控制与个体防护'),
    sa.Column('handling_storage', sa.Text(), nullable=True, comment='操作处置与储存注意事项'),
    sa.Column('stability_reactivity', sa.Text(), nullable=True, comment='稳定性和反应性'),
    sa.Column('msds_attachment', sa.JSON(), nullable=True, comment='「MSDS附件」= 平台生成的标准模板文件'),
    sa.Column('msds_attachment_path', sa.String(length=512), nullable=True, comment='标准 docx 本地路径'),
    sa.Column('review_status', sa.String(length=16), server_default='pending', nullable=False, comment='复核状态: pending/approved/rejected（本期默认 pending）'),
    sa.Column('reviewed_by', sa.String(length=64), nullable=True, comment='复核人'),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True, comment='复核时间'),
    sa.Column('archive_status', sa.String(length=16), server_default='pending', nullable=False, comment='归档状态: pending/archived'),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True, comment='归档时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='safety'
    )
    op.create_index('idx_msds_feishu_record', 'msds_documents', ['feishu_record_id'], unique=False, schema='safety')
    op.create_index('idx_msds_cas_no', 'msds_documents', ['cas_no'], unique=False, schema='safety')
    op.create_index('idx_msds_name', 'msds_documents', ['name'], unique=False, schema='safety')
    op.create_index('idx_msds_review_status', 'msds_documents', ['review_status'], unique=False, schema='safety')

    # ── 表 3：学习任务（仅建表预留）──
    op.create_table('msds_training_tasks',
    sa.Column('msds_document_id', sa.UUID(), nullable=True, comment='关联 msds_documents.id'),
    sa.Column('target_name', sa.String(length=128), nullable=True, comment='目标人姓名'),
    sa.Column('target_open_id', sa.String(length=128), nullable=True, comment='飞书 open_id'),
    sa.Column('department', sa.String(length=128), nullable=True, comment='部门'),
    sa.Column('deadline', sa.Date(), nullable=True, comment='截止日期（普通5工作日/危化品2工作日）'),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False, comment='状态: pending/read/overdue'),
    sa.Column('remind_count', sa.Integer(), server_default='0', nullable=False, comment='已提醒次数'),
    sa.Column('confirm_message_id', sa.String(length=128), nullable=True, comment='飞书确认表单消息 ID'),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True, comment='确认时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='safety'
    )
    op.create_index('idx_msds_task_doc', 'msds_training_tasks', ['msds_document_id'], unique=False, schema='safety')
    op.create_index('idx_msds_task_user', 'msds_training_tasks', ['target_open_id'], unique=False, schema='safety')
    op.create_index('idx_msds_task_status', 'msds_training_tasks', ['status'], unique=False, schema='safety')


def downgrade() -> None:
    op.drop_index('idx_msds_task_status', table_name='msds_training_tasks', schema='safety')
    op.drop_index('idx_msds_task_user', table_name='msds_training_tasks', schema='safety')
    op.drop_index('idx_msds_task_doc', table_name='msds_training_tasks', schema='safety')
    op.drop_table('msds_training_tasks', schema='safety')

    op.drop_index('idx_msds_review_status', table_name='msds_documents', schema='safety')
    op.drop_index('idx_msds_name', table_name='msds_documents', schema='safety')
    op.drop_index('idx_msds_cas_no', table_name='msds_documents', schema='safety')
    op.drop_index('idx_msds_feishu_record', table_name='msds_documents', schema='safety')
    op.drop_table('msds_documents', schema='safety')

    op.drop_index('idx_msds_collect_status', table_name='msds_collection_records', schema='safety')
    op.drop_index('idx_msds_collect_feishu', table_name='msds_collection_records', schema='safety')
    op.drop_table('msds_collection_records', schema='safety')
