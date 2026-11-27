"""hr certificates and probation three-step approval

员工电子证件资料库 + 试用期管理升级：
1. 四张新表：employee_certificates / certificate_requirements /
   probation_safety_exams / probation_remind_logs
2. employees + is_key_position/direct_manager_name（飞书源表同步映射）
3. departments + department_manager_name/supervising_leader_name（审批人按部门配置）
4. probation_reviews 三级审批链改造：reviewer_* → direct_manager_*，状态机
   pending_reviewer/pending_hr → pending_step1/2/3，存量数据同步迁移

Revision ID: 5142d97887e4
Revises: b3e5c8f1a240
Create Date: 2026-11-23 10:04:44.936049
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5142d97887e4'
down_revision: Union[str, None] = 'b3e5c8f1a240'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = 'hr'


def upgrade() -> None:
    # ── 1. 员工证件资料库 ──
    op.create_table(
        'employee_certificates',
        sa.Column('employee_id', sa.Uuid(), nullable=False, comment='员工档案ID'),
        sa.Column('category', sa.String(length=32), nullable=False, comment='证件类别（见 CATEGORIES）'),
        sa.Column('certificate_name', sa.String(length=128), nullable=True, comment='证件名称（如：低压电工证）'),
        sa.Column('certificate_no', sa.String(length=64), nullable=True, comment='证件号码（输出时脱敏）'),
        sa.Column('issue_date', sa.Date(), nullable=True, comment='发证日期'),
        sa.Column('expiry_date', sa.Date(), nullable=True, comment='有效期至（长期有效时为空）'),
        sa.Column('is_permanent', sa.Boolean(), server_default='false', nullable=False, comment='长期有效'),
        sa.Column('version_no', sa.Integer(), server_default='1', nullable=False, comment='版本号（同员工同类别递增，1 为首版）'),
        sa.Column('is_current', sa.Boolean(), server_default='true', nullable=False, comment='是否当前版本'),
        sa.Column('storage_key', sa.String(length=256), nullable=False, comment='对象存储key'),
        sa.Column('filename', sa.String(length=255), nullable=False, comment='原始文件名'),
        sa.Column('content_type', sa.String(length=64), nullable=False, comment='MIME类型'),
        sa.Column('size', sa.Integer(), nullable=False, comment='文件大小（字节）'),
        sa.Column('remark', sa.String(length=512), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema=SCHEMA,
    )
    op.create_index('ix_emp_cert_employee', 'employee_certificates', ['employee_id'], unique=False, schema=SCHEMA)
    op.create_index('ix_emp_cert_category', 'employee_certificates', ['category'], unique=False, schema=SCHEMA)
    op.create_index(
        'uq_emp_cert_current', 'employee_certificates', ['employee_id', 'category'],
        unique=True, schema=SCHEMA,
        postgresql_where=sa.text('is_current = true AND is_deleted = false'),
    )

    op.create_table(
        'certificate_requirements',
        sa.Column('category', sa.String(length=32), nullable=False, comment='证件类别'),
        sa.Column('applies_to', sa.String(length=16), nullable=False, comment='适用范围: all全员必交/key_position仅重点岗位追加'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema=SCHEMA,
    )
    op.create_index(
        'uq_cert_req_active', 'certificate_requirements', ['category', 'applies_to'],
        unique=True, schema=SCHEMA,
        postgresql_where=sa.text('is_deleted = false'),
    )

    # ── 2. 安全考试 + 提醒日志 ──
    op.create_table(
        'probation_safety_exams',
        sa.Column('employee_id', sa.Uuid(), nullable=False, comment='员工档案ID'),
        sa.Column('exam_date', sa.Date(), nullable=False, comment='考试日期'),
        sa.Column('passed', sa.Boolean(), nullable=False, comment='是否合格'),
        sa.Column('score', sa.Float(), nullable=True, comment='分数'),
        sa.Column('entered_by', sa.String(length=64), nullable=True, comment='录入人（安全办）'),
        sa.Column('remark', sa.String(length=256), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema=SCHEMA,
    )
    op.create_index('ix_pse_employee', 'probation_safety_exams', ['employee_id'], unique=False, schema=SCHEMA)

    op.create_table(
        'probation_remind_logs',
        sa.Column('employee_id', sa.Uuid(), nullable=False, comment='员工档案ID'),
        sa.Column('remind_type', sa.String(length=32), nullable=True, comment='提醒类型: safety_exam_60d满60天安全考试/probation_30d转正前30天'),
        sa.Column('reminded_at', sa.DateTime(timezone=True), nullable=False, comment='提醒时间'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema=SCHEMA,
    )
    op.create_index(
        'uq_prl_once', 'probation_remind_logs', ['employee_id', 'remind_type'],
        unique=True, schema=SCHEMA,
        postgresql_where=sa.text('is_deleted = false'),
    )

    # ── 3. employees / departments 加列 ──
    op.add_column('employees', sa.Column('is_key_position', sa.Boolean(), nullable=True, comment='是否重点岗位（影响试用期时长/安全考试节点/应交证件清单）'), schema=SCHEMA)
    op.add_column('employees', sa.Column('direct_manager_name', sa.String(length=64), nullable=True, comment='直属上级姓名（转正评估第一级）'), schema=SCHEMA)
    op.alter_column('employees', 'probation_end_date', existing_type=sa.DATE(),
                    comment='转正到期日（空=按时长配置派生；试用期延长时写入新日期）',
                    existing_nullable=True, schema=SCHEMA)
    op.add_column('departments', sa.Column('department_manager_name', sa.String(length=64), nullable=True, comment='部门负责人（转正审批第二级）'), schema=SCHEMA)
    op.add_column('departments', sa.Column('supervising_leader_name', sa.String(length=64), nullable=True, comment='分管领导（转正审批第三级）'), schema=SCHEMA)

    # ── 4. probation_reviews 三级审批链 ──
    # 4.1 先放宽活跃唯一索引（where 条件里的旧状态即将消失）
    op.drop_index('uq_pr_employee_active', table_name='probation_reviews', schema=SCHEMA)
    # 4.2 新列先可空加出（表内有存量行，NOT NULL 需回填后再收紧）
    op.add_column('probation_reviews', sa.Column('current_step', sa.Integer(), server_default='1', nullable=True, comment='当前审批级: 1直属上级/2部门经理/3分管领导'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('direct_manager_name', sa.String(length=64), nullable=True, comment='直属上级姓名'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('direct_manager_open_id', sa.String(length=64), nullable=True, comment='直属上级飞书open_id'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('dept_manager_name', sa.String(length=64), nullable=True, comment='部门经理姓名'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('dept_manager_open_id', sa.String(length=64), nullable=True, comment='部门经理飞书open_id'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('leader_name', sa.String(length=64), nullable=True, comment='分管领导姓名'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('leader_open_id', sa.String(length=64), nullable=True, comment='分管领导飞书open_id'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('direct_manager_decided_at', sa.DateTime(timezone=True), nullable=True, comment='直属上级提交时间'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('dept_manager_decision', sa.String(length=8), nullable=True, comment='部门经理审批: 同意/退回'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('dept_manager_comment', sa.Text(), nullable=True, comment='部门经理审批意见'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('dept_manager_decided_at', sa.DateTime(timezone=True), nullable=True, comment='部门经理审批时间'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('leader_decision', sa.String(length=8), nullable=True, comment='分管领导审批: 同意/退回'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('leader_comment', sa.Text(), nullable=True, comment='分管领导审批意见'), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('leader_decided_at', sa.DateTime(timezone=True), nullable=True, comment='分管领导审批时间'), schema=SCHEMA)
    # 4.3 存量数据迁移：reviewer_* → direct_manager_*，状态 pending_reviewer/pending_hr → pending_step1/pending_step3
    op.execute(
        "UPDATE hr.probation_reviews SET "
        "direct_manager_name = COALESCE(reviewer_name, '未登记'), "
        "direct_manager_open_id = COALESCE(reviewer_open_id, 'unknown'), "
        "direct_manager_decided_at = submitted_at, "
        "current_step = CASE WHEN status = 'pending_hr' THEN 3 ELSE 1 END, "
        "status = CASE status WHEN 'pending_reviewer' THEN 'pending_step1' "
        "WHEN 'pending_hr' THEN 'pending_step3' ELSE status END"
    )
    # 4.4 回填完成后收紧 NOT NULL + 默认值，再删旧列、改注释
    op.alter_column('probation_reviews', 'current_step', existing_type=sa.Integer(),
                    nullable=False, server_default='1', schema=SCHEMA)
    op.alter_column('probation_reviews', 'direct_manager_name', existing_type=sa.String(length=64),
                    nullable=False, schema=SCHEMA)
    op.alter_column('probation_reviews', 'direct_manager_open_id', existing_type=sa.String(length=64),
                    nullable=False, schema=SCHEMA)
    op.alter_column('probation_reviews', 'status', existing_type=sa.String(length=16),
                    server_default='pending_step1',
                    comment='pending_step1直属上级待评/pending_step2部门经理待审/pending_step3分管领导待审'
                            '/effective已生效/rejected未通过或退回/cancelled已取消',
                    existing_nullable=False, schema=SCHEMA)
    op.alter_column('probation_reviews', 'conclusion', existing_type=sa.String(length=8),
                    comment='直属上级结论: 通过/延长/不通过', existing_nullable=True, schema=SCHEMA)
    op.alter_column('probation_reviews', 'comment', existing_type=sa.Text(),
                    comment='直属上级评语', existing_nullable=True, schema=SCHEMA)
    op.alter_column('probation_reviews', 'hr_note', existing_type=sa.String(length=256),
                    comment='HR 附注/生效回写重试说明', existing_nullable=True, schema=SCHEMA)
    op.alter_column('probation_reviews', 'reviewed_by', existing_type=sa.String(length=64),
                    comment='HR 操作人（兜底生效/取消）', existing_nullable=True, schema=SCHEMA)
    op.alter_column('probation_reviews', 'reviewed_at', existing_type=sa.DateTime(timezone=True),
                    comment='HR 操作时间', existing_nullable=True, schema=SCHEMA)
    op.drop_column('probation_reviews', 'submitted_at', schema=SCHEMA)
    op.drop_column('probation_reviews', 'reviewer_open_id', schema=SCHEMA)
    op.drop_column('probation_reviews', 'reviewer_name', schema=SCHEMA)
    # 4.5 新 where 条件的活跃唯一索引
    op.create_index(
        'uq_pr_employee_active', 'probation_reviews', ['employee_id'],
        unique=True, schema=SCHEMA,
        postgresql_where=sa.text(
            "status IN ('pending_step1', 'pending_step2', 'pending_step3') AND is_deleted = false"
        ),
    )

    # ── 5. 默认应交证件清单种子（全员：身份证/学历证；重点岗位追加三类）──
    op.execute(
        "INSERT INTO hr.certificate_requirements (id, category, applies_to, created_at, updated_at, is_deleted) "
        "SELECT gen_random_uuid(), c.category, c.applies_to, now(), now(), false "
        "FROM (VALUES "
        "('id_card', 'all'), ('graduation', 'all'), "
        "('professional_qualification', 'key_position'), "
        "('special_operation', 'key_position'), ('health', 'key_position') "
        ") AS c(category, applies_to) "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM hr.certificate_requirements r "
        "  WHERE r.category = c.category AND r.applies_to = c.applies_to AND r.is_deleted = false)"
    )

    # ── 6. 试用期时长配置种子（一般 3 个月 / 重点岗位 6 个月，界面可改）──
    op.execute(
        "INSERT INTO hr.system_settings (id, key, value, description, created_at, updated_at, is_deleted) "
        "VALUES "
        "(gen_random_uuid(), 'probation.duration_months.standard', '3', '试用期月数（一般岗位）', now(), now(), false), "
        "(gen_random_uuid(), 'probation.duration_months.key_position', '6', '试用期月数（重点岗位）', now(), now(), false) "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_index('uq_pr_employee_active', table_name='probation_reviews', schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('reviewer_name', sa.String(length=64), nullable=True), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('reviewer_open_id', sa.String(length=64), nullable=True), schema=SCHEMA)
    op.add_column('probation_reviews', sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True), schema=SCHEMA)
    op.execute(
        "UPDATE hr.probation_reviews SET "
        "reviewer_name = direct_manager_name, reviewer_open_id = direct_manager_open_id, "
        "submitted_at = direct_manager_decided_at, "
        "status = CASE status WHEN 'pending_step1' THEN 'pending_reviewer' "
        "WHEN 'pending_step3' THEN 'pending_hr' WHEN 'pending_step2' THEN 'pending_reviewer' "
        "WHEN 'rejected' THEN 'cancelled' ELSE status END"
    )
    op.alter_column('probation_reviews', 'reviewer_name', existing_type=sa.String(length=64), nullable=False, schema=SCHEMA)
    op.alter_column('probation_reviews', 'reviewer_open_id', existing_type=sa.String(length=64), nullable=False, schema=SCHEMA)
    op.alter_column('probation_reviews', 'status', existing_type=sa.String(length=16),
                    server_default='pending_reviewer', comment='pending_reviewer待评估/pending_hr待HR确认/effective已生效/cancelled已取消',
                    existing_nullable=False, schema=SCHEMA)
    op.drop_column('probation_reviews', 'leader_decided_at', schema=SCHEMA)
    op.drop_column('probation_reviews', 'leader_comment', schema=SCHEMA)
    op.drop_column('probation_reviews', 'leader_decision', schema=SCHEMA)
    op.drop_column('probation_reviews', 'dept_manager_decided_at', schema=SCHEMA)
    op.drop_column('probation_reviews', 'dept_manager_comment', schema=SCHEMA)
    op.drop_column('probation_reviews', 'dept_manager_decision', schema=SCHEMA)
    op.drop_column('probation_reviews', 'direct_manager_decided_at', schema=SCHEMA)
    op.drop_column('probation_reviews', 'leader_open_id', schema=SCHEMA)
    op.drop_column('probation_reviews', 'leader_name', schema=SCHEMA)
    op.drop_column('probation_reviews', 'dept_manager_open_id', schema=SCHEMA)
    op.drop_column('probation_reviews', 'dept_manager_name', schema=SCHEMA)
    op.drop_column('probation_reviews', 'direct_manager_open_id', schema=SCHEMA)
    op.drop_column('probation_reviews', 'direct_manager_name', schema=SCHEMA)
    op.drop_column('probation_reviews', 'current_step', schema=SCHEMA)
    op.create_index(
        'uq_pr_employee_active', 'probation_reviews', ['employee_id'],
        unique=True, schema=SCHEMA,
        postgresql_where=sa.text("status IN ('pending_reviewer', 'pending_hr') AND is_deleted = false"),
    )
    op.drop_column('departments', 'supervising_leader_name', schema=SCHEMA)
    op.drop_column('departments', 'department_manager_name', schema=SCHEMA)
    op.drop_column('employees', 'direct_manager_name', schema=SCHEMA)
    op.drop_column('employees', 'is_key_position', schema=SCHEMA)
    op.drop_index('uq_prl_once', table_name='probation_remind_logs', schema=SCHEMA)
    op.drop_table('probation_remind_logs', schema=SCHEMA)
    op.drop_index('ix_pse_employee', table_name='probation_safety_exams', schema=SCHEMA)
    op.drop_table('probation_safety_exams', schema=SCHEMA)
    op.drop_index('uq_cert_req_active', table_name='certificate_requirements', schema=SCHEMA)
    op.drop_table('certificate_requirements', schema=SCHEMA)
    op.drop_index('uq_emp_cert_current', table_name='employee_certificates', schema=SCHEMA)
    op.drop_index('ix_emp_cert_category', table_name='employee_certificates', schema=SCHEMA)
    op.drop_index('ix_emp_cert_employee', table_name='employee_certificates', schema=SCHEMA)
    op.drop_table('employee_certificates', schema=SCHEMA)
    op.execute("DELETE FROM hr.system_settings WHERE key IN ('probation.duration_months.standard', 'probation.duration_months.key_position')")
