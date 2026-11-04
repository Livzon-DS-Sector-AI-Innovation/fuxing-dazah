"""Safety API — chemical_inventory endpoints（危化品库存管理，单表固定行版）。

响应统一 ApiResponse；api.py 只做 HTTP 层（接参、注入、调 service、返回），不写 ORM/业务逻辑。
直读模式：列表/统计 meta 带 mode=direct + elapsed_ms（cert 口径）；手工补录端点明确拒绝
（补录只写平台库镜像，直读下不可见，cert renew 同口径）。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    ChemicalInventoryRecordCreate,
    ChemicalInventoryRecordResponse,
)
from app.modules.safety.service import ChemicalInventoryService

chemical_inventory_router = APIRouter()


@chemical_inventory_router.get(
    "/chemical-inventory/records", response_model=ApiResponse, summary="危化品库存台账（当前固定行）"
)
async def get_inventory_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    department: str | None = Query(None, description="部门"),
    material_name: str | None = Query(None, description="物料名称（模糊）"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    from app.modules.safety.service.chemical_inventory_direct import config

    direct = config.direct_enabled()
    t0 = time.perf_counter()
    service = ChemicalInventoryService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_records(
        skip, page_size, department=department, material_name=material_name,
    )
    meta: dict[str, object] = {"page": page, "page_size": page_size, "total": total}
    if direct:
        meta["mode"] = "direct"
        meta["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    return ApiResponse(
        data=[ChemicalInventoryRecordResponse.model_validate(i).model_dump() for i in items],
        meta=meta,
    )


@chemical_inventory_router.post(
    "/chemical-inventory/records", response_model=ApiResponse, summary="手工补录/更新库存记录"
)
async def create_inventory_record(
    data: ChemicalInventoryRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    from app.modules.safety.service.chemical_inventory_direct import config

    # 直读模式：补录只写平台库镜像（直读列表不可见），明确拒绝防止写进死数据（cert renew 口径）
    if config.direct_enabled():
        from app.modules.safety.service.chemical_inventory_direct.config import (
            receipt_direct_disabled_message,
        )

        return ApiResponse(code=400, message=receipt_direct_disabled_message())

    service = ChemicalInventoryService(db)
    item = await service.create_record(data.model_dump(exclude_none=True))
    return ApiResponse(data=ChemicalInventoryRecordResponse.model_validate(item).model_dump())


@chemical_inventory_router.post(
    "/chemical-inventory/scan", response_model=ApiResponse, summary="手动全量风险扫描（规则回填风险标记/风险说明）"
)
async def scan_inventory(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    service = ChemicalInventoryService(db)
    result = await service.run_full_scan()
    return ApiResponse(data=result)


@chemical_inventory_router.get(
    "/chemical-inventory/stats", response_model=ApiResponse, summary="当前库存风险统计"
)
async def get_inventory_stats(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    from app.modules.safety.service.chemical_inventory_direct import config

    direct = config.direct_enabled()
    t0 = time.perf_counter()
    service = ChemicalInventoryService(db)
    stats = await service.get_stats()
    meta: dict[str, object] | None = None
    if direct:
        meta = {"mode": "direct", "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
    return ApiResponse(data=stats, meta=meta)


# ── 趋势看板（daily 快照只读聚合，trend.py 业务层）──


@chemical_inventory_router.get(
    "/chemical-inventory/trend", response_model=ApiResponse, summary="库存趋势（daily 快照逐日聚合）"
)
async def get_inventory_trend(
    days: int = Query(30, ge=7, le=180, description="最近 N 个快照日"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    from app.modules.safety.chemical_inventory import trend

    t0 = time.perf_counter()
    points = await trend.daily_trend_points(db, days=days)
    return ApiResponse(
        data={"days": days, "points": points},
        meta={"days": days, "elapsed_ms": int((time.perf_counter() - t0) * 1000)},
    )


@chemical_inventory_router.get(
    "/chemical-inventory/changes", response_model=ApiResponse, summary="物料异动明细（目标日 vs 前一快照日）"
)
async def get_inventory_changes(
    date: str | None = Query(None, description="目标快照日 YYYY-MM-DD（默认最新 daily 快照日）"),
    limit: int = Query(100, ge=1, le=500, description="明细条数（按|变化量|降序截取）"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    from datetime import date as date_type

    from app.modules.safety.chemical_inventory import trend

    t0 = time.perf_counter()
    target = date_type.fromisoformat(date) if date else None
    result = await trend.material_changes(db, target_date=target, limit=limit)
    return ApiResponse(
        data=result,
        meta={"elapsed_ms": int((time.perf_counter() - t0) * 1000)},
    )


@chemical_inventory_router.get(
    "/chemical-inventory/changes/trend", response_model=ApiResponse, summary="异动趋势（逐日急剧上升/下降条数）"
)
async def get_inventory_change_trend(
    days: int = Query(30, ge=7, le=180, description="最近 N 个快照日"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    from app.modules.safety.chemical_inventory import trend

    t0 = time.perf_counter()
    points = await trend.change_trend(db, days=days)
    return ApiResponse(
        data={"days": days, "points": points},
        meta={"days": days, "elapsed_ms": int((time.perf_counter() - t0) * 1000)},
    )
