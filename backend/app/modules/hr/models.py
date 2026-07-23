"""HR business ORM models live here."""

from datetime import date
from uuid import UUID

from sqlalchemy import JSON, Date, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel


class HrDepartment(BaseModel):
    __tablename__ = "departments"
    __table_args__ = (
        Index("ix_departments_code", "code"),
        {"schema": "hr"},
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="部门名称")
    code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, comment="部门编码"
    )
    description: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="部门描述"
    )

    teams: Mapped[list["Team"]] = relationship(
        "Team", back_populates="department", lazy="select"
    )


class Team(BaseModel):
    __tablename__ = "teams"
    __table_args__ = (
        Index("ix_teams_department_id", "department_id"),
        Index("ix_teams_name", "name"),
        {"schema": "hr"},
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="班组名称")
    code: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="班组编码"
    )
    description: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="班组描述"
    )
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr.departments.id"), nullable=False, comment="所属部门ID"
    )

    department: Mapped["HrDepartment"] = relationship(
        "HrDepartment", back_populates="teams", lazy="select"
    )


class Employee(BaseModel):
    __tablename__ = "employees"
    __table_args__ = (
        Index("ix_employees_department", "department"),
        Index("ix_employees_status", "status"),
        Index("ix_employees_employee_number", "employee_number"),
        Index("ix_employees_feishu_record_id", "feishu_record_id"),
        {"schema": "hr"},
    )

    # ─── Core identifiers ───
    employee_number: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, comment="工号"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="姓名")
    domain_account: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="域账号"
    )

    # ─── Department & job ───
    department: Mapped[str] = mapped_column(String(64), nullable=False, comment="体现部门")
    actual_department: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="实际部门")
    team: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="班组")
    position: Mapped[str] = mapped_column(String(64), nullable=False, comment="职位")
    job_category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="职类"
    )
    level: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="级别")
    concurrent_departments: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="兼任部门"
    )

    # ─── Qualifications ───
    qualifications: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, comment="职称／职业资格（多选）"
    )
    qualification_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="职称类型"
    )

    # ─── Personal info ───
    gender: Mapped[str | None] = mapped_column(
        String(8), nullable=True, comment="性别"
    )
    native_place: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="籍贯"
    )
    political_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="政治面貌"
    )
    marital_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="婚姻状况"
    )
    household_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="户籍类型"
    )
    status_category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="统计类别"
    )

    # ─── Birth date (split as in Feishu) ───
    birth_year: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="出生年份"
    )
    birth_month: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="出生月份"
    )
    birth_day: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="出生日期"
    )
    age: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="年龄（飞书公式）"
    )

    # ─── Dates ───
    work_start_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="参加工作时间"
    )
    factory_entry_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="进厂时间"
    )
    livo_entry_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="入丽珠时间"
    )
    hire_date: Mapped[date] = mapped_column(Date, nullable=False, comment="入职日期")
    graduation_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="毕业时间"
    )

    # ─── Computed tenure (read-only mirrors of Feishu formulas) ───
    work_years: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="工作年限（飞书公式）"
    )
    factory_tenure: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="厂龄（飞书公式）"
    )
    company_tenure: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="司龄（飞书公式）"
    )

    # ─── Education ───
    education: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="学历"
    )
    classification: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="分类：全日制/非全日制"
    )
    school: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="毕业学校"
    )
    major: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="专业"
    )
    variety: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="品种"
    )

    # ─── ID & address ───
    id_card: Mapped[str | None] = mapped_column(
        String(18), nullable=True, comment="身份证号"
    )
    id_card_expiry: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="身份证到期日"
    )
    id_card_address: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="身份证地址|家庭地址"
    )
    current_address: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="现住址"
    )

    # ─── Contract ───
    contract_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="合同期限"
    )
    contract_start_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="合同开始日期（第一次）"
    )
    contract_end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="合同结束日期（第一次）"
    )
    contract_start_2: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第二次合同起点"
    )
    contract_end_2: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第二次合同终止"
    )
    contract_start_3: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第三次合同起点"
    )
    contract_end_3: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第三次合同终止"
    )
    contract_start_4: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第四次合同起点"
    )
    contract_end_4: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第四次合同终止"
    )

    # ─── Contact ───
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="手机")
    email: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="邮箱"
    )
    emergency_contact_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="紧急联系人姓名"
    )
    emergency_contact_phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="紧急联系人电话"
    )
    emergency_contact_relation: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="紧急联系人关系"
    )

    # ─── Banking & training ───
    bank_account: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="银行卡号"
    )
    training_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="培训档案编号"
    )

    # ─── Work history & remarks ───
    transfer_history: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="异动（含曾经工作部门、岗位)"
    )
    remarks: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, comment="备注（多选）"
    )

    # ─── Status ───
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="待审批",
        server_default="待审批",
        comment="状态: 在职, 离职, 试用期, 待审批",
    )

    # ─── Sort order ───
    sort_order: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Excel行序号"
    )

    # ─── Excel 导入扩展字段 ───
    duty: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="职务"
    )
    dept_manager: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="部门管理者"
    )
    additional_manager: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="额外管理者"
    )
    report_grade: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="报表用职级"
    )
    dept_head_trainer: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="部门负责人/一级培训师"
    )
    safety_training_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="入职安全培训日期"
    )
    safety_training_score: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="入职安全培训成绩"
    )
    culture_training_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="企业文化培训日期"
    )
    gmp_training_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="GMP基础培训时间"
    )
    departure_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="离职时间"
    )

    # ─── Feishu sync metadata ───
    feishu_open_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 open_id"
    )
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="飞书多维表格 record_id"
    )
    feishu_synced_at: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="上次飞书同步时间"
    )


