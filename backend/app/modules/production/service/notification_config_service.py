"""生产模块通知配置服务：各类通知的启用开关与额外通知人员。"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.production.models import NotificationConfig
from app.modules.production.schemas.notification import (
    NotificationConfigOut,
    NotificationConfigUpdateIn,
)
from app.modules.production.service.reminder_service import NOTIFICATION_TYPES
from app.platform.identity.models import User


async def get_notification_configs(db: AsyncSession) -> list[NotificationConfigOut]:
    """全部通知类型及其配置（无配置行按默认：启用、无额外人员）。"""
    rows = await db.execute(
        select(NotificationConfig).where(
            NotificationConfig.is_deleted == False,  # noqa: E712
        )
    )
    configs = {r.notify_type: r for r in rows.scalars()}
    return [
        NotificationConfigOut(
            notify_type=code,
            name=type_def.name,
            description=type_def.description,
            is_enabled=configs[code].is_enabled if code in configs else True,
            extra_user_ids=(
                [uuid.UUID(uid) for uid in (configs[code].extra_recipients or [])]
                if code in configs
                else []
            ),
        )
        for code, type_def in NOTIFICATION_TYPES.items()
    ]


async def update_notification_config(
    db: AsyncSession,
    notify_type: str,
    payload: NotificationConfigUpdateIn,
    user: User | None,
) -> NotificationConfigOut:
    """更新单个通知类型的配置（upsert）。

    校验通知类型合法、额外人员均存在且未删除，避免配置出
    永远收不到通知的悬空 user_id。
    """
    type_def = NOTIFICATION_TYPES.get(notify_type)
    if type_def is None:
        raise NotFoundException("通知类型", notify_type)

    extra_ids = list(dict.fromkeys(payload.extra_user_ids))  # 去重保序
    if extra_ids:
        rows = await db.execute(
            select(User.id).where(
                User.id.in_(extra_ids),
                User.is_deleted == False,  # noqa: E712
            )
        )
        found = {row[0] for row in rows.all()}
        missing = sorted(str(uid) for uid in extra_ids if uid not in found)
        if missing:
            raise AppException(
                status_code=400,
                message=f"额外通知人员不存在或已删除：{', '.join(missing)}",
            )

    values = {
        "is_enabled": payload.is_enabled,
        "extra_recipients": [str(uid) for uid in extra_ids],
        "updated_by": user.id if user else None,
    }
    # 先 SELECT 再 INSERT 的 upsert 在并发首建时会撞部分唯一索引，
    # 用 ON CONFLICT 单语句原子完成（软删行不在索引内，删除后可重建）。
    await db.execute(
        pg_insert(NotificationConfig)
        .values(notify_type=notify_type, **values)
        .on_conflict_do_update(
            index_elements=["notify_type"],
            index_where=NotificationConfig.is_deleted == False,  # noqa: E712
            set_={**values, "updated_at": func.now()},
        )
    )

    return NotificationConfigOut(
        notify_type=notify_type,
        name=type_def.name,
        description=type_def.description,
        is_enabled=payload.is_enabled,
        extra_user_ids=extra_ids,
    )
