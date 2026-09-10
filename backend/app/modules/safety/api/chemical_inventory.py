"""Safety API — chemical_inventory endpoints（危化品库存管理，单表固定行版）。

响应统一 ApiResponse；api.py 只做 HTTP 层，不写 ORM/业务逻辑。
"""
from __future__ import annotations

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
    service = ChemicalInventoryService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_records(
        skip, page_size, department=department, material_name=material_name,
    )
    return ApiResponse(
        data=[ChemicalInventoryRecordResponse.model_validate(i).model_dump() for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@chemical_inventory_router.post(
    "/chemical-inventory/records", response_model=ApiResponse, summary="手工补录/更新库存记录"
)
async def create_inventory_record(
    data: ChemicalInventoryRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    service = ChemicalInventoryService(db)
    item = await service.create_record(data.model_dump(exclude_none=True))
    await db.commit()
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
    await db.commit()
    return ApiResponse(data=result)


@chemical_inventory_router.get(
    "/chemical-inventory/stats", response_model=ApiResponse, summary="当前库存风险统计"
)
async def get_inventory_stats(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    service = ChemicalInventoryService(db)
    stats = await service.get_stats()
    return ApiResponse(data=stats)
