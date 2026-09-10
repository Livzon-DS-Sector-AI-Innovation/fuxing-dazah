"""add central_alarm_records

Revision ID: ef05484455e7
Revises: 813667b97e08
Create Date: 2026-08-24 09:35:03.242249
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ef05484455e7'
down_revision: Union[str, None] = '813667b97e08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── CLAUDE.md 铁律：autogenerate 不会自动生成 CREATE SCHEMA ──
    # safety schema 已存在（baseline 已建），但保留此句确保空库部署可执行
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    op.create_table(
        'central_alarm_records',
        sa.Column('feishu_record_id', sa.String(length=64), nullable=True,
                  comment='飞书 Bitable 记录 ID（同步主键；软删时置 NULL）'),
        sa.Column('source', sa.String(length=16), server_default='bitable', nullable=False,
                  comment='数据来源: bitable(飞书同步) / manual(预留)'),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True,
                  comment='最后同步时间（事件/全量同步回写）'),
        sa.Column('alarm_date', sa.DateTime(timezone=True), nullable=True,
                  comment='报警日期（Bitable「日期」列，datetime）'),
        sa.Column('post', sa.String(length=64), nullable=True, comment='岗位（Bitable「岗位」单选列）'),
        sa.Column('alarm_description', sa.Text(), nullable=True,
                  comment='报警情况说明（自由文本，AI 分析输入）'),
        sa.Column('special_note', sa.Text(), nullable=True, comment='特殊情况说明（自由文本，少数记录）'),
        sa.Column('workshop', sa.String(length=64), nullable=True,
                  comment='车间（如 车间一/车间二/车间四/新罐区）'),
        sa.Column('line', sa.String(length=64), nullable=True,
                  comment='产线/区域（如 达托/达巴/雷帕/乙醇纳滤）'),
        sa.Column('bt_extra', sa.JSON(), nullable=True,
                  comment='Bitable 多余字段兜底（联调用，不参与分析）'),
        sa.Column('ai_alarm_type', sa.String(length=64), nullable=True,
                  comment='AI 结构化报警类型: 高液位/低液位/高温/低温/空罐/误报/联锁/其他'),
        sa.Column('ai_equipment', sa.String(length=128), nullable=True,
                  comment='AI 抽取设备（如 R19150B 层析上柱罐）'),
        sa.Column('ai_pattern', sa.String(length=32), nullable=True,
                  comment='AI 异常模式: normal_transient(正常瞬报)/repeated(重复报警)/false_alarm(误报)/anomalous(异常依赖)'),
        sa.Column('ai_dimension', sa.String(length=32), nullable=True,
                  comment='AI 维度: process(工艺)/operation(人员操作)/equipment(设备设施)/other(其他)'),
        sa.Column('ai_reason_analysis', sa.Text(), nullable=True, comment='AI 原因分析（自然语言，40-120 字）'),
        sa.Column('ai_rectification_direction', sa.Text(), nullable=True, comment='AI 整改方向（30-80 字）'),
        sa.Column('ai_analyzed_at', sa.DateTime(timezone=True), nullable=True, comment='AI 分析完成时间（回写时间戳）'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        # BaseModel 继承字段（autogenerate 会显式列出）
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
        comment='中控报警记录（Bitable 镜像 + AI 分析字段）',
    )
    op.create_index('ix_central_alarm_ai_dimension', 'central_alarm_records', ['ai_dimension'], unique=False, schema='safety')
    op.create_index('ix_central_alarm_ai_pattern', 'central_alarm_records', ['ai_pattern'], unique=False, schema='safety')
    op.create_index('ix_central_alarm_alarm_date', 'central_alarm_records', ['alarm_date'], unique=False, schema='safety')
    op.create_index('ix_central_alarm_workshop', 'central_alarm_records', ['workshop'], unique=False, schema='safety')
    op.create_index('uq_central_alarm_feishu_record_id', 'central_alarm_records', ['feishu_record_id'],
                    unique=True, schema='safety',
                    postgresql_where=sa.text('is_deleted = false AND feishu_record_id IS NOT NULL'))


def downgrade() -> None:
    op.drop_index('uq_central_alarm_feishu_record_id', table_name='central_alarm_records',
                  schema='safety',
                  postgresql_where=sa.text('is_deleted = false AND feishu_record_id IS NOT NULL'))
    op.drop_index('ix_central_alarm_workshop', table_name='central_alarm_records', schema='safety')
    op.drop_index('ix_central_alarm_alarm_date', table_name='central_alarm_records', schema='safety')
    op.drop_index('ix_central_alarm_ai_pattern', table_name='central_alarm_records', schema='safety')
    op.drop_index('ix_central_alarm_ai_dimension', table_name='central_alarm_records', schema='safety')
    op.drop_table('central_alarm_records', schema='safety')
