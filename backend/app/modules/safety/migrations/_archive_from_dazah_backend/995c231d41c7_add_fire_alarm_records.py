"""add fire_alarm_records

Revision ID: 995c231d41c7
Revises: sched002a3b4c5d
Create Date: 2026-08-18 11:30:22.315863

手工清理：autogenerate 混入其他模块无关变更，只保留 fire_alarm_records 本表 DDL。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '995c231d41c7'
down_revision: Union[str, None] = 'sched002a3b4c5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── CLAUDE.md 铁律：autogenerate 不会自动生成 CREATE SCHEMA ──
    # safety schema 已存在（baseline 已建），但保留此句确保空库部署可执行
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    op.create_table('fire_alarm_records',
    sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='飞书 Bitable 记录 ID（同步主键；软删时置 NULL）'),
    sa.Column('source', sa.String(length=16), server_default='bitable', nullable=False, comment='数据来源: bitable(飞书同步) / manual(预留)'),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True, comment='最后同步时间（事件/全量同步回写）'),
    sa.Column('alarm_time', sa.DateTime(timezone=True), nullable=True, comment='报警时间'),
    sa.Column('alarm_type', sa.String(length=64), nullable=True, comment='报警类型'),
    sa.Column('department', sa.String(length=100), nullable=True, comment='报警部门'),
    sa.Column('department_leader_name', sa.String(length=100), nullable=True, comment='报警部门负责人姓名'),
    sa.Column('building', sa.String(length=100), nullable=True, comment='报警楼栋'),
    sa.Column('location', sa.String(length=255), nullable=True, comment='报警部位'),
    sa.Column('alarm_nature', sa.String(length=64), nullable=True, comment='报警性质'),
    sa.Column('cause_category', sa.String(length=64), nullable=True, comment='报警原因分类（人工填写）'),
    sa.Column('cause_description', sa.Text(), nullable=True, comment='具体报警原因（人工填写，AI 分析输入）'),
    sa.Column('bt_extra', sa.JSON(), nullable=True, comment='Bitable 多余字段兜底（联调用，不参与分析）'),
    sa.Column('ai_dimension', sa.String(length=32), nullable=True, comment='AI 维度分类: process(工艺) / operation(人员操作) / equipment(设备设施) / other(其他)'),
    sa.Column('ai_reason_analysis', sa.Text(), nullable=True, comment='AI 原因分析（自然语言，40-120 字）'),
    sa.Column('ai_rectification_direction', sa.Text(), nullable=True, comment='AI 整改方向（针对性与可操作性，30-80 字）'),
    sa.Column('ai_analyzed_at', sa.DateTime(timezone=True), nullable=True, comment='AI 分析完成时间（回写时间戳）'),
    sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='safety',
    comment='消防报警记录（Bitable 镜像 + AI 分析字段）'
    )
    # 部分唯一索引（CLAUDE.md 软删除铁律）
    op.create_index('uq_fire_alarm_feishu_record_id', 'fire_alarm_records', ['feishu_record_id'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false AND feishu_record_id IS NOT NULL'))
    op.create_index('ix_fire_alarm_alarm_time', 'fire_alarm_records', ['alarm_time'], unique=False, schema='safety')
    op.create_index('ix_fire_alarm_department', 'fire_alarm_records', ['department'], unique=False, schema='safety')
    op.create_index('ix_fire_alarm_ai_dimension', 'fire_alarm_records', ['ai_dimension'], unique=False, schema='safety')


def downgrade() -> None:
    op.drop_index('uq_fire_alarm_feishu_record_id', table_name='fire_alarm_records', schema='safety', postgresql_where=sa.text('is_deleted = false AND feishu_record_id IS NOT NULL'))
    op.drop_index('ix_fire_alarm_department', table_name='fire_alarm_records', schema='safety')
    op.drop_index('ix_fire_alarm_alarm_time', table_name='fire_alarm_records', schema='safety')
    op.drop_index('ix_fire_alarm_ai_dimension', table_name='fire_alarm_records', schema='safety')
    op.drop_table('fire_alarm_records', schema='safety')
