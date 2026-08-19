"""产线字典与用户-产线绑定 API 契约。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LineCreate(BaseModel):
    name: str = Field(max_length=200)
    remark: str | None = None


class LineUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    remark: str | None = None


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    remark: str | None
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class LineAssignmentCreate(BaseModel):
    user_id: uuid.UUID
    line_id: uuid.UUID


class LineAssignmentOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    line_id: uuid.UUID
    line_name: str | None = None
    created_at: datetime
