"""法规采集监控 API（聚合契约③ + 本仓收录留痕，三态信封）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.safety.regulation_ingest.monitor import (
    build_monitor_envelope,
    build_run_detail,
)
from app.shared.schemas import ApiResponse

regulation_monitor_router = APIRouter()


@regulation_monitor_router.get(
    "/regulation-monitor",
    response_model=ApiResponse,
    summary="采集监控聚合（三态信封：源健康/最新法规/判定漏斗/运行历史）",
)
async def get_regulation_monitor(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> ApiResponse:
    """一次拉取聚合 ragplus 爬虫状态（契约③）与本仓收录留痕。

    三态：not_connected=未对接；live=正常；degraded=降级（errors 标注
    原因，不静默空结果）。
    """
    envelope = await build_monitor_envelope(db, page=page, page_size=page_size)
    return ApiResponse(code=200, data=envelope)


@regulation_monitor_router.get(
    "/regulation-monitor/runs/{run_id}",
    response_model=ApiResponse,
    summary="运行详情（ragplus 采集段快照 + 本仓收录段逐条管线）",
)
async def get_regulation_run_detail(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> ApiResponse:
    """按 ragplus run_id 拉取两段拼接的运行详情。"""
    detail = await build_run_detail(db, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="收录留痕中不存在该 run_id")
    return ApiResponse(code=200, data=detail)
