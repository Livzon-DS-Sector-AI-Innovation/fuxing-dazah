"""QA 检索与操作日志端点。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.response import paginated_response
from app.modules.qa import service
from app.modules.qa.api._deps import (
    audit_read,
    qa_read,
)
from app.platform.identity.models import User

router = APIRouter()


@router.get("/search", summary="QA全局检索")
async def search_qa(
    user: User = Depends(qa_read),
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    include_history: bool = False,
    include_inactive: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=200),
) -> Any:
    items, total = await service.search(
        db,
        q,
        include_history=include_history,
        include_inactive=include_inactive,
        page=page,
        page_size=page_size,
    )
    return paginated_response(items, page, page_size, total)


@router.get("/operation-logs", summary="QA操作日志")
async def get_qa_operation_logs(
    user: User = Depends(audit_read),
    db: AsyncSession = Depends(get_db),
    resource_type: str | None = None,
    product_id: uuid.UUID | None = None,
    year: int | None = Query(default=None, ge=2000, le=2100),
    batch_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = Query(default=None, alias="user_id"),
    start_at: datetime | None = Query(default=None, alias="from"),
    end_at: datetime | None = Query(default=None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Any:
    """QA 操作日志：时间、操作人、变更前后值。

    读取范围由 service 的来源注册表决定（当前覆盖 PQR 数据录入，
    旧版杂项审计事件不在此列）。product_id/year/batch_id 是 PQR
    来源的定位字段过滤；每个来源域自带 extra 定位上下文。
    """
    if resource_type is not None and resource_type not in (
        service.OPERATION_LOG_SOURCES
    ):
        raise AppException(
            status_code=422, message=f"未知的操作日志来源类型：{resource_type}"
        )
    extra_equals: dict[str, str] = {}
    if product_id is not None:
        extra_equals["product_id"] = str(product_id)
    if year is not None:
        extra_equals["year"] = str(year)
    if batch_id is not None:
        extra_equals["batch_id"] = str(batch_id)
    logs, total = await service.list_operation_logs(
        db,
        page=page,
        page_size=page_size,
        resource_type=resource_type,
        extra_equals=extra_equals or None,
        user_id=actor_id,
        start_at=start_at,
        end_at=end_at,
    )
    from app.platform.identity.public_api import get_user_names

    # 审计表只存 user_id；列表要给人看，批量换成姓名（查不到的前端回退显示 ID）
    names = await get_user_names(db, [log.user_id for log in logs])
    data = [
        {
            "id": log.id,
            "created_at": log.created_at,
            "actor_id": log.user_id,
            "actor_name": names.get(log.user_id),
            "resource_type": log.resource_type,
            "source_label": service.OPERATION_LOG_SOURCES.get(
                str(log.resource_type), ("—", ())
            )[0],
            "action": log.action,
            "old_value": log.old_value,
            "new_value": log.new_value,
            "extra": log.extra or {},
        }
        for log in logs
    ]
    return paginated_response(data, page, page_size, total)
