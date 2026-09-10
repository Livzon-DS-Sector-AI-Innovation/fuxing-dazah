"""rebuild occupational health tables

职业健康管理系统重构（backend-design.md §一/§二）：
- 新建 5 张表：oh_persons / oh_positions / oh_hazard_factors / oh_exam_applications / oh_followups
- 重建 oh_health_exams（drop + recreate，保留表名，旧表零业务数据，Q9 已确认）
- 删除 oh_hazard_monitors（监测功能废弃，D2）
- 唯一约束全部使用部分唯一索引（WHERE is_deleted = false），软删清空唯一键字段

Revision ID: 4af6c8f79ac8
Revises: 5932b971f04b
Create Date: 2026-08-13 11:16:26.361709
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4af6c8f79ac8'
down_revision: Union[str, None] = '5932b971f04b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns() -> list[sa.Column]:
    """BaseModel 公共列（id/created_at/updated_at/created_by/updated_by/is_deleted）"""
    return [
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    ]


def upgrade() -> None:
    # 1. 保险：safety schema 已存在，幂等无害（CLAUDE.md：新建 schema 需手动 CREATE SCHEMA）
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    # 2. 删除废弃监测表 + 旧体检表（重建）
    op.drop_table("oh_hazard_monitors", schema="safety")
    op.drop_table("oh_health_exams", schema="safety")

    # ── 3. oh_persons 人员汇总台账 ──
    op.create_table(
        'oh_persons',
        sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='Bitable 记录 ID（同步主键）'),
        sa.Column('source', sa.String(length=16), server_default='bitable', nullable=False, comment='数据来源: bitable/manual'),
        sa.Column('name', sa.String(length=100), nullable=False, comment='员工姓名'),
        sa.Column('id_card_no', sa.String(length=32), nullable=True, comment='身份证号（关联键，98% 覆盖）'),
        sa.Column('employee_no', sa.String(length=64), nullable=True, comment='工号（业务键，43% 缺失）'),
        sa.Column('user_id', sa.Uuid(), nullable=True, comment='关联 identity.users.id（无 FK，可空）'),
        sa.Column('open_id', sa.String(length=64), nullable=True, comment='飞书 open_id（Bitable 人员字段解析）'),
        sa.Column('department', sa.String(length=100), nullable=True, comment='部门'),
        sa.Column('position', sa.String(length=100), nullable=True, comment='岗位'),
        sa.Column('gender', sa.String(length=16), nullable=True, comment='性别'),
        sa.Column('age', sa.Integer(), nullable=True, comment='年龄（Bitable 公式同步）'),
        sa.Column('marital_status', sa.String(length=16), nullable=True, comment='婚姻状况'),
        sa.Column('phone', sa.String(length=32), nullable=True, comment='电话'),
        sa.Column('total_work_years', sa.Float(), nullable=True, comment='总工龄（年.月折算）'),
        sa.Column('hazard_exposure_years', sa.Float(), nullable=True, comment='接害工龄（年.月折算）'),
        sa.Column('hazard_factors', sa.JSON(), nullable=True, comment='接触危害因素 [标准名]（按岗位从 oh_positions 同步）'),
        sa.Column('last_exam_at', sa.DateTime(timezone=True), nullable=True, comment='最后体检时间（平台回填）'),
        sa.Column('last_exam_type', sa.String(length=32), nullable=True, comment='最后体检类别: pre_employment/periodic/post_employment/transfer/emergency'),
        sa.Column('last_exam_conclusion', sa.String(length=32), nullable=True, comment='最后体检结论（ai_conclusion 归一）'),
        sa.Column('last_exam_summary', sa.Text(), nullable=True, comment='最后体检摘要（AI summary_text）'),
        sa.Column('exam_record_ids', sa.JSON(), nullable=True, comment='体检记录 ID 数组（对应 Bitable link 关联）'),
        sa.Column('safety_officer', sa.String(length=100), nullable=True, comment='部门安全员（与申请表对齐）'),
        sa.Column('work_status', sa.String(length=16), nullable=True, comment='在岗状态: on_post/off_post/pre_employment/transfer（原「最后体检状态」更名）'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        *_base_columns(),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
        comment='职业健康人员汇总台账（Bitable 镜像）'
    )

    # ── 4. oh_health_exams 体检记录（重建，新结构）──
    op.create_table(
        'oh_health_exams',
        sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='Bitable 记录 ID'),
        sa.Column('source', sa.String(length=16), server_default='bitable', nullable=False, comment='数据来源: bitable/manual'),
        sa.Column('exam_no', sa.String(length=64), nullable=True, comment='体检号（Bitable 自动编号字段）'),
        sa.Column('person_id', sa.Uuid(), nullable=True, comment='关联 oh_persons.id（无 FK）'),
        sa.Column('employee_name', sa.String(length=100), nullable=False, comment='员工姓名（冗余，便于查询）'),
        sa.Column('id_card_no', sa.String(length=32), nullable=True, comment='身份证号（关联键冗余）'),
        sa.Column('employee_no', sa.String(length=64), nullable=True, comment='工号（冗余）'),
        sa.Column('department', sa.String(length=100), nullable=True, comment='部门'),
        sa.Column('position', sa.String(length=100), nullable=True, comment='岗位（原 Bitable「工种」更名）'),
        sa.Column('gender', sa.String(length=16), nullable=True, comment='性别'),
        sa.Column('age', sa.Integer(), nullable=True, comment='年龄（公式）'),
        sa.Column('marital_status', sa.String(length=16), nullable=True, comment='婚姻状况'),
        sa.Column('phone', sa.String(length=32), nullable=True, comment='电话'),
        sa.Column('exam_type', sa.String(length=32), nullable=False, comment='体检类型: pre_employment/periodic/post_employment/transfer/emergency'),
        sa.Column('exam_agency', sa.String(length=255), nullable=True, comment='体检机构'),
        sa.Column('scheduled_date', sa.DateTime(timezone=True), nullable=True, comment='登记时间（Bitable「登记时间」）'),
        sa.Column('exam_date', sa.DateTime(timezone=True), nullable=True, comment='实际体检日期'),
        sa.Column('report_date', sa.DateTime(timezone=True), nullable=True, comment='报告日期'),
        sa.Column('hazard_factors', sa.JSON(), nullable=True, comment='危害因素 [标准名]（多选）'),
        sa.Column('protection_measures', sa.Text(), nullable=True, comment='防护措施（Bitable 公式）'),
        sa.Column('total_work_years', sa.Float(), nullable=True, comment='总工龄'),
        sa.Column('hazard_exposure_years', sa.Float(), nullable=True, comment='接害工龄'),
        sa.Column('exam_result', sa.Text(), nullable=True, comment='体检结果（大段文本，AI 输入①）'),
        sa.Column('exam_conclusion', sa.Text(), nullable=True, comment='检查结论（大段文本，AI 输入①）'),
        sa.Column('treatment_advice_raw', sa.Text(), nullable=True, comment='处理意见原文（AI 输入①）'),
        sa.Column('paper_report_kept', sa.String(length=16), nullable=True, comment='纸质报告留存: yes/no'),
        sa.Column('synced_to_summary', sa.Boolean(), nullable=True, comment='是否已同步汇总表（平台回写 Bitable）'),
        sa.Column('source_table', sa.String(length=64), nullable=True, comment='Bitable Source Table（推断 exam_type 用）'),
        sa.Column('source_record_id', sa.String(length=64), nullable=True, comment='Bitable Source Record ID'),
        sa.Column('attachments', sa.JSON(), nullable=True, comment='体检报告附件 [{name,file_token,url,...}]'),
        sa.Column('attachment_paths', sa.JSON(), nullable=True, comment='附件本地路径 [string]'),
        sa.Column('status', sa.String(length=32), server_default='pending', nullable=False, comment='机器状态（兼容旧前端）: pending/scheduled/in_progress/completed/archived'),
        sa.Column('ai_parse_status', sa.String(length=16), server_default='pending', nullable=False, comment='AI 解析状态: pending/parsing/parsed/failed'),
        sa.Column('ai_parse_error', sa.Text(), nullable=True, comment='解析失败原因'),
        sa.Column('ai_parse_result', sa.JSON(), nullable=True, comment='OhExamReportParseOutput 全量（abnormal_indicators/conclusion_category/...）'),
        sa.Column('ai_interpretation', sa.Text(), nullable=True, comment='AI智能解读文本（回写 Bitable）'),
        sa.Column('ai_conclusion', sa.String(length=32), nullable=True, comment='AI 结论分类: normal/abnormal_other/contraindicated/suspected_od/od_diagnosed/re_examination'),
        sa.Column('ai_contraindication_factors', sa.JSON(), nullable=True, comment='AI 职业禁忌证涉及危害因素 [标准名]'),
        sa.Column('ai_fitness', sa.String(length=32), nullable=True, comment='AI 适配: fit/fit_with_restriction/unfit'),
        sa.Column('ai_override_notes', sa.Text(), nullable=True, comment='人工覆盖结论备注（留痕）'),
        sa.Column('override_conclusion', sa.String(length=32), nullable=True, comment='人工覆盖结论（非空表示已覆盖 AI）'),
        sa.Column('override_by', sa.Uuid(), nullable=True, comment='覆盖人 identity.users.id'),
        sa.Column('override_at', sa.DateTime(timezone=True), nullable=True, comment='覆盖时间'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        *_base_columns(),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
        comment='职业健康体检记录（Bitable 镜像 + AI 解析字段）'
    )

    # ── 5. oh_positions 岗位危害台账 ──
    op.create_table(
        'oh_positions',
        sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='Bitable 记录 ID'),
        sa.Column('source', sa.String(length=16), server_default='bitable', nullable=False, comment='数据来源: bitable/manual'),
        sa.Column('department', sa.String(length=100), nullable=True, comment='部门'),
        sa.Column('position', sa.String(length=100), nullable=True, comment='岗位'),
        sa.Column('job_title', sa.String(length=100), nullable=True, comment='职务'),
        sa.Column('hazard_factors', sa.JSON(), nullable=True, comment='危害因素 [标准名]（多选 43 项）'),
        sa.Column('hazard_factors_status', sa.String(length=16), nullable=True, comment='filled/empty/inferred（二期 AI 推断用）'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        *_base_columns(),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
        comment='岗位危害因素台账（Bitable 镜像）'
    )

    # ── 6. oh_hazard_factors 危害因素 PPE 字典 ──
    op.create_table(
        'oh_hazard_factors',
        sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='Bitable 记录 ID'),
        sa.Column('source', sa.String(length=16), server_default='bitable', nullable=False, comment='数据来源: bitable/manual'),
        sa.Column('factor_name', sa.String(length=100), nullable=False, comment='危害因素标准名（43 项之一）'),
        sa.Column('ppe_respiratory', sa.Text(), nullable=True, comment='呼吸防护用品（半面罩/全面罩两档）'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        *_base_columns(),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
        comment='危害因素 PPE 映射字典（Bitable 镜像）'
    )

    # ── 7. oh_exam_applications 转岗离岗申请 ──
    op.create_table(
        'oh_exam_applications',
        sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='Bitable 记录 ID'),
        sa.Column('source', sa.String(length=16), server_default='bitable', nullable=False, comment='数据来源: bitable/manual'),
        sa.Column('application_no', sa.String(length=64), nullable=True, comment='申请编号（文本/URL）'),
        sa.Column('apply_status', sa.String(length=16), nullable=True, comment='申请状态: 已通过/审批中/已拒绝/已取消/已终止/已撤回/已删除'),
        sa.Column('approval_flow', sa.String(length=100), nullable=True, comment='审批流程名称'),
        sa.Column('approval_node', sa.String(length=100), nullable=True, comment='当前审批节点'),
        sa.Column('current_handler', sa.String(length=100), nullable=True, comment='当前处理人'),
        sa.Column('initiator_name', sa.String(length=100), nullable=True, comment='发起人姓名'),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True, comment='发起时间'),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True, comment='完成时间'),
        sa.Column('transfer_type', sa.String(length=16), nullable=True, comment='transfer/post_employment（转岗/离岗）'),
        sa.Column('exam_type', sa.String(length=32), nullable=True, comment='体检类型: 离岗体检/转岗体检'),
        sa.Column('employee_name', sa.String(length=100), nullable=True, comment='员工姓名'),
        sa.Column('id_card_no', sa.String(length=32), nullable=True, comment='身份证号'),
        sa.Column('department', sa.String(length=100), nullable=True, comment='原部门'),
        sa.Column('position', sa.String(length=100), nullable=True, comment='原岗位'),
        sa.Column('new_department', sa.String(length=100), nullable=True, comment='转入部门'),
        sa.Column('new_position', sa.String(length=100), nullable=True, comment='转入岗位'),
        sa.Column('transfer_date', sa.DateTime(timezone=True), nullable=True, comment='转岗日期'),
        sa.Column('leave_date', sa.DateTime(timezone=True), nullable=True, comment='离岗日期'),
        sa.Column('dept_safety_officer', sa.String(length=100), nullable=True, comment='部门安全员'),
        sa.Column('applicant_name', sa.String(length=100), nullable=True, comment='申请人'),
        sa.Column('apply_date', sa.DateTime(timezone=True), nullable=True, comment='申请日期'),
        sa.Column('diff_analyze_status', sa.String(length=16), server_default='none', nullable=False, comment='差异分析状态: none/parsing/analyzed/failed'),
        sa.Column('diff_analyze_error', sa.Text(), nullable=True, comment='差异分析失败原因'),
        sa.Column('diff_analyze_result', sa.JSON(), nullable=True, comment='OhTransferDiffOutput 全量'),
        sa.Column('diff_summary', sa.Text(), nullable=True, comment='差异分析摘要（回写 Bitable「差异分析结论」）'),
        sa.Column('needs_exam', sa.Boolean(), nullable=True, comment='是否需体检（AI 输出）'),
        sa.Column('exam_suggestion', sa.String(length=32), nullable=True, comment='建议体检类型: pre_employment/periodic/transfer'),
        sa.Column('created_exam_id', sa.Uuid(), nullable=True, comment='自动创建的体检登记 oh_health_exams.id（联动）'),
        sa.Column('bt_extra', sa.JSON(), nullable=True, comment='Bitable 脏字段（备案残留等，镜像忽略主字段后兜底）'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        *_base_columns(),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
        comment='职业健康体检申请（转岗/离岗审批流入口）'
    )

    # ── 8. oh_followups 异常随访 ──
    op.create_table(
        'oh_followups',
        sa.Column('exam_id', sa.Uuid(), nullable=True, comment='关联 oh_health_exams.id（无 FK）'),
        sa.Column('person_id', sa.Uuid(), nullable=True, comment='关联 oh_persons.id（无 FK）'),
        sa.Column('person_name', sa.String(length=100), nullable=True, comment='人员姓名（冗余）'),
        sa.Column('indicator_name', sa.String(length=100), nullable=True, comment='异常指标名'),
        sa.Column('indicator_value', sa.String(length=100), nullable=True, comment='指标值（保留原文+单位）'),
        sa.Column('reference_range', sa.String(length=100), nullable=True, comment='参考范围'),
        sa.Column('abnormal_level', sa.String(length=16), nullable=True, comment='异常程度: mild/moderate/severe'),
        sa.Column('category', sa.String(length=32), nullable=True, comment='指标类别: lab/vision/hearing/physique/other'),
        sa.Column('followup_type', sa.String(length=32), nullable=True, comment='随访类型: re_examination/specialist_referral/transfer_post/health_monitor'),
        sa.Column('followup_date', sa.Date(), nullable=True, comment='建议复查/处置日期（到期派生）'),
        sa.Column('status', sa.String(length=16), server_default='open', nullable=False, comment='随访状态: open/followed/closed/expired'),
        sa.Column('action_taken', sa.Text(), nullable=True, comment='处置记录'),
        sa.Column('responsible', sa.String(length=100), nullable=True, comment='责任人'),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True, comment='关闭时间'),
        sa.Column('source', sa.String(length=16), server_default='ai', nullable=False, comment='来源: ai/manual'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        *_base_columns(),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
        comment='职业健康异常随访（平台侧新增，闭环管理）'
    )

    # ── 9. 索引（部分唯一索引显式声明，autogenerate 不稳定必须手写）──
    # oh_persons
    op.create_index('uq_oh_persons_name_idcard', 'oh_persons', ['name', 'id_card_no'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false AND id_card_no IS NOT NULL'))
    op.create_index('uq_oh_persons_employee_no', 'oh_persons', ['employee_no'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false AND employee_no IS NOT NULL'))
    op.create_index('ix_oh_persons_feishu', 'oh_persons', ['feishu_record_id'], schema='safety')
    op.create_index('ix_oh_persons_dept', 'oh_persons', ['department'], schema='safety')
    # oh_health_exams
    op.create_index('uq_oh_health_exams_exam_no', 'oh_health_exams', ['exam_no'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false AND exam_no IS NOT NULL'))
    op.create_index('uq_oh_health_exams_feishu', 'oh_health_exams', ['feishu_record_id'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false AND feishu_record_id IS NOT NULL'))
    op.create_index('ix_oh_health_exams_person', 'oh_health_exams', ['person_id'], schema='safety')
    op.create_index('ix_oh_health_exams_status', 'oh_health_exams', ['status'], schema='safety')
    op.create_index('ix_oh_health_exams_exam_type', 'oh_health_exams', ['exam_type'], schema='safety')
    # oh_positions
    op.create_index('uq_oh_positions_dept_pos', 'oh_positions', ['department', 'position'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('ix_oh_positions_feishu', 'oh_positions', ['feishu_record_id'], schema='safety')
    # oh_hazard_factors
    op.create_index('uq_oh_hazard_factors_name', 'oh_hazard_factors', ['factor_name'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('ix_oh_hazard_factors_feishu', 'oh_hazard_factors', ['feishu_record_id'], schema='safety')
    # oh_exam_applications
    op.create_index('uq_oh_exam_applications_no', 'oh_exam_applications', ['application_no'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false AND application_no IS NOT NULL'))
    op.create_index('uq_oh_exam_applications_feishu', 'oh_exam_applications', ['feishu_record_id'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false AND feishu_record_id IS NOT NULL'))
    op.create_index('ix_oh_exam_applications_status', 'oh_exam_applications', ['apply_status'], schema='safety')
    # oh_followups
    op.create_index('uq_oh_followups_exam_indicator', 'oh_followups', ['exam_id', 'indicator_name'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false AND exam_id IS NOT NULL'))
    op.create_index('ix_oh_followups_person', 'oh_followups', ['person_id'], schema='safety')
    op.create_index('ix_oh_followups_status', 'oh_followups', ['status'], schema='safety')
    op.create_index('ix_oh_followups_due', 'oh_followups', ['followup_date'], schema='safety')


def downgrade() -> None:
    # 1. 删除 6 张新表（反向）
    op.drop_table('oh_followups', schema='safety')
    op.drop_table('oh_exam_applications', schema='safety')
    op.drop_table('oh_hazard_factors', schema='safety')
    op.drop_table('oh_positions', schema='safety')
    op.drop_table('oh_health_exams', schema='safety')
    op.drop_table('oh_persons', schema='safety')

    # 2. 重建旧 oh_health_exams（按 baseline 原始结构 + 部分唯一索引）
    op.create_table(
        'oh_health_exams',
        sa.Column('exam_no', sa.String(length=64), nullable=False, comment='体检编号'),
        sa.Column('employee_name', sa.String(length=100), nullable=False, comment='员工姓名'),
        sa.Column('employee_id', sa.String(length=64), nullable=True, comment='工号'),
        sa.Column('department', sa.String(length=100), nullable=True, comment='部门'),
        sa.Column('job_position', sa.String(length=100), nullable=True, comment='岗位'),
        sa.Column('exam_type', sa.String(length=32), nullable=False, comment='体检类型: pre_employment/periodic/post_employment/emergency'),
        sa.Column('status', sa.String(length=32), server_default='scheduled', nullable=False, comment='状态'),
        sa.Column('exam_agency', sa.String(length=255), nullable=True, comment='体检机构'),
        sa.Column('scheduled_date', sa.DateTime(timezone=True), nullable=True, comment='计划体检日期'),
        sa.Column('exam_date', sa.DateTime(timezone=True), nullable=True, comment='实际体检日期'),
        sa.Column('report_date', sa.DateTime(timezone=True), nullable=True, comment='报告日期'),
        sa.Column('hazard_factors', sa.JSON(), nullable=True, comment='关联的危害因素列表 [string]'),
        sa.Column('overall_conclusion', sa.String(length=32), nullable=True, comment='综合体检结论'),
        sa.Column('exam_items', sa.JSON(), nullable=True, comment='体检项目结果 JSON数组 [{item_name, category, result, reference_range, is_abnormal, remarks}]'),
        sa.Column('abnormality_records', sa.JSON(), nullable=True, comment='异常处置记录 JSON数组'),
        sa.Column('attachments', sa.JSON(), nullable=True, comment='附件列表'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        *_base_columns(),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
        comment='职业健康体检表'
    )
    op.create_index('uq_oh_health_exams_exam_no', 'oh_health_exams', ['exam_no'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false'))

    # 3. 重建旧 oh_hazard_monitors（按 baseline 原始结构 + 部分唯一索引）
    op.create_table(
        'oh_hazard_monitors',
        sa.Column('monitor_no', sa.String(length=64), nullable=False, comment='监测编号'),
        sa.Column('workplace', sa.String(length=255), nullable=False, comment='监测场所/车间'),
        sa.Column('location', sa.String(length=255), nullable=True, comment='具体监测点位'),
        sa.Column('equipment_info', sa.String(length=255), nullable=True, comment='关联设备/岗位'),
        sa.Column('detection_type', sa.String(length=32), nullable=False, comment='检测类型: regular/commissioned/evaluation/accident'),
        sa.Column('detection_date', sa.DateTime(timezone=True), nullable=True, comment='检测日期'),
        sa.Column('detection_agency', sa.String(length=255), nullable=True, comment='检测机构'),
        sa.Column('status', sa.String(length=32), server_default='draft', nullable=False, comment='状态'),
        sa.Column('inspector_name', sa.String(length=100), nullable=True, comment='检测人员'),
        sa.Column('verifier_name', sa.String(length=100), nullable=True, comment='验证人员'),
        sa.Column('detection_results', sa.JSON(), nullable=True, comment='检测结果 JSON数组 [{factor_name, factor_category, detection_value, unit, oel_limit, compliance_status, sampling_method, standard_ref}]'),
        sa.Column('abnormality_records', sa.JSON(), nullable=True, comment='异常处置记录 JSON数组 [{abnormality_desc, corrective_action, responsible_person, deadline, status, completed_at, remarks}]'),
        sa.Column('attachments', sa.JSON(), nullable=True, comment='附件列表 JSON数组 [{name, path}]'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        *_base_columns(),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
        comment='职业危害因素监测表'
    )
    op.create_index('uq_oh_hazard_monitors_monitor_no', 'oh_hazard_monitors', ['monitor_no'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false'))
