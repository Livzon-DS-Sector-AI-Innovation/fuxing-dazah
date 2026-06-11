"""维修工单 API 路由."""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import MissingGreenlet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import NO_VALUE

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.core.exceptions import AppException
from app.core.response import paginated_response, success_response
from app.modules.equipment import service
from app.modules.equipment.schemas import (
    MaterialConsumeRequest,
    MaterialConsumeResponse,
    WorkOrderAssign,
    WorkOrderComplete,
    WorkOrderCreate,
    WorkOrderResponse,
    WorkOrderStatistics,
    WorkOrderUpdate,
    WorkOrderVerify,
)


def _require_user(current_user: CurrentUser) -> uuid.UUID:
    """要求已认证用户，返回用户ID"""
    if not current_user:
        raise AppException(message="需要登录才能执行此操作", status_code=401)
    return current_user.id


def _to_response(wo) -> WorkOrderResponse:
    """将 ORM WorkOrder 转为响应对象，填充关联名称"""
    # 异步环境下写操作返回的对象可能未 eager load images 关系
    # 提前检测，直接跳过懒加载赋值，在 resp 上补充空列表
    has_images = True
    try:
        insp = sa_inspect(wo)
        if insp.attrs.images.loaded_value is NO_VALUE:
            has_images = False
    except MissingGreenlet:
        has_images = False

    resp = WorkOrderResponse.model_validate(wo)
    if not has_images:
        resp.images = []
    if wo.reporter:
        resp.reporter_name = wo.reporter.name
    if wo.assignee:
        resp.assignee_name = wo.assignee.name
    if wo.responsible_person:
        resp.responsible_person_name = wo.responsible_person.name
    if wo.equipment:
        resp.equipment_name = wo.equipment.name
        resp.equipment_no = wo.equipment.equipment_no
    if wo.fault_symptom:
        resp.symptom_name = wo.fault_symptom.name
    if wo.fault_cause:
        resp.cause_name = wo.fault_cause.name
    if wo.fault_action:
        resp.action_name = wo.fault_action.name
    return resp


router = APIRouter()


@router.post("/", summary="创建工单（报修）")
async def create_work_order(
    data: WorkOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    reporter_id = _require_user(current_user)
    wo = await service.create_work_order(db, data, reporter_id)
    return success_response(data=_to_response(wo))


@router.put("/{work_order_id}", summary="更新工单")
async def update_work_order(
    work_order_id: uuid.UUID,
    data: WorkOrderUpdate,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    wo = await service.update_work_order(db, work_order_id, data)
    return success_response(data=_to_response(wo))


@router.get("/", summary="工单列表")
async def list_work_orders(
    status: str | None = Query(None, description="工单状态"),
    equipment_id: uuid.UUID | None = Query(None, description="设备ID"),
    priority: str | None = Query(None, description="优先级"),
    order_type: str | None = Query(None, description="工单类型"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    work_orders, total = await service.get_work_orders(
        db, status=status, equipment_id=equipment_id,
        priority=priority, order_type=order_type,
        page=page, page_size=page_size,
    )
    return paginated_response(
        data=[_to_response(wo) for wo in work_orders],
        page=page, page_size=page_size, total=total,
    )


@router.get("/statistics", summary="工单统计")
async def get_work_order_statistics(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    stats = await service.get_work_order_statistics(db)
    return success_response(data=WorkOrderStatistics.model_validate(stats))


@router.get("/{work_order_id}", summary="工单详情")
async def get_work_order(
    work_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    wo = await service.get_work_order_by_id(db, work_order_id)
    return success_response(data=_to_response(wo))


@router.put("/{work_order_id}/assign", summary="指派维修人")
async def assign_work_order(
    work_order_id: uuid.UUID,
    data: WorkOrderAssign,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    wo = await service.assign_work_order(db, work_order_id, data.assignee_id)
    return success_response(data=_to_response(wo))


@router.put("/{work_order_id}/start", summary="开始维修")
async def start_work_order(
    work_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    wo = await service.start_work_order(db, work_order_id)
    return success_response(data=_to_response(wo))


@router.put("/{work_order_id}/complete", summary="提交完成")
async def complete_work_order(
    work_order_id: uuid.UUID,
    data: WorkOrderComplete,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    wo = await service.complete_work_order(db, work_order_id, data)
    return success_response(data=_to_response(wo))


@router.put("/{work_order_id}/verify", summary="验收")
async def verify_work_order(
    work_order_id: uuid.UUID,
    data: WorkOrderVerify,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    verifier_id = _require_user(current_user)
    wo = await service.verify_work_order(db, work_order_id, verifier_id, data)
    return success_response(data=_to_response(wo))


@router.put("/{work_order_id}/close", summary="关闭工单")
async def close_work_order(
    work_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    wo = await service.close_work_order(db, work_order_id)
    return success_response(data=_to_response(wo))


@router.post("/{work_order_id}/materials", summary="领料")
async def consume_materials(
    work_order_id: uuid.UUID,
    data: MaterialConsumeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    items = [item.model_dump() for item in data.items]
    transactions = await service.consume_materials(db, work_order_id, items)
    return success_response(
        data=[MaterialConsumeResponse.model_validate(t) for t in transactions]
    )


@router.get("/{work_order_id}/materials", summary="工单领料记录")
async def get_material_consumptions(
    work_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.modules.equipment import repository as repo

    transactions = await repo.get_material_consumptions(db, work_order_id)
    return success_response(
        data=[MaterialConsumeResponse.model_validate(t) for t in transactions]
    )