class OffboardingRecord(BaseModel):
    __tablename__ = "offboarding_records"
    __table_args__ = (
        Index("ix_offboarding_employee_id", "employee_id"),
        Index("ix_offboarding_date", "offboarding_date"),
        {"schema": "hr"},
    )

    employee_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr.employees.id"),
        nullable=False,
        comment="员工ID",
    )
    offboarding_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="离职日期"
    )
    offboarding_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="辞职",
        server_default="辞职",
        comment="离职类型: 辞职, 辞退, 合同到期, 退休, 其他",
    )
    reason: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="离职原因"
    )
    handover_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="待交接",
        server_default="待交接",
        comment="交接状态: 待交接, 交接中, 已完成",
    )
    notes: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="备注"
    )

    employee: Mapped["Employee"] = relationship("Employee", lazy="select")


class DepartureRecord(BaseModel):
    __tablename__ = "departure_records"
    __table_args__ = (
        Index("ix_departure_department", "department"),
        Index("ix_departure_offboarding_date", "offboarding_date"),
        Index("ix_departure_feishu_record_id", "feishu_record_id"),
        {"schema": "hr"},
    )

    # ─── Basic info ───
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="姓名")
    department: Mapped[str] = mapped_column(String(64), nullable=False, comment="部门")
    team: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="班组")
    position: Mapped[str] = mapped_column(String(64), nullable=False, comment="职位")
    job_category: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="职类")
    gender: Mapped[str | None] = mapped_column(String(8), nullable=True, comment="性别")
    status_category: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="统计类别")

    # ─── Dates & tenure ───
    livo_entry_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="入丽珠时间")
    factory_entry_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="进厂时间")
    work_start_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="参加工作时间")
    offboarding_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="离职日期")
    company_tenure_at_leave: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="离职时司龄")

    # ─── Education ───
    education: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="学历")
    school: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="毕业学校")
    major: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="专业")
    classification: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="分类：全日制/非全日制")

    # ─── Personal ───
    id_card: Mapped[str | None] = mapped_column(String(18), nullable=True, comment="身份证号")
    native_place: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="籍贯")
    household_type: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="户籍类型")
    marital_status: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="婚姻状况")
    political_status: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="政治面貌")

    # ─── Contact ───
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="手机")
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="紧急联系人电话")
    emergency_contact_relation: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="紧急联系人|关系")
    bank_account: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="银行卡号")

    # ─── Contract ───
    contract_type: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="合同期限")

    # ─── Work history ───
    transfer_history: Mapped[str | None] = mapped_column(Text, nullable=True, comment="异动（含曾经工作部门、岗位)")

    # ─── Offboarding specific ───
    offboarding_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="辞职",
        server_default="辞职",
        comment="离职类型: 辞职, 辞退, 合同到期, 退休, 其他",
    )
    offboarding_reason: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, comment="离职原因（多选）"
    )
    offboarding_reason_2: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, comment="离职原因2（多选）"
    )
    offboarding_remarks: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, comment="离职备注（多选）"
    )

    # ─── Other ───
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # ─── Feishu sync metadata ───
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="飞书多维表格 record_id"
    )
    feishu_synced_at: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="上次飞书同步时间"
    )


