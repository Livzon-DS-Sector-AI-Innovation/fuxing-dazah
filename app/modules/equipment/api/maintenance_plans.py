"""维护计划管理 API 路由."""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.equipment import service
from app.modules.equipment.deps import EquipmentAccessContext, require_equipment_access
from app.modules.equipment.models.equipment import EquipmentCategory
from app.modules.equipment.schemas import (
    MaintenancePlanCreate,
    MaintenancePlanResponse,
    MaintenancePlanUpdate,
)

router = APIRouter()


async def _fetch_category_names(
    db: AsyncSession,
    cat_ids: list[uuid.UUID],
) -> dict[str, str]:
    """批量查询分类名称，返回 {id_str: name} 映射。"""
    if not cat_ids:
        return {}
    result = await db.execute(
        select(EquipmentCategory.id, EquipmentCategory.name).where(
            EquipmentCategory.id.in_(cat_ids),
            EquipmentCategory.is_deleted == False,  # noqa: E712
        )
    )
    return {str(row[0]): row[1] for row in result.all()}


def _enrich_plan(plan, category_names: dict[str, str]) -> MaintenancePlanResponse:
    """填充维护计划响应的关联名称"""
    resp = MaintenancePlanResponse.model_validate(plan)
    if plan.equipment:
        resp.equipment_name = plan.equipment.name
        resp.equipment_no = plan.equipment.equipment_no
    if plan.executor:
        resp.executor_name = plan.executor.name
    if plan.category_id and str(plan.category_id) in category_names:
        resp.category_name = category_names[str(plan.category_id)]
    return resp


@router.post("/", summary="新增维护计划")
async def create_maintenance_plan(
    data: MaintenancePlanCreate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:create"),
    ),
) -> JSONResponse:
    plan = await service.create_maintenance_plan(db, data, ctx)
    cat_ids = [plan.category_id] if plan.category_id else []
    category_names = await _fetch_category_names(db, cat_ids)
    return success_response(data=_enrich_plan(plan, category_names))


@router.get("/", summary="维护计划列表")
async def list_maintenance_plans(
    equipment_id: uuid.UUID | None = Query(None, description="设备ID"),
    category_id: uuid.UUID | None = Query(None, description="分类ID"),
    status: str | None = Query(None, description="状态"),
    keyword: str | None = Query(None, description="关键词搜索"),
    plan_mode: str | None = Query(None, description="关联方式: equipment=按设备, category=按分类"),
    sort_field: str | None = Query(None, description="排序字段"),
    sort_order: str | None = Query(None, description="排序方向: ascend/descend"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:read"),
    ),
) -> JSONResponse:
    plans, total = await service.get_maintenance_plans(
        db, ctx=ctx, equipment_id=equipment_id, category_id=category_id,
        status=status, keyword=keyword, plan_mode=plan_mode,
        page=page, page_size=page_size,
        sort_field=sort_field, sort_order=sort_order,
    )
    # 批量查询分类名称
    cat_ids = [p.category_id for p in plans if p.category_id]
    category_names = await _fetch_category_names(db, cat_ids)

    return paginated_response(
        data=[_enrich_plan(p, category_names) for p in plans],
        page=page, page_size=page_size, total=total,
    )


@router.get("/overdue", summary="查询到期/逾期的维护计划")
async def get_overdue_plans(
    days: int = Query(0, ge=0, description="提前天数，0=仅逾期"),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:read"),
    ),
) -> JSONResponse:
    plans = await service.get_overdue_maintenance_plans(db, ctx, days)
    cat_ids = [p.category_id for p in plans if p.category_id]
    category_names = await _fetch_category_names(db, cat_ids)
    return success_response(
        data=[_enrich_plan(p, category_names) for p in plans]
    )


@router.get("/{plan_id}", summary="维护计划详情")
async def get_maintenance_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:read"),
    ),
) -> JSONResponse:
    plan = await service.get_maintenance_plan_by_id(db, plan_id)
    cat_ids = [plan.category_id] if plan.category_id else []
    category_names = await _fetch_category_names(db, cat_ids)
    return success_response(data=_enrich_plan(plan, category_names))


@router.put("/{plan_id}", summary="修改维护计划")
async def update_maintenance_plan(
    plan_id: uuid.UUID,
    data: MaintenancePlanUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:update"),
    ),
) -> JSONResponse:
    plan = await service.update_maintenance_plan(db, plan_id, data, ctx)
    cat_ids = [plan.category_id] if plan.category_id else []
    category_names = await _fetch_category_names(db, cat_ids)
    return success_response(data=_enrich_plan(plan, category_names))


@router.delete("/{plan_id}", summary="删除维护计划")
async def delete_maintenance_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:delete"),
    ),
) -> JSONResponse:
    await service.delete_maintenance_plan(db, plan_id, ctx)
    return success_response(message="删除成功")
