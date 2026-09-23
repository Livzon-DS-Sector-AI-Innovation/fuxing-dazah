"""设备跨模块引用授权 API schema。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class EquipmentReferenceResponse(BaseModel):
    """对目标模块公开的最小设备摘要。"""

    id: uuid.UUID
    equipment_no: str
    name: str
    status: str | None = None
    is_active: bool = True
    source: str


class EquipmentReferenceGrantRequest(BaseModel):
    target_module: str = Field(..., min_length=1, max_length=64)
    equipment_ids: list[uuid.UUID] = Field(..., min_length=1)
    remark: str | None = Field(default=None, max_length=1000)


class EquipmentReferenceRevokeRequest(BaseModel):
    target_module: str = Field(..., min_length=1, max_length=64)
    equipment_ids: list[uuid.UUID] = Field(..., min_length=1)


class EquipmentReferenceGrantResponse(BaseModel):
    id: uuid.UUID
    equipment_id: uuid.UUID
    target_module: str
    source: str
    granted_by: uuid.UUID | None = None
    granted_at: datetime
    revoked_by: uuid.UUID | None = None
    revoked_at: datetime | None = None
    remark: str | None = None

    model_config = {"from_attributes": True}


class EquipmentReferenceTargetModuleResponse(BaseModel):
    code: str
    name: str
    path: str
    db_schema: str
    owner_hint: str
    description: str


__all__ = [
    "EquipmentReferenceGrantRequest",
    "EquipmentReferenceGrantResponse",
    "EquipmentReferenceResponse",
    "EquipmentReferenceRevokeRequest",
    "EquipmentReferenceTargetModuleResponse",
]