class TrainingLedger(BaseModel):
    __tablename__ = "training_ledgers"
    __table_args__ = (
        Index("ix_training_ledgers_employee_number", "employee_number"),
        Index("ix_training_ledgers_training_date", "training_date"),
        {"schema": "hr"},
    )

    employee_number: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="工号"
    )
    training_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="培训日期"
    )
    training_subject: Mapped[str] = mapped_column(
        String(256), nullable=False, comment="培训课程/主题"
    )
    training_method: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="培训方式"
    )
    duration_hours: Mapped[float | None] = mapped_column(
        nullable=True, comment="课时"
    )
    location: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="培训地点"
    )
    trainer: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="培训单位/培训师"
    )
    assessment_result: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="考核成绩"
    )
    source_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="manual",
        server_default="manual",
        comment="来源: manual手动, notification培训通知关联",
    )
    source_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="来源ID"
    )
    remarks: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="备注"
    )


class TrainingLedgerPage(BaseModel):
    """培训台账专属页面配置（动态菜单持久化）"""

    __tablename__ = "training_ledger_pages"
    __table_args__ = (
        Index("ix_training_ledger_pages_employee_number", "employee_number", unique=True),
        {"schema": "hr"},
    )

    employee_number: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, comment="工号"
    )
    employee_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="员工姓名"
    )


class OnboardingRecord(BaseModel):
    __tablename__ = "onboarding_records"
    __table_args__ = (
        Index("ix_onboarding_employee_number", "employee_number"),
        Index("ix_onboarding_department", "department"),
        Index("ix_onboarding_hire_date", "hire_date"),
        Index("ix_onboarding_feishu_record_id", "feishu_record_id"),
        {"schema": "hr"},
    )

    # ─── Core identifiers ───
    seq_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="编号（飞书自动编号）"
    )
    employee_number: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="工号"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="姓名")
    domain_account: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="域账号"
    )

    # ─── Department & job ───
    department: Mapped[str] = mapped_column(String(64), nullable=False, comment="部门")
    team: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="班组")
    position: Mapped[str] = mapped_column(String(64), nullable=False, comment="岗位")
    job_category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="职类"
    )
    status_category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="统计类别"
    )

    # ─── Employment status ───
    is_employed: Mapped[str | None] = mapped_column(
        String(8), nullable=True, comment="是否在职: 是/否"
    )

    # ─── Dates ───
    hire_date: Mapped[date] = mapped_column(Date, nullable=False, comment="入职时间")
    factory_entry_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="进厂时间"
    )
    livo_entry_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="入丽珠时间"
    )
    work_start_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="参加工作时间"
    )
    graduation_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="毕业时间"
    )
    birth_month: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="出生月份"
    )
    birth_day: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="出生日期"
    )

    # ─── Contract ───
    contract_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="合同期限"
    )
    contract_start_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第一次合同起点"
    )
    contract_end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第一次合同终止"
    )
    contract_start_2: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第二次合同起点"
    )
    contract_end_2: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第二次合同终止"
    )
    contract_start_3: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第三次合同起点"
    )
    contract_end_3: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第三次合同终止"
    )
    contract_start_4: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第四次合同起点"
    )
    contract_end_4: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第四次合同终止"
    )

    # ─── Computed (read-only mirrors of Feishu formulas) ───
    age: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="年龄（飞书公式）"
    )
    work_years: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="工作年限（飞书公式）"
    )
    factory_tenure: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="厂龄（飞书公式）"
    )
    company_tenure: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="司龄（飞书公式）"
    )
    hire_month: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="入职月份（飞书公式）"
    )

    # ─── Education ───
    school: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="毕业学校"
    )
    education: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="学历"
    )
    major: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="专业"
    )
    classification: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="分类：全日制/非全日制"
    )

    # ─── Personal info ───
    id_card: Mapped[str | None] = mapped_column(
        String(18), nullable=True, comment="身份证号"
    )
    id_card_expiry: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="身份证到期日"
    )
    id_card_address: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="身份证地址|家庭地址"
    )
    current_address: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="现住址"
    )
    marital_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="婚姻状况"
    )
    household_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="户籍类型"
    )
    political_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="政治面貌"
    )

    # ─── Contact ───
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="手机")
    email: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="邮箱"
    )
    emergency_contact_phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="紧急联系人电话"
    )
    emergency_contact_relation: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="紧急联系人|关系"
    )

    # ─── Banking ───
    bank_account: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="银行卡号"
    )
    bank_account_location: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="银行卡开户地"
    )

    # ─── Other ───
    training_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="培训档案编号"
    )
    transfer_history: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="异动（含曾经工作部门、岗位)"
    )
    remarks: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, comment="备注（多选）"
    )

    # ─── Source ───
    source: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="来源: feishu/approval"
    )

    # ─── Feishu sync metadata ───
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="飞书多维表格 record_id"
    )
    feishu_synced_at: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="上次飞书同步时间"
    )


