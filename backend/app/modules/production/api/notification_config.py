"""通知配置 API — 只做 HTTP 层：入参、依赖注入、调 service、统一响应。"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.production.schemas.notification import (
    NotificationConfigOut,
    NotificationConfigUpdateIn,
)
from app.modules.production.service import notification_config_service
from app.platform.identity.deps import User
from app.platform.permission.deps import require_permission

router = APIRouter()

_manage = require_permission("production:notification:manage")


@router.get(
    "/notification-configs",
    response_model=list[NotificationConfigOut],
    summary="通知配置列表",
    description="全部通知类型的说明、启用状态与额外通知人员（无配置行按默认启用）。",
)
async def list_notification_configs(
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    configs = await notification_config_service.get_notification_configs(db)
    return success_response(
        [c.model_dump(mode="json") for c in configs],
    )


@router.put(
    "/notification-configs/{notify_type}",
    response_model=NotificationConfigOut,
    summary="更新通知配置",
    description="更新单个通知类型的启用开关与额外通知人员（发送时与功能接收人合并去重）。",
)
async def update_notification_config(
    notify_type: str,
    payload: NotificationConfigUpdateIn,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    config = await notification_config_service.update_notification_config(
        db, notify_type, payload, user,
    )
    return success_response(config.model_dump(mode="json"))
