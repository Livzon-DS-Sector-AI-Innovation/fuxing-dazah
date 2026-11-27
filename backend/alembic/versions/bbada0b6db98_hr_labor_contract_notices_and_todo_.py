"""hr 劳动合同：通知留痕表 + 合同来源列 + 扫描件换传原因列 + 离职办结单交接转办列

1. 新表 hr.contract_notice_logs：合同通知留痕（员工续签 / 领取 / 签字提醒三张卡 +
   部门负责人审批提醒，每次尝试发送写一行，失败与跳过同样留痕）
2. hr.labor_contracts 加来源列 origin（可空、无服务端默认：存量迁移行保持 NULL）
3. hr.contract_archive_versions 加换传原因列 reason（可空；首次上传为空）
4. hr.offboarding_cases 加 4 列（离职管理同期改动，一并落库）：clearance_pending /
   handover_to / dept_clerk / sms_sent_at，并同步 sms_status 的列注释

纯增量：只新增表与可空列，不改动、不删除已有列。
注意：本迁移不带外键约束（仓库惯例，BaseModel 的 created_by/updated_by FK 不落库）。

Revision ID: bbada0b6db98
Revises: 58152f3280b2
Create Date: 2026-11-27 12:14:38.786235
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bbada0b6db98'
down_revision: str | None = '58152f3280b2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = 'hr'


def upgrade() -> None:
    # 1. 合同通知留痕
    op.create_table(
        'contract_notice_logs',
        sa.Column('contract_id', sa.Uuid(), nullable=False, comment='劳动合同 ID（逻辑关联，无外键）'),
        sa.Column('kind', sa.String(length=16), nullable=False,
                  comment='通知类型: dept_approval 部门审批提醒 / renew 续签通知 / collect 领取通知 / sign 签字提醒'),
        sa.Column('recipient_name', sa.String(length=64), nullable=True, comment='收件人姓名（员工或部门负责人）'),
        sa.Column('recipient_open_id', sa.String(length=64), nullable=True, comment='收件人飞书 open_id'),
        sa.Column('status', sa.String(length=16), nullable=False, comment='结果: sent 已发送 / failed 发送失败 / skipped 跳过'),
        sa.Column('error_message', sa.String(length=255), nullable=True, comment='失败或跳过的原因'),
        sa.Column('created_by_name', sa.String(length=64), nullable=True, comment='触发发送的操作人姓名（定时任务为空）'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema=SCHEMA,
    )
    op.create_index('ix_contract_notice_contract', 'contract_notice_logs', ['contract_id'], unique=False, schema=SCHEMA)
    op.create_index('ix_contract_notice_created', 'contract_notice_logs', ['created_at'], unique=False, schema=SCHEMA)

    # 2. 合同来源（存量迁移行保持 NULL）
    op.add_column('labor_contracts', sa.Column(
        'origin', sa.String(length=16), nullable=True,
        comment='来源: renewal 续签生成 / manual 手工录入 / import Excel 导入 / migration 存量迁移；'
                'NULL = 迁移脚本写入的历史行（视同 migration）',
    ), schema=SCHEMA)

    # 3. 扫描件换传原因
    op.add_column('contract_archive_versions', sa.Column(
        'reason', sa.String(length=255), nullable=True,
        comment='换传原因（已有扫描件再上传时必填；首次上传为空）',
    ), schema=SCHEMA)

    # 4. 离职办结单：清退挂起 + 交接转办 + 短信发送时间
    op.add_column('offboarding_cases', sa.Column(
        'clearance_pending', sa.Boolean(), server_default='false', nullable=False,
        comment='清退交接审批挂起待发起（未到建议发起日，到期由轮询自动发起）',
    ), schema=SCHEMA)
    op.add_column('offboarding_cases', sa.Column(
        'handover_to', sa.String(length=64), nullable=True, comment='交接人（工作交接承接人）',
    ), schema=SCHEMA)
    op.add_column('offboarding_cases', sa.Column(
        'dept_clerk', sa.String(length=64), nullable=True, comment='部门办事员（确认工作交接事项）',
    ), schema=SCHEMA)
    op.add_column('offboarding_cases', sa.Column(
        'sms_sent_at', sa.DateTime(timezone=True), nullable=True, comment='短信发送时间（人工登记）',
    ), schema=SCHEMA)
    op.alter_column(
        'offboarding_cases', 'sms_status', existing_type=sa.VARCHAR(length=16),
        comment='短信状态: manual 已人工发送并登记 / sent / failed / not_configured（通道预留）',
        existing_comment='短信状态: sent/not_configured/failed（通道预留）',
        existing_nullable=True, schema=SCHEMA,
    )


def downgrade() -> None:
    op.alter_column(
        'offboarding_cases', 'sms_status', existing_type=sa.VARCHAR(length=16),
        comment='短信状态: sent/not_configured/failed（通道预留）',
        existing_comment='短信状态: manual 已人工发送并登记 / sent / failed / not_configured（通道预留）',
        existing_nullable=True, schema=SCHEMA,
    )
    op.drop_column('offboarding_cases', 'sms_sent_at', schema=SCHEMA)
    op.drop_column('offboarding_cases', 'dept_clerk', schema=SCHEMA)
    op.drop_column('offboarding_cases', 'handover_to', schema=SCHEMA)
    op.drop_column('offboarding_cases', 'clearance_pending', schema=SCHEMA)
    op.drop_column('contract_archive_versions', 'reason', schema=SCHEMA)
    op.drop_column('labor_contracts', 'origin', schema=SCHEMA)
    op.drop_index('ix_contract_notice_created', table_name='contract_notice_logs', schema=SCHEMA)
    op.drop_index('ix_contract_notice_contract', table_name='contract_notice_logs', schema=SCHEMA)
    op.drop_table('contract_notice_logs', schema=SCHEMA)