class AnnualTrainingPlan(BaseModel):
    __tablename__ = "annual_training_plans"
    __table_args__ = (
        Index("ix_annual_training_plans_year", "year"),
        Index("ix_annual_training_plans_department", "department"),
        {"schema": "hr"},
    )

    year: Mapped[int] = mapped_column(Integer, nullable=False, comment="年度")
    department: Mapped[str] = mapped_column(String(64), nullable=False, comment="部门")
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="草稿",
        server_default="草稿",
        comment="状态: 草稿, 已确认",
    )

    items: Mapped[list["AnnualTrainingPlanItem"]] = relationship(
        "AnnualTrainingPlanItem",
        back_populates="plan",
        lazy="select",
        cascade="all, delete-orphan",
    )


class AnnualTrainingPlanItem(BaseModel):
    __tablename__ = "annual_training_plan_items"
    __table_args__ = (
        Index("ix_annual_training_plan_items_plan_id", "plan_id"),
        {"schema": "hr"},
    )

    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr.annual_training_plans.id"),
        nullable=False,
        comment="年度计划ID",
    )
    month: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="月份")
    trainee_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="培训人数")
    duration_hours: Mapped[float | None] = mapped_column(nullable=True, comment="课时")
    content_and_textbook: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="培训内容及使用教材"
    )
    target_audience: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="培训对象"
    )
    position_and_count: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="参加岗位/参加人数"
    )
    training_method: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="培训方式"
    )
    training_hours: Mapped[float | None] = mapped_column(nullable=True, comment="培训学时")
    confirmer: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="确认者"
    )
    confirm_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="确认日期")
    remarks: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="备注"
    )
    tracking_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="培训跟踪: 完成, 未完成"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="排序",
    )

    plan: Mapped["AnnualTrainingPlan"] = relationship(
        "AnnualTrainingPlan", back_populates="items", lazy="select"
    )


# ─── Trainer ───

