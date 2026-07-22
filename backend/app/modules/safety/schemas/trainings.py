"""Safety request and response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.safety.schemas.enums import (
    TrainingLevel,
    TrainingMode,
    TrainingType,
)


class SafetyTrainingBase(BaseModel):
    """安全培训基础模式"""

    training_no: str = Field(..., max_length=64, description="培训编号")
    training_name: str = Field(..., max_length=255, description="培训名称")
    training_type: TrainingType = Field(TrainingType.ANNUAL, description="培训类型")
    training_mode: TrainingMode = Field(TrainingMode.OFFLINE, description="培训方式")
    training_level: TrainingLevel = Field(TrainingLevel.DEPT, description="培训级别")
    trainer: uuid.UUID | None = Field(None, description="培训讲师")
    trainer_name: str | None = Field(None, max_length=100, description="讲师姓名")
    training_date: datetime = Field(..., description="培训日期")
    duration_hours: float | None = Field(None, ge=0, description="培训时长(小时)")
    location: str | None = Field(None, max_length=255, description="培训地点")
    content: str | None = Field(None, description="培训内容")
    department: str | None = Field(None, max_length=100, description="培训部门")
    exam_passing_score: float | None = Field(60, ge=0, description="及格分数线")
    course_material_path: str | None = Field(None, max_length=500, description="课程资料路径")
    notes: str | None = Field(None, description="备注")


class SafetyTrainingCreate(SafetyTrainingBase):
    """创建安全培训"""

    pass


class SafetyTrainingUpdate(BaseModel):
    """更新安全培训"""

    training_no: str | None = Field(None, max_length=64, description="培训编号")
    training_name: str | None = Field(None, max_length=255, description="培训名称")
    training_type: TrainingType | None = Field(None, description="培训类型")
    training_mode: TrainingMode | None = Field(None, description="培训方式")
    trainer: uuid.UUID | None = Field(None, description="培训讲师")
    trainer_name: str | None = Field(None, max_length=100, description="讲师姓名")
    training_date: datetime | None = Field(None, description="培训日期")
    duration_hours: float | None = Field(None, ge=0, description="培训时长(小时)")
    location: str | None = Field(None, max_length=255, description="培训地点")
    content: str | None = Field(None, description="培训内容")
    department: str | None = Field(None, max_length=100, description="培训部门")
    status: str | None = Field(None, max_length=32, description="状态")
    notes: str | None = Field(None, description="备注")


class SafetyTrainingResponse(SafetyTrainingBase):
    """安全培训响应"""

    id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==================== 培训记录 Schemas ====================


class TrainingRecordBase(BaseModel):
    """培训记录基础模式"""

    employee_id: uuid.UUID | None = Field(None, description="员工ID")
    employee_name: str | None = Field(None, max_length=100, description="员工姓名")
    department: str | None = Field(None, max_length=100, description="部门")
    position: str | None = Field(None, max_length=100, description="岗位")
    attendance: bool = Field(True, description="是否出席")
    score: float | None = Field(None, ge=0, le=100, description="考核成绩")
    passed: bool | None = Field(None, description="是否合格")
    certificate_no: str | None = Field(None, max_length=100, description="证书编号")
    certificate_expiry: datetime | None = Field(None, description="证书有效期至")
    certificate_status: str | None = Field(None, max_length=32, description="证书状态")
    certificate_file_path: str | None = Field(None, max_length=500, description="证书文件路径")
    notes: str | None = Field(None, description="备注")


class TrainingRecordCreate(TrainingRecordBase):
    """创建培训记录"""

    training_id: uuid.UUID


class TrainingRecordUpdate(BaseModel):
    """更新培训记录"""

    employee_id: uuid.UUID | None = Field(None, description="员工ID")
    employee_name: str | None = Field(None, max_length=100, description="员工姓名")
    department: str | None = Field(None, max_length=100, description="部门")
    position: str | None = Field(None, max_length=100, description="岗位")
    attendance: bool | None = Field(None, description="是否出席")
    score: float | None = Field(None, ge=0, le=100, description="考核成绩")
    passed: bool | None = Field(None, description="是否合格")
    certificate_no: str | None = Field(None, max_length=100, description="证书编号")
    certificate_expiry: datetime | None = Field(None, description="证书有效期至")
    certificate_status: str | None = Field(None, max_length=32, description="证书状态")
    certificate_file_path: str | None = Field(None, max_length=500, description="证书文件路径")
    notes: str | None = Field(None, description="备注")


class TrainingRecordResponse(TrainingRecordBase):
    """培训记录响应"""

    id: uuid.UUID
    training_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


