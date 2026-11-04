"""督办留痕查询 API（方向 C）。

GET /api/v1/safety/hazard-audit                    → 窗口内按隐患聚合列表
GET /api/v1/safety/hazard-audit/{record_id}/timeline → 单条隐患合并时间线

数据来自底座留痕表（audit_trail 旁挂；开关关时表空、接口照常返回空集）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response

logger = logging.getLogger(__name__)

hazard_audit_router = APIRouter()


@hazard_audit_router.get("/hazard-audit", summary="督办留痕·按隐患聚合")
async def list_hazard_audit(
    days: int = Query(30, ge=1, le=366, description="时间窗（天）"),
    keyword: str | None = Query(None, description="隐患编号/record_id 模糊"),
    db: AsyncSession = Depends(get_db),
):
    from app.modules.safety.service.hazard_direct.audit_query import (
        list_hazard_audit as query_list,
    )

    items = await query_list(db, days=days, keyword=keyword)
    return success_response(data=items, meta={"days": days, "total": len(items)})


@hazard_audit_router.get(
    "/hazard-audit/{record_id}/timeline", summary="督办留痕·单隐患时间线",
)
async def hazard_audit_timeline(
    record_id: str,
    days: int = Query(90, ge=1, le=366, description="时间窗（天）"),
    db: AsyncSession = Depends(get_db),
):
    from app.modules.safety.service.hazard_direct.audit_query import (
        hazard_audit_timeline as query_timeline,
    )

    events = await query_timeline(db, record_id, days=days)
    return success_response(data=events, meta={"record_id": record_id, "total": len(events)})