class HrTrainer(BaseModel):
    __tablename__ = "trainers"
    __table_args__ = (
        Index("ix_trainers_department", "department"),
        Index("ix_trainers_name", "name"),
        {"schema": "hr"},
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    department: Mapped[str | None] = mapped_column(String(64))
    trainable_departments: Mapped[str | None] = mapped_column(Text, comment="可培训部门")
    qualification_scope: Mapped[str | None] = mapped_column(Text, comment="资格范围")
    certification_date: Mapped[date | None] = mapped_column(Date)
    confirmation_date: Mapped[date | None] = mapped_column(Date)
    confirmation_reminder: Mapped[date | None] = mapped_column(Date)
    is_level1: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="是否一级培训师")
    admin: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="培训管理员")
    remarks: Mapped[str | None] = mapped_column(Text)
    is_primary_trainer: Mapped[bool] = mapped_column(default=False, server_default="false")
    admin: Mapped[str | None] = mapped_column(String(64))


# ─── SOP Catalog ───

class SopCatalog(BaseModel):
    __tablename__ = "sop_catalog"
    __table_args__ = (
        Index("ix_sop_catalog_department", "department"),
        Index("ix_sop_catalog_category", "category"),
        {"schema": "hr"},
    )

    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    sop_number: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(128))
    department: Mapped[str | None] = mapped_column(String(128))
    position_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="适用岗位")


class HrPosition(BaseModel):
    """部门职位表：按部门存储可选职位列表"""
    __tablename__ = "positions"
    __table_args__ = (
        Index("ix_positions_department", "department"),
        {"schema": "hr"},
    )

    department: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="部门名称"
    )
    name: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="职位名称"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="排序"
    )


class PositionTraining(BaseModel):
    """岗位培训内容关联表：岗位 → 培训类别 → SOP/文件"""
    __tablename__ = "position_trainings"
    __table_args__ = (
        Index("ix_pt_position", "position_name"),
        Index("ix_pt_department", "department"),
        {"schema": "hr"},
    )

    position_name: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="岗位名称"
    )
    department: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="所属部门"
    )
    variety: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="品种"
    )
    training_category: Mapped[str] = mapped_column(
        String(256), nullable=False, comment="培训类别"
    )
    trainer: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="培训师"
    )
    training_method: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="培训方式"
    )
    sop_number: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="SOP编号"
    )
    file_name: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="文件名称"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="排序"
    )


# ─── QA / Training Assessment Models ───

class TrainingAssessment(BaseModel):
    """培训考核场次（问答/实操）"""

    __tablename__ = "training_assessments"
    __table_args__ = (
        Index("ix_training_assessments_department", "department"),
        Index("ix_training_assessments_training_date", "training_date"),
        {"schema": "hr"},
    )

    subject: Mapped[str] = mapped_column(
        String(256), nullable=False, comment="培训内容/主题"
    )
    department: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="培训部门/对象"
    )
    training_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="培训日期"
    )
    training_method: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="培训方式"
    )
    assessment_method: Mapped[str] = mapped_column(
        String(32), nullable=False, default="问答", server_default="问答", comment="考核方式"
    )
    trainer: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="培训师"
    )
    questions: Mapped[dict | list | None] = mapped_column(
        JSON, nullable=True, comment="题目快照 [{file_no,question,answer,score}]"
    )
    question_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10", comment="题目数量"
    )
    full_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100", comment="满分"
    )
    excellent_line: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90, server_default="90", comment="优秀线"
    )
    pass_line: Mapped[int] = mapped_column(
        Integer, nullable=False, default=80, server_default="80", comment="合格线"
    )


class TrainingAssessmentScore(BaseModel):
    """培训考核成绩"""

    __tablename__ = "training_assessment_scores"
    __table_args__ = (
        Index("ix_training_assessment_scores_assessment_id", "assessment_id"),
        Index("ix_training_assessment_scores_employee_number", "employee_number"),
        {"schema": "hr"},
    )

    assessment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="考核场次ID（逻辑关联，无外键）"
    )
    employee_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="姓名"
    )
    employee_number: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="工号"
    )
    wrong_questions: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="错题序号列表，空为全对"
    )
    total_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="总分"
    )
    grade: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="等级：优/合格/不合格"
    )
    result_text: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="得分情况文字"
    )
    assessed_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="考核日期"
    )
