"""HR business request and response schemas live here."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ─── Department Schemas ───

class DepartmentBase(BaseModel):
    name: str = Field(..., max_length=64, description="部门名称")
    code: str = Field(..., max_length=32, description="部门编码")
    description: str | None = Field(None, max_length=256, description="部门描述")


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    name: str | None = Field(None, max_length=64)
    code: str | None = Field(None, max_length=32)
    description: str | None = Field(None, max_length=256)


class DepartmentResponse(DepartmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ─── Team Schemas ───

class TeamBase(BaseModel):
    name: str = Field(..., max_length=64, description="班组名称")
    code: str | None = Field(None, max_length=32, description="班组编码")
    description: str | None = Field(None, max_length=256, description="班组描述")
    department_id: UUID = Field(..., description="所属部门ID")


class TeamCreate(TeamBase):
    pass


class TeamUpdate(BaseModel):
    name: str | None = Field(None, max_length=64)
    code: str | None = Field(None, max_length=32)
    description: str | None = Field(None, max_length=256)
    department_id: UUID | None = Field(None)


class TeamResponse(TeamBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    department: DepartmentResponse | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ─── Employee Schemas ───

class EmployeeBase(BaseModel):
    # Core
    employee_number: str = Field(..., max_length=32, description="工号")
    name: str = Field(..., max_length=64, description="姓名")
    domain_account: str | None = Field(None, max_length=64, description="域账号")

    # Department & job
    department: str = Field(..., max_length=64, description="体现部门")
    actual_department: str | None = Field(None, max_length=64, description="实际部门")
    team: str | None = Field(None, max_length=64, description="班组")
    position: str = Field(..., max_length=64, description="职位")
    job_category: str | None = Field(None, max_length=32, description="职类")
    level: str | None = Field(None, max_length=32, description="级别")
    concurrent_departments: str | None = Field(None, max_length=256, description="兼任部门")
    variety: str | None = Field(None, max_length=128, description="品种")

    # Qualifications
    qualifications: list[str] | None = Field(None, description="职称／职业资格")
    qualification_type: str | None = Field(None, max_length=32, description="职称类型")

    # Personal
    gender: str | None = Field(None, max_length=8, description="性别")
    native_place: str | None = Field(None, max_length=64, description="籍贯")
    political_status: str | None = Field(None, max_length=32, description="政治面貌")
    marital_status: str | None = Field(None, max_length=16, description="婚姻状况")
    household_type: str | None = Field(None, max_length=16, description="户籍类型")
    status_category: str | None = Field(None, max_length=32, description="统计类别")

    # Birth
    birth_year: int | None = Field(None, description="出生年份")
    birth_month: int | None = Field(None, description="出生月份")
    birth_day: int | None = Field(None, description="出生日期")
    age: int | None = Field(None, description="年龄")

    # Dates
    work_start_date: date | None = Field(None, description="参加工作时间")
    factory_entry_date: date | None = Field(None, description="进厂时间")
    livo_entry_date: date | None = Field(None, description="入丽珠时间")
    hire_date: date = Field(..., description="入职日期")
    graduation_date: date | None = Field(None, description="毕业时间")

    # Computed
    work_years: int | None = Field(None, description="工作年限")
    factory_tenure: str | None = Field(None, max_length=32, description="厂龄")
    company_tenure: str | None = Field(None, max_length=32, description="司龄")

    # Education
    education: str | None = Field(None, max_length=16, description="学历")
    classification: str | None = Field(None, max_length=16, description="分类")
    school: str | None = Field(None, max_length=128, description="毕业学校")
    major: str | None = Field(None, max_length=64, description="专业")

    # ID & address
    id_card: str | None = Field(None, max_length=18, description="身份证号")
    id_card_expiry: str | None = Field(None, max_length=32, description="身份证到期日")
    id_card_address: str | None = Field(None, description="身份证地址|家庭地址")
    current_address: str | None = Field(None, description="现住址")

    # Contract
    contract_type: str | None = Field(None, max_length=32, description="合同期限")
    contract_start_date: date | None = Field(None, description="合同开始日期")
    contract_end_date: date | None = Field(None, description="合同结束日期")
    contract_start_2: date | None = Field(None, description="第二次合同起点")
    contract_end_2: date | None = Field(None, description="第二次合同终止")
    contract_start_3: date | None = Field(None, description="第三次合同起点")
    contract_end_3: date | None = Field(None, description="第三次合同终止")
    contract_start_4: date | None = Field(None, description="第四次合同起点")
    contract_end_4: date | None = Field(None, description="第四次合同终止")

    # Contact
    phone: str | None = Field(None, max_length=32, description="手机")
    email: str | None = Field(None, max_length=128, description="邮箱")
    emergency_contact_name: str | None = Field(
        None, max_length=64, description="紧急联系人姓名"
    )
    emergency_contact_phone: str | None = Field(
        None, max_length=32, description="紧急联系人电话"
    )
    emergency_contact_relation: str | None = Field(
        None, max_length=32, description="紧急联系人关系"
    )

    # Banking & training
    bank_account: str | None = Field(None, max_length=32, description="银行卡号")
    training_id: str | None = Field(None, max_length=32, description="培训档案编号")

    # Other
    transfer_history: str | None = Field(None, description="异动记录")
    remarks: list[str] | None = Field(None, description="备注")
    status: str = Field("待审批", max_length=16, description="状态")
    sort_order: int | None = Field(None, description="Excel行序号")

    # Excel 扩展字段
    duty: str | None = Field(None, max_length=64, description="职务")
    dept_manager: str | None = Field(None, max_length=64, description="部门管理者")
    additional_manager: str | None = Field(None, max_length=64, description="额外管理者")
    report_grade: str | None = Field(None, max_length=32, description="报表用职级")
    dept_head_trainer: str | None = Field(None, max_length=64, description="部门负责人/一级培训师")
    safety_training_date: date | None = Field(None, description="入职安全培训日期")
    safety_training_score: str | None = Field(None, max_length=32, description="入职安全培训成绩")
    culture_training_date: date | None = Field(None, description="企业文化培训日期")
    gmp_training_date: date | None = Field(None, description="GMP基础培训时间")
    departure_date: date | None = Field(None, description="离职时间")


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    employee_number: str | None = Field(None, max_length=32)
    name: str | None = Field(None, max_length=64)
    domain_account: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=64)
    team: str | None = Field(None, max_length=64)
    position: str | None = Field(None, max_length=64)
    job_category: str | None = Field(None, max_length=32)
    level: str | None = Field(None, max_length=32)
    qualifications: list[str] | None = Field(None)
    qualification_type: str | None = Field(None, max_length=32)
    gender: str | None = Field(None, max_length=8)
    native_place: str | None = Field(None, max_length=64)
    political_status: str | None = Field(None, max_length=32)
    marital_status: str | None = Field(None, max_length=16)
    household_type: str | None = Field(None, max_length=16)
    status_category: str | None = Field(None, max_length=32)
    birth_year: int | None = Field(None)
    birth_month: int | None = Field(None)
    birth_day: int | None = Field(None)
    age: int | None = Field(None)
    work_start_date: date | None = Field(None)
    factory_entry_date: date | None = Field(None)
    livo_entry_date: date | None = Field(None)
    hire_date: date | None = Field(None)
    graduation_date: date | None = Field(None)
    work_years: int | None = Field(None)
    factory_tenure: str | None = Field(None, max_length=32)
    company_tenure: str | None = Field(None, max_length=32)
    education: str | None = Field(None, max_length=16)
    classification: str | None = Field(None, max_length=16)
    school: str | None = Field(None, max_length=128)
    major: str | None = Field(None, max_length=64)
    id_card: str | None = Field(None, max_length=18)
    id_card_expiry: str | None = Field(None, max_length=32)
    id_card_address: str | None = Field(None)
    current_address: str | None = Field(None)
    contract_type: str | None = Field(None, max_length=32)
    contract_start_date: date | None = Field(None)
    contract_end_date: date | None = Field(None)
    contract_start_2: date | None = Field(None)
    contract_end_2: date | None = Field(None)
    contract_start_3: date | None = Field(None)
    contract_end_3: date | None = Field(None)
    contract_start_4: date | None = Field(None)
    contract_end_4: date | None = Field(None)
    phone: str | None = Field(None, max_length=32)
    email: str | None = Field(None, max_length=128)
    emergency_contact_name: str | None = Field(None, max_length=64)
    emergency_contact_phone: str | None = Field(None, max_length=32)
    emergency_contact_relation: str | None = Field(None, max_length=32)
    bank_account: str | None = Field(None, max_length=32)
    training_id: str | None = Field(None, max_length=32)
    transfer_history: str | None = Field(None)
    remarks: list[str] | None = Field(None)
    status: str | None = Field(None, max_length=16)


class EmployeeResponse(EmployeeBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    feishu_open_id: str | None = None
    feishu_record_id: str | None = None
    feishu_synced_at: date | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TrainingSignInSheetInput(BaseModel):
    training_date: date = Field(..., description="培训日期")
    training_time_start: str | None = Field(None, max_length=32, description="培训开始时间")
    training_time_end: str | None = Field(None, max_length=32, description="培训结束时间")
    department: str = Field(..., max_length=64, description="受训部门")
    training_subject: str | None = Field(None, max_length=128, description="培训主题")
    topic: str = Field(..., max_length=256, description="培训题目或内容概要")
    instructor: str | None = Field(None, max_length=64, description="授课人")
    location: str | None = Field(None, max_length=128, description="培训地点")
    training_method: str | None = Field(None, max_length=32, description="培训方式")
    assessment_method: str | None = Field(None, max_length=32, description="考核方式")
    employee_names: list[str] = Field(default_factory=list, description="应出席受训人员姓名列表")
    employee_departments: dict[str, str] = Field(default_factory=dict, description="员工姓名→部门映射")
    remarks: str | None = Field(None, max_length=512, description="备注")


class TrainingNotificationInput(BaseModel):
    department: str = Field(..., max_length=64, description="主办部门")
    training_date: date = Field(..., description="培训日期")
    subject: str = Field(..., max_length=128, description="培训主题")
    training_time_start: str | None = Field(None, max_length=32, description="培训开始时间")
    training_time_end: str | None = Field(None, max_length=32, description="培训结束时间")
    location: str | None = Field(None, max_length=128, description="培训地点")
    trainer: str | None = Field(None, max_length=64, description="培训师")
    training_method: str | None = Field(None, max_length=32, description="培训方式")
    assessment_method: str | None = Field(None, max_length=32, description="考核方式")
    content: str | None = Field(None, max_length=512, description="培训内容")
    trainee_names: list[str] = Field(default_factory=list, description="培训人员姓名列表")
    issuer_department: str | None = Field(None, max_length=64, description="落款部门")
    issue_date: date | None = Field(None, description="落款日期")


class TrainingEvaluationInput(BaseModel):
    subject: str = Field(..., max_length=256, description="培训主题")
    training_date: date | None = Field(None, description="培训日期")
    training_time_start: str | None = Field(None, max_length=32)
    training_time_end: str | None = Field(None, max_length=32)
    duration_hours: float | None = Field(None, description="学时")
    training_method: str | None = Field(None, max_length=32)
    trainer: str | None = Field(None, max_length=64)
    trainee_names: list[str] = Field(default_factory=list)
    assessment_method: str | None = Field(None, max_length=32)


class OnboardingEvaluationInput(BaseModel):
    employee_name: str = Field(..., max_length=64, description="员工姓名")
    employee_number: str | None = Field(None, max_length=32, description="工作卡号")
    gender: str | None = Field(None, max_length=8, description="性别")
    department_position: str | None = Field(None, max_length=128, description="所在部门/岗位")
    hire_date: date | None = Field(None, description="入厂时间")
    training_period: str | None = Field(None, max_length=64, description="培训/考核期")
    regularization_date: date | None = Field(None, description="转正时间")
    assessment_contents: list[str] = Field(default_factory=list, description="上岗培训期内考核内容")
    comprehensive_comment: str | None = Field(None, max_length=1024, description="培训/考核期综合评语")
    is_qualified: bool | None = Field(None, description="是否同意上岗")
    assigned_position: str | None = Field(None, max_length=64, description="担任岗位")
    assessment_method: str | None = Field(None, max_length=32, description="考核方式")
    dept_manager_signature: str | None = Field(None, max_length=64, description="部门负责人签名")
    signature_date: date | None = Field(None, description="签名日期")
    remarks: str | None = Field(None, max_length=512, description="备注")
    dept_manager_agree: bool | None = Field(None, description="部门负责人是否同意")
    hr_manager_agree: bool | None = Field(None, description="人事行政部负责人是否同意")
    qa_manager_agree: bool | None = Field(None, description="质量管理负责人是否同意")
    dept_manager: str | None = Field(None, max_length=64, description="部门负责人")
    hr_manager: str | None = Field(None, max_length=64, description="人事行政部负责人")
    qa_manager: str | None = Field(None, max_length=64, description="质量管理负责人")
    approval_date: date | None = Field(None, description="审批日期")


# ─── OffboardingRecord Schemas ───

class OffboardingRecordBase(BaseModel):
    employee_id: UUID = Field(..., description="员工ID")
    offboarding_date: date = Field(..., description="离职日期")
    offboarding_type: str = Field("辞职", max_length=16, description="离职类型")
    reason: str | None = Field(None, max_length=512, description="离职原因")
    handover_status: str = Field("待交接", max_length=16, description="交接状态")
    notes: str | None = Field(None, max_length=512, description="备注")


class OffboardingRecordCreate(OffboardingRecordBase):
    pass


class OffboardingRecordUpdate(BaseModel):
    employee_id: UUID | None = Field(None)
    offboarding_date: date | None = Field(None)
    offboarding_type: str | None = Field(None, max_length=16)
    reason: str | None = Field(None, max_length=512)
    handover_status: str | None = Field(None, max_length=16)
    notes: str | None = Field(None, max_length=512)


class OffboardingRecordResponse(OffboardingRecordBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee: EmployeeResponse | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ─── DepartureRecord Schemas ───

class DepartureRecordBase(BaseModel):
    # Basic
    name: str = Field(..., max_length=64, description="姓名")
    department: str = Field(..., max_length=64, description="体现部门")
    team: str | None = Field(None, max_length=64, description="班组")
    position: str = Field(..., max_length=64, description="职位")
    job_category: str | None = Field(None, max_length=64, description="职类")
    gender: str | None = Field(None, max_length=8, description="性别")
    status_category: str | None = Field(None, max_length=64, description="统计类别")

    # Dates
    livo_entry_date: date | None = Field(None, description="入丽珠时间")
    factory_entry_date: date | None = Field(None, description="进厂时间")
    work_start_date: date | None = Field(None, description="参加工作时间")
    offboarding_date: date | None = Field(None, description="离职日期")
    company_tenure_at_leave: str | None = Field(None, max_length=64, description="离职时司龄")

    # Education
    education: str | None = Field(None, max_length=16, description="学历")
    school: str | None = Field(None, max_length=128, description="毕业学校")
    major: str | None = Field(None, max_length=64, description="专业")
    classification: str | None = Field(None, max_length=16, description="分类")

    # Personal
    id_card: str | None = Field(None, max_length=18, description="身份证号")
    native_place: str | None = Field(None, max_length=64, description="籍贯")
    household_type: str | None = Field(None, max_length=128, description="户籍类型")
    marital_status: str | None = Field(None, max_length=32, description="婚姻状况")
    political_status: str | None = Field(None, max_length=64, description="政治面貌")

    # Contact
    phone: str | None = Field(None, max_length=32, description="手机")
    emergency_contact_phone: str | None = Field(None, max_length=32, description="紧急联系人电话")
    emergency_contact_relation: str | None = Field(None, max_length=64, description="紧急联系人|关系")
    bank_account: str | None = Field(None, max_length=128, description="银行卡号")

    # Contract
    contract_type: str | None = Field(None, max_length=64, description="合同期限")

    # Work history
    transfer_history: str | None = Field(None, description="异动记录")

    # Offboarding specific
    offboarding_type: str = Field("辞职", max_length=16, description="离职类型")
    offboarding_reason: list[str] | None = Field(None, description="离职原因")
    offboarding_reason_2: list[str] | None = Field(None, description="离职原因2")
    offboarding_remarks: list[str] | None = Field(None, description="离职备注")

    # Other
    remarks: str | None = Field(None, description="备注")


class DepartureRecordCreate(DepartureRecordBase):
    pass


class DepartureRecordUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=64)
    team: str | None = Field(None, max_length=64)
    position: str | None = Field(None, max_length=64)
    job_category: str | None = Field(None, max_length=32)
    gender: str | None = Field(None, max_length=8)
    status_category: str | None = Field(None, max_length=32)
    livo_entry_date: date | None = Field(None)
    factory_entry_date: date | None = Field(None)
    work_start_date: date | None = Field(None)
    offboarding_date: date | None = Field(None)
    company_tenure_at_leave: str | None = Field(None, max_length=32)
    education: str | None = Field(None, max_length=16)
    school: str | None = Field(None, max_length=128)
    major: str | None = Field(None, max_length=64)
    classification: str | None = Field(None, max_length=16)
    id_card: str | None = Field(None, max_length=18)
    native_place: str | None = Field(None, max_length=64)
    household_type: str | None = Field(None, max_length=16)
    marital_status: str | None = Field(None, max_length=16)
    political_status: str | None = Field(None, max_length=32)
    phone: str | None = Field(None, max_length=32)
    emergency_contact_phone: str | None = Field(None, max_length=32)
    emergency_contact_relation: str | None = Field(None, max_length=32)
    bank_account: str | None = Field(None, max_length=32)
    contract_type: str | None = Field(None, max_length=32)
    transfer_history: str | None = Field(None)
    offboarding_type: str | None = Field(None, max_length=16)
    offboarding_reason: list[str] | None = Field(None)
    offboarding_reason_2: list[str] | None = Field(None)
    offboarding_remarks: list[str] | None = Field(None)
    remarks: list[str] | None = Field(None)


class DepartureRecordResponse(DepartureRecordBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    feishu_record_id: str | None = None
    feishu_synced_at: date | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ─── OnboardingRecord Schemas ───

class OnboardingRecordBase(BaseModel):
    # Core
    seq_number: int | None = Field(None, description="编号")
    employee_number: str = Field(..., max_length=32, description="工号")
    name: str = Field(..., max_length=64, description="姓名")
    domain_account: str | None = Field(None, max_length=64, description="域账号")

    # Department & job
    department: str = Field(..., max_length=64, description="体现部门")
    team: str | None = Field(None, max_length=64, description="班组")
    position: str = Field(..., max_length=64, description="岗位")
    job_category: str | None = Field(None, max_length=32, description="职类")
    status_category: str | None = Field(None, max_length=32, description="统计类别")

    # Employment status
    is_employed: str | None = Field(None, max_length=8, description="是否在职")

    # Dates
    hire_date: date = Field(..., description="入职时间")
    factory_entry_date: date | None = Field(None, description="进厂时间")
    livo_entry_date: date | None = Field(None, description="入丽珠时间")
    work_start_date: date | None = Field(None, description="参加工作时间")
    graduation_date: date | None = Field(None, description="毕业时间")
    birth_month: int | None = Field(None, description="出生月份")
    birth_day: int | None = Field(None, description="出生日期")

    # Contract
    contract_type: str | None = Field(None, max_length=32, description="合同期限")
    contract_start_date: date | None = Field(None, description="第一次合同起点")
    contract_end_date: date | None = Field(None, description="第一次合同终止")
    contract_start_2: date | None = Field(None, description="第二次合同起点")
    contract_end_2: date | None = Field(None, description="第二次合同终止")
    contract_start_3: date | None = Field(None, description="第三次合同起点")
    contract_end_3: date | None = Field(None, description="第三次合同终止")
    contract_start_4: date | None = Field(None, description="第四次合同起点")
    contract_end_4: date | None = Field(None, description="第四次合同终止")

    # Computed
    age: int | None = Field(None, description="年龄")
    work_years: int | None = Field(None, description="工作年限")
    factory_tenure: str | None = Field(None, max_length=32, description="厂龄")
    company_tenure: str | None = Field(None, max_length=32, description="司龄")
    hire_month: str | None = Field(None, max_length=16, description="入职月份")

    # Education
    school: str | None = Field(None, max_length=128, description="毕业学校")
    education: str | None = Field(None, max_length=16, description="学历")
    major: str | None = Field(None, max_length=64, description="专业")
    classification: str | None = Field(None, max_length=16, description="分类")

    # Personal
    id_card: str | None = Field(None, max_length=18, description="身份证号")
    id_card_expiry: str | None = Field(None, max_length=32, description="身份证到期日")
    id_card_address: str | None = Field(None, description="身份证地址|家庭地址")
    current_address: str | None = Field(None, description="现住址")
    marital_status: str | None = Field(None, max_length=16, description="婚姻状况")
    household_type: str | None = Field(None, max_length=16, description="户籍类型")
    political_status: str | None = Field(None, max_length=32, description="政治面貌")

    # Contact
    phone: str | None = Field(None, max_length=32, description="手机")
    email: str | None = Field(None, max_length=128, description="邮箱")
    emergency_contact_phone: str | None = Field(None, max_length=32, description="紧急联系人电话")
    emergency_contact_relation: str | None = Field(None, max_length=32, description="紧急联系人|关系")

    # Banking
    bank_account: str | None = Field(None, max_length=32, description="银行卡号")
    bank_account_location: str | None = Field(None, max_length=32, description="银行卡开户地")

    # Other
    training_id: str | None = Field(None, max_length=32, description="培训档案编号")
    transfer_history: str | None = Field(None, description="异动记录")
    remarks: list[str] | None = Field(None, description="备注")


class OnboardingRecordCreate(OnboardingRecordBase):
    pass


class OnboardingRecordUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    seq_number: int | None = Field(None)
    employee_number: str | None = Field(None, max_length=32)
    name: str | None = Field(None, max_length=64)
    domain_account: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=64)
    team: str | None = Field(None, max_length=64)
    position: str | None = Field(None, max_length=64)
    job_category: str | None = Field(None, max_length=32)
    status_category: str | None = Field(None, max_length=32)
    is_employed: str | None = Field(None, max_length=8)
    hire_date: date | None = Field(None)
    factory_entry_date: date | None = Field(None)
    livo_entry_date: date | None = Field(None)
    work_start_date: date | None = Field(None)
    graduation_date: date | None = Field(None)
    birth_month: int | None = Field(None)
    birth_day: int | None = Field(None)
    contract_type: str | None = Field(None, max_length=32)
    contract_start_date: date | None = Field(None)
    contract_end_date: date | None = Field(None)
    contract_start_2: date | None = Field(None)
    contract_end_2: date | None = Field(None)
    contract_start_3: date | None = Field(None)
    contract_end_3: date | None = Field(None)
    contract_start_4: date | None = Field(None)
    contract_end_4: date | None = Field(None)
    age: int | None = Field(None)
    work_years: int | None = Field(None)
    factory_tenure: str | None = Field(None, max_length=32)
    company_tenure: str | None = Field(None, max_length=32)
    hire_month: str | None = Field(None, max_length=16)
    school: str | None = Field(None, max_length=128)
    education: str | None = Field(None, max_length=16)
    major: str | None = Field(None, max_length=64)
    classification: str | None = Field(None, max_length=16)
    id_card: str | None = Field(None, max_length=18)
    id_card_expiry: str | None = Field(None, max_length=32)
    id_card_address: str | None = Field(None)
    current_address: str | None = Field(None)
    marital_status: str | None = Field(None, max_length=16)
    household_type: str | None = Field(None, max_length=16)
    political_status: str | None = Field(None, max_length=32)
    phone: str | None = Field(None, max_length=32)
    email: str | None = Field(None, max_length=128)
    emergency_contact_phone: str | None = Field(None, max_length=32)
    emergency_contact_relation: str | None = Field(None, max_length=32)
    bank_account: str | None = Field(None, max_length=32)
    bank_account_location: str | None = Field(None, max_length=32)
    training_id: str | None = Field(None, max_length=32)
    transfer_history: str | None = Field(None)
    remarks: list[str] | None = Field(None)


class OnboardingRecordResponse(OnboardingRecordBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    feishu_record_id: str | None = None
    feishu_synced_at: date | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ─── TrainingLedger Schemas ───

class TrainingLedgerBase(BaseModel):
    employee_number: str = Field(..., max_length=32, description="工号")
    training_date: date = Field(..., description="培训日期")
    training_subject: str = Field(..., max_length=256, description="培训课程/主题")
    training_method: str | None = Field(None, max_length=32, description="培训方式")
    duration_hours: float | None = Field(None, description="课时")
    location: str | None = Field(None, max_length=128, description="培训地点")
    trainer: str | None = Field(None, max_length=128, description="培训单位/培训师")
    assessment_result: str | None = Field(None, max_length=16, description="考核成绩")
    source_type: str = Field("manual", max_length=16, description="来源: manual, notification")
    source_id: str | None = Field(None, max_length=64, description="来源ID")
    remarks: str | None = Field(None, max_length=512, description="备注")


class TrainingLedgerCreate(TrainingLedgerBase):
    pass


class TrainingLedgerUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    employee_number: str | None = Field(None, max_length=32)
    training_date: date | None = Field(None)
    training_subject: str | None = Field(None, max_length=256)
    training_method: str | None = Field(None, max_length=32)
    duration_hours: float | None = Field(None)
    location: str | None = Field(None, max_length=128)
    trainer: str | None = Field(None, max_length=128)
    assessment_result: str | None = Field(None, max_length=16)
    source_type: str | None = Field(None, max_length=16)
    source_id: str | None = Field(None, max_length=64)
    remarks: str | None = Field(None, max_length=512)


class TrainingLedgerResponse(TrainingLedgerBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TrainingLedgerListResponse(BaseModel):
    code: int
    message: str
    data: list[TrainingLedgerResponse]
    meta: dict | None = None


# ─── TrainingLedgerPage Schemas ───

class TrainingLedgerPageCreate(BaseModel):
    employee_number: str = Field(..., max_length=32, description="工号")
    employee_name: str = Field(..., max_length=64, description="员工姓名")


class TrainingLedgerPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_number: str
    employee_name: str
    department: str | None = Field(None, max_length=64, description="所属部门")
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ─── AnnualTrainingPlan Schemas ───

class AnnualTrainingPlanBase(BaseModel):
    year: int = Field(..., description="年度")
    department: str = Field(..., max_length=64, description="体现部门")
    status: str = Field("草稿", max_length=16, description="状态: 草稿, 已确认")


class AnnualTrainingPlanCreate(AnnualTrainingPlanBase):
    pass


class AnnualTrainingPlanUpdate(BaseModel):
    year: int | None = Field(None, description="年度")
    department: str | None = Field(None, max_length=64, description="部门")
    status: str | None = Field(None, max_length=16, description="状态")


class AnnualTrainingPlanResponse(AnnualTrainingPlanBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AnnualTrainingPlanListResponse(BaseModel):
    code: int
    message: str
    data: list[AnnualTrainingPlanResponse]
    meta: dict | None = None


# ─── AnnualTrainingPlanItem Schemas ───

class AnnualTrainingPlanItemBase(BaseModel):
    month: str | None = Field(None, max_length=16, description="月份/季度")
    trainee_count: int | None = Field(None, description="培训人数")
    duration_hours: float | None = Field(None, description="课时")
    content_and_textbook: str | None = Field(None, max_length=512, description="培训内容及使用教材")
    target_audience: str | None = Field(None, max_length=256, description="培训对象")
    position_and_count: str | None = Field(None, max_length=256, description="参加岗位/参加人数")
    training_method: str | None = Field(None, max_length=64, description="培训方式")
    location: str | None = Field(None, max_length=128, description="培训地点")
    assessment_method: str | None = Field(None, max_length=64, description="考核方式")
    notes: str | None = Field(None, max_length=512, description="注意事项")
    training_hours: float | None = Field(None, description="培训学时")
    confirmer: str | None = Field(None, max_length=64, description="确认者")
    confirm_date: date | None = Field(None, description="确认日期")
    remarks: str | None = Field(None, max_length=512, description="备注")
    tracking_status: str | None = Field(None, max_length=16, description="培训跟踪: 完成, 未完成")
    sort_order: int = Field(0, description="排序")


class AnnualTrainingPlanItemCreate(AnnualTrainingPlanItemBase):
    pass


class AnnualTrainingPlanItemUpdate(BaseModel):
    month: str | None = Field(None, max_length=16)
    trainee_count: int | None = Field(None)
    duration_hours: float | None = Field(None)
    content_and_textbook: str | None = Field(None, max_length=512)
    target_audience: str | None = Field(None, max_length=256)
    position_and_count: str | None = Field(None, max_length=256)
    training_method: str | None = Field(None, max_length=64)
    training_hours: float | None = Field(None)
    confirmer: str | None = Field(None, max_length=64)
    confirm_date: date | None = Field(None)
    remarks: str | None = Field(None, max_length=512)
    tracking_status: str | None = Field(None, max_length=16)
    sort_order: int | None = Field(None)
    target_audience: str | None = Field(None, max_length=256)
    position_and_count: str | None = Field(None, max_length=256)
    training_method: str | None = Field(None, max_length=64)
    training_hours: float | None = Field(None)
    confirmer: str | None = Field(None, max_length=64)
    confirm_date: date | None = Field(None)
    remarks: str | None = Field(None, max_length=512)
    sort_order: int | None = Field(None)


class AnnualTrainingPlanItemResponse(AnnualTrainingPlanItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plan_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AnnualTrainingPlanItemBatchUpdate(BaseModel):
    items: list[AnnualTrainingPlanItemCreate] = Field(default_factory=list, description="明细列表")


# ─── Trainer Schemas ───

class TrainerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    department: str | None = None
    trainable_departments: str | None = None
    qualification_scope: str | None = None
    certification_date: date | None = None
    confirmation_date: date | None = None
    confirmation_reminder: date | None = None
    remarks: str | None = None
    is_primary_trainer: bool = False
    is_level1: str | None = None
    admin: str | None = None
    created_at: datetime | None = None


class TrainerListResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: list[TrainerResponse] = Field(default_factory=list)
    meta: dict | None = None


# ─── Department Training Personnel Schemas ───


class DeptTrainingPersonnelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_department: str
    variety: str | None = None
    department: str
    training_admin: str | None = None
    department_head: str | None = None
    level1_trainer: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DeptTrainingPersonnelCreate(BaseModel):
    display_department: str = Field(..., max_length=128)
    variety: str | None = Field(None, max_length=64)
    department: str = Field(..., max_length=128)
    training_admin: str | None = Field(None, max_length=256)
    department_head: str | None = Field(None, max_length=64)
    level1_trainer: str | None = Field(None, max_length=64)


class DeptTrainingPersonnelUpdate(BaseModel):
    display_department: str | None = Field(None, max_length=128)
    variety: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=128)
    training_admin: str | None = Field(None, max_length=256)
    department_head: str | None = Field(None, max_length=64)
    level1_trainer: str | None = Field(None, max_length=64)


class DeptTrainingPersonnelListResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: list[DeptTrainingPersonnelResponse] = Field(default_factory=list)
    meta: dict | None = None


# ─── SOP Catalog Schemas ───

class SopCatalogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    file_name: str
    sop_number: str | None = None
    category: str | None = None
    department: str | None = None
    position_name: str | None = None


class BatchScoreItem(BaseModel):
    id: UUID
    assessment_result: str | None = None


class BatchScoreUpdate(BaseModel):
    records: list[BatchScoreItem]


class SopCatalogListResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: list[SopCatalogResponse] = Field(default_factory=list)
    meta: dict | None = None
