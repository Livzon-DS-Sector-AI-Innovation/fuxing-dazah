"""QA 检索与审计日志端点。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
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


@router.get("/audit-logs", summary="QA审计日志")
async def get_qa_audit_logs(
    user: User = Depends(audit_read),
    db: AsyncSession = Depends(get_db),
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = Query(default=None, alias="user_id"),
    start_at: datetime | None = Query(default=None, alias="from"),
    end_at: datetime | None = Query(default=None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Any:
    logs, total = await service.list_audit_logs(
        db,
        page=page,
        page_size=page_size,
        user_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        start_at=start_at,
        end_at=end_at,
    )
    from app.platform.identity.public_api import get_user_names

    # 审计表只存 user_id；列表要给人看，批量换成姓名（查不到的前端回退显示 ID）
    names = await get_user_names(db, [log.user_id for log in logs])
    data = [
        {
            "id": log.id,
            "user_id": log.user_id,
            "actor_id": log.user_id,
            "actor_name": names.get(log.user_id),
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "object_type": log.resource_type,
            "object_id": log.resource_id,
            "old_value": log.old_value,
            "new_value": log.new_value,
            "before_value": log.old_value,
            "after_value": log.new_value,
            "extra": log.extra,
            "metadata": log.extra,
            "created_at": log.created_at,
            "file_sha256": (log.extra or {}).get("sha256") if log.extra else None,
        }
        for log in logs
    ]
    return paginated_response(data, page, page_size, total)
