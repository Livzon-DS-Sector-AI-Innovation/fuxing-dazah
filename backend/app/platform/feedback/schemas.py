"""系统反馈 API 契约。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.platform.feedback.models import FeedbackType


class FeedbackCreate(BaseModel):
    """提交反馈入参；page_path 由前端自动携带当前页面路径。"""

    # 先剥离首尾空白再做 max_length 校验，避免 2000 字正文外加换行被误判超长。
    model_config = ConfigDict(str_strip_whitespace=True)

    type: FeedbackType
    content: str = Field(max_length=2000)
    page_path: str | None = Field(default=None, max_length=512)

    @field_validator("content")
    @classmethod
    def _reject_blank_content(cls, value: str) -> str:
        if not value:
            raise ValueError("反馈内容不能为空")
        return value

    @field_validator("page_path")
    @classmethod
    def _empty_page_path_as_none(cls, value: str | None) -> str | None:
        return value or None


class FeedbackHandledIn(BaseModel):
    """标记「已处理」开关入参；False 表示取消标记。"""

    is_handled: bool


class FeedbackAttachmentOut(BaseModel):
    """反馈截图元数据；文件内容经 ``/content`` 端点代理读取。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    feedback_id: uuid.UUID
    file_name: str
    mime_type: str
    file_size: int
    sha256: str
    uploaded_by_name: str | None = None
    created_at: datetime | None = None


class FeedbackOut(BaseModel):
    """反馈条目（列表与详情共用），附带截图列表。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: FeedbackType
    content: str
    page_path: str | None = None
    submitter_id: uuid.UUID | None = None
    submitter_name: str
    submitter_department: str | None = None
    is_handled: bool
    handled_by_name: str | None = None
    handled_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    attachments: list[FeedbackAttachmentOut] = []


class FeedbackPendingCountOut(BaseModel):
    """待处理反馈数量（管理员按钮角标）。"""

    pending: int
