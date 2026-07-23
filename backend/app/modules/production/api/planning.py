"""计划中枢 API — 只做 HTTP 层。"""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.production.schemas.planning import (
    DemandAllocationCreate,
    DemandAllocationOut,
    DemandCreate,
    DemandOut,
    DemandUpdate,
    PlanItemCreate,
    PlanItemOut,
    PlanItemScheduleIn,
    PlanItemUpdate,
    PlanOrderCreate,
    PlanOrderOut,
    PlanOrderUpdate,
)
from app.modules.production.service import planning_service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()
_submit = require_permission("production:batch:submit")
_read = require_permission("production:batch:read")


# ══════════════════════════════
# Demand
# ══════════════════════════════

@router.get("/demands", summary="需求列表")
async def list_demands(
    status: str | None = None,
    priority: str | None = None,
    source_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await planning_service.list_demands_paged(
        db, status, priority, source_type, date_from, date_to, keyword, page, page_size,
    )
    return paginated_response(
        [DemandOut.model_validate(i).model_dump(mode="json") for i in items],
        page, page_size, total,
    )


@router.post("/demands", summary="创建需求")
async def create_demand(
    payload: DemandCreate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    demand = await planning_service.create_demand(db, payload, user)
    return success_response(DemandOut.model_validate(demand).model_dump(mode="json"))


@router.get("/demands/{demand_id}", summary="需求详情")
async def get_demand(
    demand_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await planning_service.get_demand_detail(db, demand_id)
    return success_response(detail.model_dump(mode="json"))


@router.put("/demands/{demand_id}", summary="更新需求")
async def update_demand(
    demand_id: uuid.UUID,
    payload: DemandUpdate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    demand = await planning_service.update_demand(db, demand_id, payload, user)
    return success_response(DemandOut.model_validate(demand).model_dump(mode="json"))


@router.delete("/demands/{demand_id}", summary="删除需求")
async def delete_demand(
    demand_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await planning_service.delete_demand(db, demand_id, user)
    return success_response({"id": str(demand_id)})


@router.post("/demands/{demand_id}/confirm", summary="确认需求")
async def confirm_demand(
    demand_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    demand = await planning_service.confirm_demand(db, demand_id, user)
    return success_response(DemandOut.model_validate(demand).model_dump(mode="json"))


@router.post("/demands/{demand_id}/cancel", summary="取消需求")
async def cancel_demand(
    demand_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    demand = await planning_service.cancel_demand(db, demand_id, user)
    return success_response(DemandOut.model_validate(demand).model_dump(mode="json"))


@router.get("/demands/{demand_id}/trace", summary="需求全链路追溯")
async def get_demand_trace(
    demand_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    trace = await planning_service.get_demand_trace(db, demand_id)
    return success_response(trace.model_dump(mode="json"))


# ══════════════════════════════
# PlanOrder
# ══════════════════════════════

@router.get("/plan-orders", summary="计划单列表")
async def list_plan_orders(
    status: str | None = None,
    priority: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await planning_service.list_plan_orders_paged(
        db, status, priority, date_from, date_to, keyword, page, page_size,
    )
    return paginated_response(
        [PlanOrderOut.model_validate(i).model_dump(mode="json") for i in items],
        page, page_size, total,
    )


@router.post("/plan-orders", summary="创建计划单")
async def create_plan_order(
    payload: PlanOrderCreate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    order = await planning_service.create_plan_order(db, payload, user)
    return success_response(PlanOrderOut.model_validate(order).model_dump(mode="json"))


@router.get("/plan-orders/{order_id}", summary="计划单详情")
async def get_plan_order(
    order_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await planning_service.get_plan_order_detail(db, order_id)
    return success_response(detail.model_dump(mode="json"))


@router.put("/plan-orders/{order_id}", summary="更新计划单")
async def update_plan_order(
    order_id: uuid.UUID,
    payload: PlanOrderUpdate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    order = await planning_service.update_plan_order(db, order_id, payload, user)
    return success_response(PlanOrderOut.model_validate(order).model_dump(mode="json"))


@router.delete("/plan-orders/{order_id}", summary="删除计划单")
async def delete_plan_order(
    order_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await planning_service.delete_plan_order(db, order_id, user)
    return success_response({"id": str(order_id)})


@router.post("/plan-orders/{order_id}/confirm", summary="确认计划单")
async def confirm_plan_order(
    order_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    order = await planning_service.confirm_plan_order(db, order_id, user)
    return success_response(PlanOrderOut.model_validate(order).model_dump(mode="json"))


@router.post("/plan-orders/{order_id}/release", summary="下达计划单")
async def release_plan_order(
    order_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    order = await planning_service.release_plan_order(db, order_id, user)
    return success_response(PlanOrderOut.model_validate(order).model_dump(mode="json"))


@router.post("/plan-orders/{order_id}/close", summary="关闭计划单")
async def close_plan_order(
    order_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    order = await planning_service.close_plan_order(db, order_id, user)
    return success_response(PlanOrderOut.model_validate(order).model_dump(mode="json"))


# ══════════════════════════════
# PlanItem
# ══════════════════════════════

@router.get("/plan-orders/{order_id}/items", summary="计划项列表")
async def list_plan_items(
    order_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items = await planning_service.list_plan_items(db, order_id)
    return success_response(
        [PlanItemOut.model_validate(i).model_dump(mode="json") for i in items]
    )


@router.post("/plan-orders/{order_id}/items", summary="添加计划项")
async def create_plan_item(
    order_id: uuid.UUID,
    payload: PlanItemCreate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    item = await planning_service.create_plan_item(db, order_id, payload, user)
    return success_response(PlanItemOut.model_validate(item).model_dump(mode="json"))


@router.put("/plan-items/{item_id}", summary="更新计划项")
async def update_plan_item(
    item_id: uuid.UUID,
    payload: PlanItemUpdate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    item = await planning_service.update_plan_item(db, item_id, payload, user)
    return success_response(PlanItemOut.model_validate(item).model_dump(mode="json"))


@router.delete("/plan-items/{item_id}", summary="删除计划项")
async def delete_plan_item(
    item_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await planning_service.delete_plan_item(db, item_id, user)
    return success_response({"id": str(item_id)})


@router.put("/plan-items/{item_id}/schedule", summary="排程计划项")
async def schedule_plan_item(
    item_id: uuid.UUID,
    payload: PlanItemScheduleIn,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    item, warnings = await planning_service.schedule_plan_item(db, item_id, payload, user)
    result = PlanItemOut.model_validate(item).model_dump(mode="json")
    if warnings:
        result["warnings"] = warnings
    return success_response(result)


@router.post("/plan-items/{item_id}/allocate", summary="分配计划项生成批次")
async def allocate_plan_item(
    item_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    item = await planning_service.allocate_plan_item(db, item_id, user)
    return success_response(PlanItemOut.model_validate(item).model_dump(mode="json"))


@router.get("/plan-items/schedule-view", summary="排程视图")
async def get_schedule_view(
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    equipment_id: str | None = None,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items = await planning_service.get_schedule_view(db, from_time, to_time, equipment_id)
    return success_response([i.model_dump(mode="json") for i in items])


# ══════════════════════════════
# Demand Allocations
# ══════════════════════════════

@router.get("/demands/{demand_id}/allocations", summary="需求关联计划项列表")
async def list_demand_allocations(
    demand_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await planning_service.get_demand_detail(db, demand_id)
    return success_response([a.model_dump(mode="json") for a in detail.allocations])


@router.post("/demands/{demand_id}/allocations", summary="关联需求到计划项")
async def create_demand_allocation(
    demand_id: uuid.UUID,
    payload: DemandAllocationCreate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    da = await planning_service.create_demand_allocation(db, demand_id, payload, user)
    return success_response(DemandAllocationOut.model_validate(da).model_dump(mode="json"))


@router.delete("/demand-allocations/{allocation_id}", summary="解除需求关联")
async def delete_demand_allocation(
    allocation_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await planning_service.delete_demand_allocation(db, allocation_id, user)
    return success_response({"id": str(allocation_id)})
