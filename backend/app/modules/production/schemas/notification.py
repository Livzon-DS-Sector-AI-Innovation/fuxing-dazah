"""通知配置 API 契约。"""

import uuid

from pydantic import BaseModel, Field


class NotificationConfigOut(BaseModel):
    """单个通知类型的配置（无配置行时按默认值返回）。"""

    notify_type: str
    name: str
    description: str
    is_enabled: bool
    extra_user_ids: list[uuid.UUID]


class NotificationConfigUpdateIn(BaseModel):
    """更新通知配置入参。"""

    is_enabled: bool = Field(description="是否启用该通知")
    extra_user_ids: list[uuid.UUID] = Field(
        default_factory=list, description="额外通知人员（发送时与功能接收人合并去重）",
    )
