"""HR business ORM models live here."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
        comment="状态: 在职, 离职, 试用期, 待审批, 病假, 产假",
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
    certificates: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="证书"
    )
    concurrent_variety: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="兼任品种"
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

    # ─── 动态计算属性 ───

    @property
    def computed_age(self) -> int | None:
        """从出生日期动态计算年龄（优于飞书静态值；非法日期容错防 500）。"""
        if not self.birth_year:
            return self.age  # fallback to stored value
        today = date.today()
        age = today.year - self.birth_year
        if self.birth_month:
            if self.birth_day:
                try:
                    birthday_this_year = date(today.year, self.birth_month, self.birth_day)
                except ValueError:
                    # 数据源存在非法日期（如 2 月 30 日），退回按月份粗算或存值
                    if 1 <= self.birth_month <= 12 and today.month < self.birth_month:
                        age -= 1
                    return age
                if today < birthday_this_year:
                    age -= 1
            elif today.month < self.birth_month:
                age -= 1
        return age

    @property
    def computed_tenure(self) -> str | None:
        """从入职日期动态计算司龄。"""
        if not self.hire_date:
            return self.company_tenure  # fallback to stored value
        today = date.today()
        delta = today - self.hire_date
        years = delta.days // 365
        months = (delta.days % 365) // 30
        if years > 0:
            return f"{years}年{months}个月"
        return f"{months}个月"

    @property
    def computed_tenure_years(self) -> float | None:
        """司龄（年，数值格式，用于统计）。"""
        if not self.hire_date:
            return None
        delta = date.today() - self.hire_date
        return round(delta.days / 365.25, 1)


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

    # ─── 离职证明签署 ───
    cert_sign_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, comment="签署链接 token"
    )
    cert_sign_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="签署状态: pending / signed"
    )
    cert_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="签署时间"
    )
    cert_sign_image: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="手写签名图片 base64"
    )
    cert_sign_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="签署人确认姓名"
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
    location: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="培训地点"
    )
    assessment_method: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="考核方式"
    )
    notes: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="注意事项"
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
    period: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="任期（如 2023.03.01起）")


# ─── Department Training Personnel ───


class DeptTrainingPersonnel(BaseModel):
    """部门培训人员配置表：按部门配置培训管理员、部门负责人、一级培训师"""

    __tablename__ = "dept_training_personnel"
    __table_args__ = (
        Index("ix_dtp_department", "department"),
        Index("ix_dtp_display_department", "display_department"),
        {"schema": "hr"},
    )

    display_department: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="体现部门"
    )
    variety: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="品种"
    )
    department: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="部门"
    )
    training_admin: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="培训管理员（逗号分隔多人）"
    )
    department_head: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="部门负责人"
    )
    level1_trainer: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="一级培训师"
    )


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


class ExamPaper(BaseModel):
    """AI 生成/手工组卷的笔试试卷，可保存后复用下载。"""
    __tablename__ = "exam_papers"
    __table_args__ = (
        Index("ix_exam_papers_department", "department"),
        Index("ix_exam_papers_subject", "subject"),
        {"schema": "hr"},
    )

    subject: Mapped[str] = mapped_column(String(256), nullable=False, comment="培训内容/主题")
    department: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="培训部门")
    training_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="培训日期")
    training_method: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="培训方式")
    questions: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="题目快照")
    full_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    pass_line: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    choice_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    true_false_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    multi_choice_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    fill_blank_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="AI生成", server_default="AI生成")


# ─── QA 题库与问答考核 ───


class QuestionBank(BaseModel):
    """共享题库：问答考核从题库选题。"""

    __tablename__ = "question_bank"
    __table_args__ = (
        Index("ix_question_bank_file_no", "file_no"),
        {"schema": "hr"},
    )

    file_no: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="SOP/文件编号")
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="题目")
    answer: Mapped[str | None] = mapped_column(Text, nullable=True, comment="参考答案")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True, default=10, comment="分值")
    source: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="来源：手工录入 / docx_import")
    subject: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="关联主题（检索用）")
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="被引用次数")


class QaAssessment(BaseModel):
    """问答考核场次：含选题快照与受训人员名单。"""

    __tablename__ = "qa_assessments"
    __table_args__ = (
        Index("ix_qa_assessments_department", "department"),
        Index("ix_qa_assessments_subject", "subject"),
        {"schema": "hr"},
    )

    subject: Mapped[str] = mapped_column(String(256), nullable=False, comment="培训内容/主题")
    department: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="培训部门")
    training_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="培训日期")
    training_method: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="培训方式")
    assessment_method: Mapped[str | None] = mapped_column(String(32), nullable=True, default="问答", comment="考核方式：笔试/问答")
    trainer: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="培训师")
    questions: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="题目快照")
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="题目数量")
    full_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100", comment="满分")
    excellent_line: Mapped[int] = mapped_column(Integer, nullable=False, default=90, server_default="90", comment="优秀线")
    pass_line: Mapped[int] = mapped_column(Integer, nullable=False, default=80, server_default="80", comment="合格线")
    trainee_names: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="受训人员姓名列表")


class QaAssessmentScore(BaseModel):
    """问答考核成绩：按人一行，记录错题与总分。"""

    __tablename__ = "qa_assessment_scores"
    __table_args__ = (
        Index("ix_qa_scores_assessment", "assessment_id"),
        Index("ix_qa_scores_employee", "employee_name"),
        {"schema": "hr"},
    )

    assessment_id: Mapped[UUID] = mapped_column(nullable=False, comment="考核场次 ID")
    employee_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="员工姓名")
    employee_number: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="员工工号")
    wrong_questions: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="错题序号（1-indexed）")
    total_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100", comment="总分")
    grade: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="等级：优秀/合格/不合格")
    result_text: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="成绩说明")
    assessed_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="考核日期")


class SystemSetting(BaseModel):
    """系统设置键值表"""

    __tablename__ = "system_settings"
    __table_args__ = (
        UniqueConstraint("key"),
        Index("ix_system_settings_key", "key", unique=True),
        {"schema": "hr"},
    )

    key: Mapped[str] = mapped_column(String(64), nullable=False, comment="配置键")
    value: Mapped[str] = mapped_column(Text, server_default="", nullable=False, comment="配置值")
    description: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="说明")


class EmailLog(BaseModel):
    """邮件发送日志"""

    __tablename__ = "email_logs"
    __table_args__ = (
        Index("ix_email_logs_employee_id", "employee_id"),
        {"schema": "hr"},
    )

    email_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="类型: offer / departure_cert")
    employee_id: Mapped[UUID | None] = mapped_column(ForeignKey("hr.employees.id"), nullable=True, comment="员工ID")
    employee_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient: Mapped[str] = mapped_column(String(256), nullable=False, comment="收件邮箱")
    subject: Mapped[str] = mapped_column(String(256), nullable=False, comment="邮件主题")
    status: Mapped[str] = mapped_column(String(16), server_default="sent", nullable=False, comment="sent / failed")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")


class TransferRecord(BaseModel):
    """员工异动记录"""

    __tablename__ = "transfer_records"
    __table_args__ = (
        Index("ix_transfer_records_employee_id", "employee_id"),
        Index("ix_transfer_records_effective_date", "effective_date"),
        {"schema": "hr"},
    )

    employee_id: Mapped[UUID] = mapped_column(nullable=False, comment="员工ID")
    transfer_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default="调动", comment="调动/晋升/降职/转岗")
    from_department: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="原部门")
    to_department: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="新部门")
    from_position: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="原岗位")
    to_position: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="新岗位")
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, comment="生效日期")
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="原因")
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="审批单号")
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="备注")


# ─── 招聘：岗位需求 ───


class JobRequirement(BaseModel):
    __tablename__ = "job_requirements"
    __table_args__ = (
        Index("ix_job_req_department", "department"),
        Index("ix_job_req_status", "status"),
        {"schema": "hr"},
    )

    position_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="岗位名称")
    department: Mapped[str] = mapped_column(String(64), nullable=False, comment="需求部门")
    headcount: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1", comment="招聘人数")
    hired_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="已入职人数")
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True, comment="岗位要求描述")
    duties: Mapped[str | None] = mapped_column(Text, nullable=True, comment="岗位职责描述（胜任度报告「岗位要求回顾」用）")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="招聘中", server_default="招聘中", comment="招聘中/已关闭")
    urgency: Mapped[str | None] = mapped_column(String(8), nullable=True, comment="紧急程度")
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="招聘负责人")
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True, comment="期望到岗日期")


# ─── 招聘：候选人 ───


class Candidate(BaseModel):
    __tablename__ = "candidates"
    __table_args__ = (
        Index("ix_candidates_status", "status"),
        Index("ix_candidates_email", "email"),
        Index("ix_candidates_job_requirement_id", "job_requirement_id"),
        {"schema": "hr"},
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="姓名")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="手机")
    email: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="邮箱")
    position: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="应聘岗位")
    department: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="部门")
    gender: Mapped[str | None] = mapped_column(String(8), nullable=True, comment="性别")
    school: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="学校")
    education: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="学历")
    major: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="专业")
    graduation_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="毕业时间")
    resume_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="简历文件路径")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="待筛选", server_default="待筛选", comment="状态: 待筛选/已筛选/面试中/已面试/录用中/已录用/已拒绝")
    recommendation_level: Mapped[str | None] = mapped_column(String(8), nullable=True, comment="推荐等级")
    match_report: Mapped[str | None] = mapped_column(Text, nullable=True, comment="匹配报告")
    job_requirement_id: Mapped[UUID | None] = mapped_column(nullable=True, comment="关联岗位需求")
    candidate_type: Mapped[str] = mapped_column(String(8), nullable=False, default="职能", server_default="职能", comment="候选人类型: 普工/职能")
    offer_status: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="Offer状态: 已发送/已接受/已拒绝/已过期")
    offer_sent_at: Mapped[date | None] = mapped_column(Date, nullable=True, comment="Offer发送时间")
    source: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="简历来源")
    expected_salary: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="期望薪资")
    current_company: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="当前公司")
    work_years: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="工作年限")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ─── 招聘：候选人状态流转日志 ───


class CandidateStatusLog(BaseModel):
    __tablename__ = "candidate_status_logs"
    __table_args__ = (
        Index("ix_csl_candidate_id", "candidate_id"),
        {"schema": "hr"},
    )

    candidate_id: Mapped[UUID] = mapped_column(nullable=False, comment="候选人ID")
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="原状态")
    to_status: Mapped[str] = mapped_column(String(16), nullable=False, comment="新状态")
    operator: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="操作人")
    remark: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="备注")


# ─── 招聘：面试记录 ───


class Interview(BaseModel):
    __tablename__ = "interviews"
    __table_args__ = (
        Index("ix_interviews_candidate_id", "candidate_id"),
        Index("ix_interviews_interview_date", "interview_date"),
        {"schema": "hr"},
    )

    candidate_id: Mapped[UUID] = mapped_column(nullable=False, comment="候选人ID")
    job_requirement_id: Mapped[UUID | None] = mapped_column(nullable=True, comment="关联岗位需求")
    interview_type: Mapped[str] = mapped_column(String(16), nullable=False, default="初试", server_default="初试", comment="初试/复试/终试")
    interview_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="面试日期")
    interviewer: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="面试官")
    location: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="面试地点")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="待安排", server_default="待安排", comment="待安排/已安排/已完成/已取消")
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="面试逐字稿（HR粘贴）")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    calendar_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="飞书日历事件ID")


# ─── 招聘：候选人胜任度分析报告（多维度） ───


class CandidateAnalysisReport(BaseModel):
    """候选人胜任度多维分析报告：面试记录提交后 AI 自动生成。

    维度评分/星级/优势风险/综合评分/推荐等级/面试建议/培养建议。
    """

    __tablename__ = "candidate_analysis_reports"
    __table_args__ = (
        Index("ix_car_candidate", "candidate_id"),
        Index(
            "uq_car_interview", "interview_id", unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "hr"},
    )

    candidate_id: Mapped[UUID] = mapped_column(nullable=False, comment="候选人ID")
    job_requirement_id: Mapped[UUID | None] = mapped_column(nullable=True, comment="关联岗位需求")
    interview_id: Mapped[UUID] = mapped_column(nullable=False, comment="关联面试记录")
    dimensions: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="维度评估 [{name, score, star, assessment}]"
    )
    strengths: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="核心优势 [str]")
    risks: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="潜在风险 [str]")
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="综合胜任度评分（0-100）")
    recommend_level: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="推荐等级：强烈推荐/推荐/待定/不推荐"
    )
    interview_suggestions: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="面试建议 [str]（联动写入面试备注）"
    )
    training_suggestions: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="录用后培养建议 [str]"
    )
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="AI 原始输出")
    model_version: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="模型版本")
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="生成时间"
    )


# ─── 招聘：AI 面试评估 ───


class CandidateAiEvaluation(BaseModel):
    __tablename__ = "candidate_ai_evaluations"
    __table_args__ = (
        Index("ix_cae_candidate_id", "candidate_id"),
        Index("ix_cae_interview_id", "interview_id"),
        {"schema": "hr"},
    )

    candidate_id: Mapped[UUID] = mapped_column(nullable=False, comment="候选人ID")
    job_requirement_id: Mapped[UUID | None] = mapped_column(nullable=True, comment="关联岗位需求")
    interview_id: Mapped[UUID | None] = mapped_column(nullable=True, comment="关联面试记录")

    # 评分（1-10）
    jd_match_score: Mapped[float | None] = mapped_column(nullable=True, comment="JD匹配度")
    professional_score: Mapped[float | None] = mapped_column(nullable=True, comment="专业能力")
    communication_score: Mapped[float | None] = mapped_column(nullable=True, comment="沟通表达")
    learning_score: Mapped[float | None] = mapped_column(nullable=True, comment="学习能力")
    stability_score: Mapped[float | None] = mapped_column(nullable=True, comment="稳定性评估")
    overall_score: Mapped[float | None] = mapped_column(nullable=True, comment="综合评分")

    # 文本评价
    strengths: Mapped[str | None] = mapped_column(Text, nullable=True, comment="优势")
    weaknesses: Mapped[str | None] = mapped_column(Text, nullable=True, comment="不足")
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="AI综合评价")
    risk_flags: Mapped[str | None] = mapped_column(Text, nullable=True, comment="风险提示")

    # 快照与元数据
    jd_text_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True, comment="评估时JD快照")
    transcript_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True, comment="评估时逐字稿快照")
    model_version: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="AI模型版本")
    evaluated_at: Mapped[datetime | None] = mapped_column(nullable=True, comment="评估时间")


# ─── 招聘：候选人推送审核 ───


class CandidateReview(BaseModel):
    __tablename__ = "candidate_reviews"
    __table_args__ = (
        Index("ix_cr_candidate_id", "candidate_id"),
        Index("ix_cr_status", "status"),
        Index("ix_cr_reviewer", "reviewer"),
        {"schema": "hr"},
    )

    candidate_id: Mapped[UUID] = mapped_column(nullable=False, comment="候选人ID")
    job_requirement_id: Mapped[UUID | None] = mapped_column(nullable=True, comment="关联岗位需求")
    pushed_by: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="推送人(HR)")
    push_note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="推送备注")
    reviewer: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="审核人(用人部门负责人)")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="待审核", server_default="待审核", comment="待审核/已同意/已拒绝")
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="审核意见")
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True, comment="审核时间")
    review_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="部门审核", server_default="部门审核",
        comment="部门审核 / 入职审批"
    )


class OnboardingTask(BaseModel):
    """入职子任务（体检、资料审核、合同签署、入职培训）"""

    __tablename__ = "onboarding_tasks"
    __table_args__ = (
        Index("ix_onboarding_tasks_candidate", "candidate_id"),
        {"schema": "hr"},
    )

    candidate_id: Mapped[UUID] = mapped_column(nullable=False, comment="候选人ID")
    task_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="任务类型：体检/资料审核/合同签署/入职培训"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="待完成", server_default="待完成",
        comment="待完成 / 已完成"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序")
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True, comment="完成时间")
    completed_by: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="完成人")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ─── 员工自定义分类标签 ───


class EmployeeTag(BaseModel):
    """员工自定义分类标签，按创建人隔离数据。"""

    __tablename__ = "employee_tags"
    __table_args__ = (
        Index("ix_employee_tags_employee", "employee_number"),
        Index("ix_employee_tags_creator", "created_by"),
        {"schema": "hr"},
    )

    employee_number: Mapped[str] = mapped_column(String(32), nullable=False, comment="员工工号")
    tag_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="标签名称")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, comment="创建人")


class EmployeeClassification(BaseModel):
    """员工自定义分类清单：培训管理员维护，员工档案以「下拉选项」形式选择。"""

    __tablename__ = "employee_classifications"
    __table_args__ = (
        Index("ix_employee_classifications_creator", "created_by"),
        {"schema": "hr"},
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="分类名称")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, comment="创建人")


# ─── SOP 培训统筹总表 ───


class SopTrainingMaster(BaseModel):
    """SOP 培训统筹总表，记录发起部门、关联 SOP 和培训状态。"""

    __tablename__ = "sop_training_masters"
    __table_args__ = (
        Index("ix_sop_master_department", "department"),
        Index("ix_sop_master_status", "status"),
        {"schema": "hr"},
    )

    department: Mapped[str] = mapped_column(String(128), nullable=False, comment="发起部门")
    sop_ids: Mapped[str | None] = mapped_column(Text, nullable=True, comment="关联 SOP 条目 ID，JSON 数组")
    trainer: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="培训师")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="草稿", server_default="草稿", comment="草稿/已提交/已转训")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="创建人")
    related_departments: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="关联相关部门（二级表按此自动生成），JSON 数组"
    )


# ─── SOP 培训文件登记表 ───


class SopTrainingRecord(BaseModel):
    """SOP 培训文件登记表：每年一张登记表，每行一个培训文件（对齐 010版 Excel 模板）。"""

    __tablename__ = "sop_training_records"
    __table_args__ = (
        Index("ix_sop_record_year", "year"),
        Index("ix_sop_record_status", "status"),
        {"schema": "hr"},
    )

    year: Mapped[str] = mapped_column(String(4), nullable=False, comment="登记年份，如 2026")
    training_date: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="培训日期，如 01.05")
    file_name: Mapped[str] = mapped_column(String(512), nullable=False, comment="文件名称")
    file_no: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="文件编号（SOP编号，(CA)前缀=草案）")
    effective_date: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="生效日期，草案填——")
    method: Mapped[str | None] = mapped_column(String(4), nullable=True, comment="培训方式：R（按完成时间）/ T（按课时）")
    complete_time: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="R：培训完成时间；T：培训课时（日期+时段）")
    trainer: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="培训师（集中培训时填写）")
    trainees: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="培训对象，默认「X部门全体员工及相关部门培训师」")
    involved_departments: Mapped[str | None] = mapped_column(Text, nullable=True, comment="培训涉及部门，JSON 数组")
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="变更内容（新制订/修改原因）")
    color: Mapped[str] = mapped_column(String(8), nullable=False, default="新增", server_default="新增", comment="新增/撤销/修改")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="草稿", server_default="草稿", comment="草稿/已提交")
    initiator_department: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="发起部门（主办部门）")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="登记人")


# ─── SOP 培训二级表（按部门） ───


class SopTrainingEntry(BaseModel):
    """SOP 培训二级表：登记提交后按培训涉及部门自动生成的部门级培训记录。"""

    __tablename__ = "sop_training_entries"
    __table_args__ = (
        Index("ix_sop_entry_record", "record_id"),
        Index("ix_sop_entry_department", "department"),
        Index("ix_sop_entry_status", "status"),
        {"schema": "hr"},
    )

    record_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="登记表记录 ID"
    )
    department: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="培训部门"
    )
    trainer: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="培训师（转培训时自动带出当前培训师）")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="待转训", server_default="待转训", comment="待转训/已转训"
    )
    complete_time: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="该部门培训完成时间/课时")
    classification: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="自定义分类（对应部门员工标签）"
    )
    personnel: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="分类人员，JSON 数组：[{\"employee_number\":\"\",\"name\":\"\"}]"
    )
    transferred_by: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="转培训操作人")
    transferred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="转培训时间"
    )


# ─── HR 内部多部门数据范围 ───


class HrUserDepartmentAccess(BaseModel):
    """多部门访问权限：允许用户访问其本部门之外的其他部门数据。"""

    __tablename__ = "user_department_access"
    __table_args__ = (
        Index("ix_uda_user_id", "user_id"),
        Index("uq_uda_user_dept_active", "user_id", "department", unique=True,
              postgresql_where=text("is_deleted = false")),
        {"schema": "hr"},
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False, comment="用户ID (identity.users)")
    department: Mapped[str] = mapped_column(String(128), nullable=False, comment="可访问的部门名称")


# ─── 月度绩效考核 ───

class MonthlyPerformanceEvaluation(BaseModel):
    """月度部门负责人绩效考核主表"""

    __tablename__ = "monthly_performance_evaluations"
    __table_args__ = (
        Index("ix_mpe_department", "department"),
        Index("ix_mpe_month", "evaluation_month"),
        Index("ix_mpe_status", "status"),
        {"schema": "hr"},
    )

    department: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="部门名称"
    )
    department_head: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="部门负责人姓名"
    )
    evaluator_leader: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="分管领导姓名"
    )
    evaluation_month: Mapped[str] = mapped_column(
        String(7), nullable=False, comment="考核月份 YYYY-MM"
    )
    headcount: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="考核定编"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft",
        comment="状态: draft/self_submitted/leader_scored/confirmed",
    )
    self_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="自评提交时间"
    )
    leader_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="领导评分提交时间"
    )

    items: Mapped[list["PerformanceEvaluationItem"]] = relationship(
        "PerformanceEvaluationItem", back_populates="evaluation",
        lazy="select", cascade="all, delete-orphan",
    )


class PerformanceEvaluationItem(BaseModel):
    """绩效考核指标明细"""

    __tablename__ = "performance_evaluation_items"
    __table_args__ = (
        Index("ix_pei_evaluation_id", "evaluation_id"),
        {"schema": "hr"},
    )

    evaluation_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr.monthly_performance_evaluations.id"),
        nullable=False, comment="关联考核主表",
    )
    category: Mapped[str] = mapped_column(
        String(16), nullable=False, default="key_work",
        comment="类别: key_work/routine_work/reward_penalty",
    )
    indicator: Mapped[str] = mapped_column(
        String(256), nullable=False, comment="考核指标"
    )
    standard: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="考核标准/目标"
    )
    weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, comment="权重(%)"
    )
    self_score: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="自评分"
    )
    leader_score: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="分管领导评分"
    )
    final_score: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="核定分"
    )
    completion: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="完成情况"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="排序"
    )

    evaluation: Mapped["MonthlyPerformanceEvaluation"] = relationship(
        "MonthlyPerformanceEvaluation", back_populates="items",
    )


class PerformanceCategory(BaseModel):
    """考核项目配置（环保/安全/质量/人才/生产/综合 等）"""

    __tablename__ = "performance_categories"
    __table_args__ = (
        Index("ix_pc_is_active", "is_active"),
        {"schema": "hr"},
    )

    name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="考核项目名称"
    )
    weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, comment="权重(%)"
    )
    evaluator: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="项目负责人姓名"
    )
    is_active: Mapped[bool] = mapped_column(
        default=True, server_default="true", comment="是否启用"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="排序"
    )


class PerformanceDeptWeight(BaseModel):
    """各部门 × 考核项目 的权重配置"""

    __tablename__ = "performance_dept_weights"
    __table_args__ = (
        Index("ix_pdw_category_dept", "category_id", "department"),
        {"schema": "hr"},
    )

    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr.performance_categories.id"),
        nullable=False, comment="关联考核项目",
    )
    department: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="部门名称"
    )
    weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, comment="该部门此项目权重(%)"
    )


class PerformanceCategoryScore(BaseModel):
    """各部门 × 考核项目 × 月度 的评分明细（含部门独立权重）"""

    __tablename__ = "performance_category_scores"
    __table_args__ = (
        Index("ix_pcs_evaluation_id", "evaluation_id"),
        Index("ix_pcs_category_id", "category_id"),
        {"schema": "hr"},
    )

    evaluation_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr.monthly_performance_evaluations.id"),
        nullable=False, comment="关联考核主表",
    )
    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr.performance_categories.id"),
        nullable=False, comment="关联考核项目",
    )
    weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, comment="该部门此项目权重(%)"
    )
    score: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="分数(0-100)"
    )
    scored_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="评分人"
    )
    scored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="评分时间"
    )


# 职称评审子包模型注册到同一 metadata（alembic env 只 import 模块级 models）
from app.modules.hr.title_review import models as title_review_models  # noqa: E402, F401
