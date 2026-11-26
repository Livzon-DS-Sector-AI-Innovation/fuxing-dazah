"""hr 劳动合同电子档案库 + 离职合同台账（劳动合同管理 P2/P3）

1. hr.labor_contracts 加归档列：archive_status / archive_file_name /
   archive_uploaded_by / archive_uploaded_at（存量合同缺省「未归档」）
2. 新表 hr.contract_archive_versions：扫描件版本（一份合同一个合并文件，
   换传升版本、旧行保留可查；当前版唯一部分索引）
3. 新表 hr.contract_access_logs：扫描件调阅/下载留痕
4. hr.departure_records 加离职合同台账人工维护列：contract_termination_type /
   contract_approval_ref / separation_process_no / contract_original_status
5. 存量修正：已离职人员（有离职记录且离职日期已到，或档案状态为离职）的
   未完结合同统一置 terminated 并关联离职记录——两本台账不交叉、不再参与
   到期预警。可重复执行。

注意：本迁移不带外键约束（仓库惯例，BaseModel 的 created_by/updated_by FK 不落库）。

Revision ID: d2f7a94c6e18
Revises: b7e4a2c91d50
Create Date: 2026-11-25 15:00:00.000000
"""
from datetime import date

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd2f7a94c6e18'
down_revision: str | None = 'b7e4a2c91d50'
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = 'hr'
VERSIONS = 'contract_archive_versions'
ACCESS_LOGS = 'contract_access_logs'


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    ]


