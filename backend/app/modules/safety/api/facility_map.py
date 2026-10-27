"""Safety API — facility_map endpoints（3.x 平台关联 F2 + #2 AI 建议映射）。

GET /safety/facility-map/pins?date=：当日特殊作业票（平台 createTime 口径）
+ 今日消防/中控报警，经 location_district_map 匹配后按分区聚合 + 未映射
清单。分区轮廓不走接口（前端静态资产）；单路数据源失败降级进 errors。

#2 AI 建议映射（人工确认门，映射资产只增不改）：
- POST /facility-map/suggestions/scan：手动批处理（收集近 N 天未映射 →
  AI 建议 → 落 pending 建议行）
- GET  /facility-map/suggestions?status=：建议清单（缺省 pending）
- POST /facility-map/suggestions/{id}/confirm：确认 → 写映射表 ai_confirmed
- POST /facility-map/suggestions/{id}/ignore：忽略（下轮收集排除）
- POST /facility-map/suggestions/confirm-high：批量确认 high
"""

from __future__ import annotations

import logging
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.safety.schemas.facility_map import FacilityMapPinsOut
from app.modules.safety.service.facility_map import suggestions
from app.modules.safety.service.facility_map.service import (
    bj_today,
    open_pins_service,
)
from app.shared.schemas import ApiResponse

logger = logging.getLogger(__name__)

facility_map_router = APIRouter()


@facility_map_router.get(
    "/facility-map/pins",
    response_model=ApiResponse,
    summary="厂区风险分区当日分布 pins（作业票+报警按分区聚合）",
)
async def get_facility_map_pins(
    date: date_type | None = Query(None, description="YYYY-MM-DD，缺省北京时间今日"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    target = date or bj_today()
    payload = await open_pins_service(session=db).get_pins(target)
    return ApiResponse(
        data=FacilityMapPinsOut(**payload).model_dump(mode="json"),
        meta={"source": "tiji-platform+bitable", "mode": "direct"},
    )


class SuggestionScanRequest(BaseModel):
    days: int = Field(
        suggestions.DEFAULT_SCAN_DAYS, ge=1, le=90,
        description="收集窗口天数（默认 30）",
    )


@facility_map_router.post(
    "/facility-map/suggestions/scan",
    response_model=ApiResponse,
    summary="扫描未映射地点并生成 AI 分区建议（手动批处理，同文本不重复调）",
)
async def scan_suggestions(
    body: SuggestionScanRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    days = (body.days if body is not None else None) or suggestions.DEFAULT_SCAN_DAYS
    try:
        data = await suggestions.run_suggestion_scan(db, days=days)
    except Exception as exc:  # noqa: BLE001 AI/平台侧失败统一 502
        logger.exception("地点建议扫描失败（days=%s）", days)
        raise HTTPException(
            status_code=502, detail=f"建议扫描失败: {str(exc)[:200]}"
        ) from exc
    message = (
        f"扫描完成：近 {days} 天未映射 {data['unmapped_texts']} 个文本，"
        f"新增建议 {data['suggested']} 条"
        f"（AI 无法判断 {data['no_judgement']} 条）"
    )
    return ApiResponse(data=data, message=message)


@facility_map_router.get(
    "/facility-map/suggestions",
    response_model=ApiResponse,
    summary="分区建议清单（缺省 pending=确认页工作集）",
)
async def list_suggestions(
    status: str | None = Query(
        None, description="状态筛选：pending/confirmed/ignored（缺省 pending）"
    ),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    items = await suggestions.list_suggestions(db, status=status or "pending")
    return ApiResponse(data={"items": items, "total": len(items)})


@facility_map_router.post(
    "/facility-map/suggestions/confirm-high",
    response_model=ApiResponse,
    summary="批量确认全部 high 置信建议（写映射表）",
)
async def confirm_high_suggestions(
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    data = await suggestions.confirm_high_confidence(db)
    return ApiResponse(
        data=data, message=f"已确认 {data['confirmed']} 条（新建映射 {data['map_created']}）"
    )


@facility_map_router.post(
    "/facility-map/suggestions/{suggestion_id}/confirm",
    response_model=ApiResponse,
    summary="确认单条建议（写 location_district_map，source=ai_confirmed）",
)
async def confirm_suggestion(
    suggestion_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    try:
        data = await suggestions.confirm_suggestion(db, suggestion_id)
    except suggestions.SuggestionStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dist = f"（{data['dist_name']}）" if data["dist_name"] else ""
    return ApiResponse(
        data=data,
        message=(
            f"已确认并写入映射：{data['location_text']} → {data['dist_id']}{dist}"
            + ("" if data["map_created"] else "（映射已有，保留原行）")
        ),
    )


@facility_map_router.post(
    "/facility-map/suggestions/{suggestion_id}/ignore",
    response_model=ApiResponse,
    summary="忽略单条建议（下轮收集排除）",
)
async def ignore_suggestion(
    suggestion_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    try:
        data = await suggestions.ignore_suggestion(db, suggestion_id)
    except suggestions.SuggestionStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=data, message="已忽略")
