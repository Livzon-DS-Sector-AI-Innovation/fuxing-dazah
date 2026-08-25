"""工具箱 ORM 模型：per-tool per-user 使用/配置授权。

权限语义（见 service.resolve_access_map）：
- 工具无任何授权行 → 使用默认开放（全员可用），配置仅超级管理员。
- 工具存在授权行 → 使用名单 ∪ 配置名单，配置仅配置名单。
- 超级管理员（permission:role:manage）恒放行。
- 存储上 can_use 仅记录使用名单成员；配置名单隐含使用由 service 读取时推导。
"""

import uuid

from sqlalchemy import Boolean, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class ToolGrant(BaseModel):
    """工具授权：某用户对某工具的使用/配置权限。"""

    __tablename__ = "tool_grants"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "tool_id", name="uq_toolbox_tool_grants_user_tool"
        ),
        Index("ix_toolbox_tool_grants_tool_id", "tool_id"),
        {"schema": "toolbox"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        comment="用户 ID (identity.users)",
    )
    tool_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="工具 ID（如 attendance-check）",
    )
    can_use: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        comment="是否在使用名单（配置名单成员的使用权由读取时推导）",
    )
    can_config: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        comment="是否可修改该工具配置",
    )