def upgrade() -> None:
    # 1. 合同行归档快照列
    op.add_column('labor_contracts', sa.Column(
        'archive_status', sa.String(length=16), server_default='unarchived', nullable=False,
        comment='归档状态: unarchived/archived（已上传扫描件）'), schema=SCHEMA)
    op.add_column('labor_contracts', sa.Column(
        'archive_file_name', sa.String(length=255), nullable=True,
        comment='当前版扫描件展示名（工号+姓名+签订次数+起止日期，服务端生成）'), schema=SCHEMA)
    op.add_column('labor_contracts', sa.Column(
        'archive_uploaded_by', sa.Uuid(), nullable=True, comment='最近一次归档人'), schema=SCHEMA)
    op.add_column('labor_contracts', sa.Column(
        'archive_uploaded_at', sa.DateTime(timezone=True), nullable=True, comment='最近一次归档时间'),
        schema=SCHEMA)

    # 2. 扫描件版本表
    op.create_table(
        VERSIONS,
        sa.Column('contract_id', sa.Uuid(), nullable=False, comment='劳动合同 ID（逻辑关联，无外键）'),
        sa.Column('version_no', sa.Integer(), nullable=False, comment='版本号（1 起算）'),
        sa.Column('is_current', sa.Boolean(), server_default='true', nullable=False, comment='是否当前版本'),
        sa.Column('storage_key', sa.String(length=255), nullable=False, comment='对象存储 key'),
        sa.Column('file_name', sa.String(length=255), nullable=False, comment='展示/下载文件名（工号+姓名+签订次数+起止日期）'),
        sa.Column('content_type', sa.String(length=64), nullable=False, comment='MIME 类型'),
        sa.Column('size', sa.Integer(), nullable=False, comment='文件大小（字节）'),
        sa.Column('remark', sa.String(length=512), nullable=True, comment='备注'),
        sa.Column('source', sa.String(length=16), server_default='single', nullable=False, comment='来源: single 单个上传 / batch 批量挂接'),
        *_base_columns(),
        sa.PrimaryKeyConstraint('id'),
        schema=SCHEMA,
    )
    op.create_index('ix_contract_archive_contract', VERSIONS, ['contract_id'], unique=False, schema=SCHEMA)
    op.create_index(
        'uq_contract_archive_current', VERSIONS, ['contract_id'],
        unique=True, schema=SCHEMA, postgresql_where=sa.text('is_current = true AND is_deleted = false'),
    )

    # 3. 调阅留痕表
    op.create_table(
        ACCESS_LOGS,
        sa.Column('contract_id', sa.Uuid(), nullable=False, comment='劳动合同 ID（逻辑关联，无外键）'),
        sa.Column('version_id', sa.Uuid(), nullable=True, comment='被调阅的扫描件版本 ID'),
        sa.Column('viewer_id', sa.Uuid(), nullable=True, comment='调阅人用户 ID'),
        sa.Column('viewer_name', sa.String(length=64), nullable=False, comment='调阅人姓名'),
        sa.Column('action', sa.String(length=16), nullable=False, comment='调阅动作: view 在线查看 / download 下载'),
        *_base_columns(),
        sa.PrimaryKeyConstraint('id'),
        schema=SCHEMA,
    )
    op.create_index('ix_contract_access_contract', ACCESS_LOGS, ['contract_id'], unique=False, schema=SCHEMA)
    op.create_index('ix_contract_access_created', ACCESS_LOGS, ['created_at'], unique=False, schema=SCHEMA)

    # 4. 离职台账人工维护列
    op.add_column('departure_records', sa.Column(
        'contract_termination_type', sa.String(length=24), nullable=True,
        comment='合同终止方式人工更正值；空=按合同到期日与离职类型自动判定'), schema=SCHEMA)
    op.add_column('departure_records', sa.Column(
        'contract_approval_ref', sa.String(length=128), nullable=True,
        comment='审批依据（审批实例/流程单号，人工补录）'), schema=SCHEMA)
    op.add_column('departure_records', sa.Column(
        'separation_process_no', sa.String(length=64), nullable=True,
        comment='离职流程单号（人工补录；有离职办结单时以办结单编号为准）'), schema=SCHEMA)
    op.add_column('departure_records', sa.Column(
        'contract_original_status', sa.String(length=16), server_default='unrecovered', nullable=False,
        comment='合同原件回收状态: unrecovered 未回收 / recovered 已回收 / waived 无需回收'), schema=SCHEMA)

    # 5. 存量修正：已离职人员的未完结合同归入离职台账
    #    「已离职」与运行期口径一致（labor_contract.repository.departed_expr）：有离职记录且
    #    离职日期已到，或员工档案状态为离职（离职人员通常已不在员工档案，两种来源都要看）。
    op.execute(sa.text("""
        UPDATE hr.labor_contracts c
        SET status = 'terminated',
            terminated_reason = CASE
                WHEN c.term_type = 'open' THEN '员工离职，无固定期限合同解除'
                WHEN c.end_date IS NOT NULL AND c.end_date <= :today THEN '合同到期终止（员工离职）'
                ELSE '员工离职，合同解除' END,
            terminated_at = now(),
            sign_token_hash = NULL,
            departure_record_id = (
                SELECT d.id FROM hr.departure_records d
                WHERE d.employee_number = c.employee_number AND d.is_deleted = false
                ORDER BY d.offboarding_date DESC NULLS LAST, d.created_at DESC
                LIMIT 1)
        WHERE c.is_deleted = false
          AND c.status IN ('active', 'pending_renewal', 'renewing', 'expired_unrenewed')
          AND (
                EXISTS (
                    SELECT 1 FROM hr.departure_records d
                    WHERE d.employee_number = c.employee_number
                      AND d.is_deleted = false
                      AND d.offboarding_date IS NOT NULL
                      AND d.offboarding_date <= :today)
             OR EXISTS (
                    SELECT 1 FROM hr.employees e
                    WHERE e.employee_number = c.employee_number
                      AND e.is_deleted = false
                      AND e.status = '离职')
          )
    """).bindparams(today=date.today()))


def downgrade() -> None:
    for col in ('contract_original_status', 'separation_process_no',
                'contract_approval_ref', 'contract_termination_type'):
        op.drop_column('departure_records', col, schema=SCHEMA)

    op.drop_index('ix_contract_access_created', table_name=ACCESS_LOGS, schema=SCHEMA)
    op.drop_index('ix_contract_access_contract', table_name=ACCESS_LOGS, schema=SCHEMA)
    op.drop_table(ACCESS_LOGS, schema=SCHEMA)

    op.drop_index('uq_contract_archive_current', table_name=VERSIONS, schema=SCHEMA)
    op.drop_index('ix_contract_archive_contract', table_name=VERSIONS, schema=SCHEMA)
    op.drop_table(VERSIONS, schema=SCHEMA)

    for col in ('archive_uploaded_at', 'archive_uploaded_by', 'archive_file_name', 'archive_status'):
        op.drop_column('labor_contracts', col, schema=SCHEMA)
