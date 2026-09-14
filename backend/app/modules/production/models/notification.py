"""生产模块通知配置 ORM（NotificationConfig）。"""

from sqlalchemy import Boolean, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class NotificationConfig(BaseModel):
    """通知配置：每类通知一行，启用开关 + 额外通知人员。

    无配置行的通知类型按默认（启用、无额外人员）处理，
    升级后行为与引入配置前完全一致。
    """

    __tablename__ = "notification_configs"
    __table_args__ = (
        Index(
            "uq_production_notification_configs",
            "notify_type",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "production"},
    )

    notify_type: Mapped[str] = mapped_column(String(50), comment="通知类型编码")
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), comment="是否启用",
    )
    # 额外通知人员 user_id 列表（字符串存储），发送时与功能接收人合并去重
    extra_recipients: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, comment="额外通知人员 user_id 列表",
    )
