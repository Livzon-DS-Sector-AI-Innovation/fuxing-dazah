"""Safety request and response schemas."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ContractorStatus(str, Enum):
    """承包商状态枚举"""

    ACTIVE = "active"
    INACTIVE = "inactive"
    BLACKLISTED = "blacklisted"


CONTRACTOR_STATUS_OPTIONS = [
    {"value": ContractorStatus.ACTIVE, "label": "活跃", "color": "green"},
    {"value": ContractorStatus.INACTIVE, "label": "停用", "color": "default"},
    {"value": ContractorStatus.BLACKLISTED, "label": "黑名单", "color": "red"},
]


class QualificationTypeEnum(str, Enum):
    """承包资质类型枚举"""

    CONSTRUCTION = "construction"
    INSTALLATION = "installation"
    MAINTENANCE = "maintenance"
    CLEANING = "cleaning"
    SECURITY = "security"
    OTHER = "other"


QUALIFICATION_TYPE_OPTIONS = [
    {"value": QualificationTypeEnum.CONSTRUCTION, "label": "建筑施工"},
    {"value": QualificationTypeEnum.INSTALLATION, "label": "设备安装"},
    {"value": QualificationTypeEnum.MAINTENANCE, "label": "检维修"},
    {"value": QualificationTypeEnum.CLEANING, "label": "保洁"},
    {"value": QualificationTypeEnum.SECURITY, "label": "安保"},
    {"value": QualificationTypeEnum.OTHER, "label": "其他"},
]


class QualificationLevelEnum(str, Enum):
    """资质等级枚举"""

    GRADE_A = "grade_a"
    GRADE_B = "grade_b"
    GRADE_C = "grade_c"


QUALIFICATION_LEVEL_OPTIONS = [
    {"value": QualificationLevelEnum.GRADE_A, "label": "甲级/一级"},
    {"value": QualificationLevelEnum.GRADE_B, "label": "乙级/二级"},
    {"value": QualificationLevelEnum.GRADE_C, "label": "丙级/三级"},
]


class ContractorTrainingStatusEnum(str, Enum):
    """承包商培训状态枚举"""

    UNTRAINED = "untrained"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    EXPIRED = "expired"


CONTRACTOR_TRAINING_STATUS_OPTIONS = [
    {"value": ContractorTrainingStatusEnum.UNTRAINED, "label": "未培训", "color": "default"},
    {"value": ContractorTrainingStatusEnum.IN_PROGRESS, "label": "培训中", "color": "processing"},
    {"value": ContractorTrainingStatusEnum.PASSED, "label": "已通过", "color": "green"},
    {"value": ContractorTrainingStatusEnum.EXPIRED, "label": "已过期", "color": "red"},
]


class WorkRecordStatusEnum(str, Enum):
    """施工记录状态枚举"""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EVALUATED = "evaluated"


WORK_RECORD_STATUS_OPTIONS = [
    {"value": WorkRecordStatusEnum.IN_PROGRESS, "label": "施工中", "color": "processing"},
    {"value": WorkRecordStatusEnum.COMPLETED, "label": "已完成", "color": "green"},
    {"value": WorkRecordStatusEnum.EVALUATED, "label": "已评价", "color": "blue"},
]


# ── 承包商主表 ──


class ContractorBase(BaseModel):
    """承包商基础模式"""

    contractor_no: str = Field(..., max_length=64, description="承包商编号")
    company_name: str = Field(..., max_length=255, description="公司名称")
    legal_representative: str | None = Field(None, max_length=100, description="法定代表人")
    contact_person: str = Field(..., max_length=100, description="联系人")
    contact_phone: str | None = Field(None, max_length=20, description="联系电话")
    business_scope: str | None = Field(None, description="经营范围")
    qualification_type: QualificationTypeEnum = Field(QualificationTypeEnum.OTHER, description="资质类型")
    qualification_level: QualificationLevelEnum | None = Field(None, description="资质等级")
    qualification_cert_no: str | None = Field(None, max_length=100, description="资质证书编号")
    qualification_expiry: datetime | None = Field(None, description="资质有效期至")
    safety_license_no: str | None = Field(None, max_length=100, description="安全生产许可证编号")
    safety_license_expiry: datetime | None = Field(None, description="安全生产许可证有效期")
    insurance_info: str | None = Field(None, description="保险信息")
    insurance_expiry: datetime | None = Field(None, description="保险有效期至")
    safety_officer_name: str | None = Field(None, max_length=100, description="安全负责人")
    safety_officer_phone: str | None = Field(None, max_length=20, description="安全负责人电话")
    special_op_personnel: list | None = Field(None, description="特种作业人员列表")
    notes: str | None = Field(None, description="备注")


class ContractorCreate(ContractorBase):
    """创建承包商"""
    pass


class ContractorUpdate(BaseModel):
    """更新承包商"""

    contractor_no: str | None = Field(None, max_length=64, description="承包商编号")
    company_name: str | None = Field(None, max_length=255, description="公司名称")
    legal_representative: str | None = Field(None, max_length=100, description="法定代表人")
    contact_person: str | None = Field(None, max_length=100, description="联系人")
    contact_phone: str | None = Field(None, max_length=20, description="联系电话")
    business_scope: str | None = Field(None, description="经营范围")
    qualification_type: QualificationTypeEnum | None = Field(None, description="资质类型")
    qualification_level: QualificationLevelEnum | None = Field(None, description="资质等级")
    qualification_cert_no: str | None = Field(None, max_length=100, description="资质证书编号")
    qualification_expiry: datetime | None = Field(None, description="资质有效期至")
    safety_license_no: str | None = Field(None, max_length=100, description="安全生产许可证编号")
    safety_license_expiry: datetime | None = Field(None, description="安全生产许可证有效期")
    insurance_info: str | None = Field(None, description="保险信息")
    insurance_expiry: datetime | None = Field(None, description="保险有效期至")
    safety_officer_name: str | None = Field(None, max_length=100, description="安全负责人")
    safety_officer_phone: str | None = Field(None, max_length=20, description="安全负责人电话")
    special_op_personnel: list | None = Field(None, description="特种作业人员列表")
    training_status: ContractorTrainingStatusEnum | None = Field(None, description="培训状态")
    training_date: datetime | None = Field(None, description="最近培训日期")
    safety_performance_score: int | None = Field(None, ge=0, le=100, description="安全绩效评分")
    status: ContractorStatus | None = Field(None, description="状态")
    notes: str | None = Field(None, description="备注")


class ContractorResponse(ContractorBase):
    """承包商响应"""

    id: uuid.UUID
    training_status: str
    training_date: datetime | None = None
    safety_performance_score: int | None = None
    blacklisted: bool = False
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── 施工记录子表 ──


class ContractorWorkRecordBase(BaseModel):
    """施工记录基础模式"""

    work_content: str = Field(..., description="施工内容")
    work_location: str | None = Field(None, max_length=255, description="施工地点")
    planned_start: datetime = Field(..., description="计划开始时间")
    planned_end: datetime = Field(..., description="计划结束时间")
    actual_start: datetime | None = Field(None, description="实际开始时间")
    actual_end: datetime | None = Field(None, description="实际结束时间")
    permit_id: uuid.UUID | None = Field(None, description="关联特殊作业票ID")
    leading_person: str | None = Field(None, max_length=100, description="带班负责人")
    worker_count: int | None = Field(None, ge=0, description="施工人数")
    safety_briefing_done: bool = Field(False, description="安全交底确认")
    violations: list | None = Field(None, description="违章记录")
    evaluation: dict | None = Field(None, description="评价")
    notes: str | None = Field(None, description="备注")


class ContractorWorkRecordCreate(ContractorWorkRecordBase):
    """创建施工记录"""
    pass


class ContractorWorkRecordUpdate(BaseModel):
    """更新施工记录"""

    work_content: str | None = Field(None, description="施工内容")
    work_location: str | None = Field(None, max_length=255, description="施工地点")
    actual_start: datetime | None = Field(None, description="实际开始时间")
    actual_end: datetime | None = Field(None, description="实际结束时间")
    leading_person: str | None = Field(None, max_length=100, description="带班负责人")
    worker_count: int | None = Field(None, ge=0, description="施工人数")
    safety_briefing_done: bool | None = Field(None, description="安全交底确认")
    violations: list | None = Field(None, description="违章记录")
    status: WorkRecordStatusEnum | None = Field(None, description="状态")
    notes: str | None = Field(None, description="备注")


class ContractorWorkRecordResponse(ContractorWorkRecordBase):
    """施工记录响应"""

    id: uuid.UUID
    contractor_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EvaluateWorkRecordRequest(BaseModel):
    """评价施工记录请求"""

    score: int = Field(..., ge=0, le=100, description="评分")
    comments: str | None = Field(None, description="评价意见")
    evaluator: str | None = Field(None, max_length=100, description="评价人")


