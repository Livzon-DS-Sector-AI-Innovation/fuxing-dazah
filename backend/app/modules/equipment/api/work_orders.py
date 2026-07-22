"""维修工单 API 路由."""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.equipment import service
from app.modules.equipment.deps import EquipmentAccessContext, require_equipment_access
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

logger = logging.getLogger(__name__)


async def _notify_start(wo) -> None:
    """网页点击开始执行时，飞书通知维修人。非关键路径。"""
    try:
        if not wo.assignee:
            return
        from app.platform.integrations.feishu.notification import send_user_card

        user = wo.assignee
        if not user.feishu_user_id:
            return

        eq_name = wo.equipment.name if wo.equipment else ""
        title = f"【设备】🔧 维修已开始 — {wo.work_order_no}"
        lines = [
            f"**工单编号：**{wo.work_order_no}",
            f"**关联设备：**{eq_name}",
            f"**工单类型：**{wo.order_type}",
            f"**优先级：**{wo.priority}",
            "",
            "维修已开始，请尽快完成维修并提交。",
        ]
        content = "\n".join(lines)
        await send_user_card(
            open_id=user.feishu_user_id,
            title=title,
            content=content,
            receive_id_type="user_id",
        )
    except Exception:
        logger.exception("开始维修通知异常: %s", wo.work_order_no)


def _to_response(wo) -> WorkOrderResponse:
    """将 ORM WorkOrder 转为响应对象，填充关联名称。"""
    resp = WorkOrderResponse.model_validate(wo)
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
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:work_order:create"),
    ),
) -> JSONResponse:
    wo = await service.create_work_order(db, data, ctx)
    return success_response(data=_to_response(wo))


@router.put("/{work_order_id}", summary="更新工单")
async def update_work_order(
    work_order_id: uuid.UUID,
    data: WorkOrderUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:work_order:update"),
    ),
) -> JSONResponse:
    wo = await service.update_work_order(db, work_order_id, data, ctx)
    return success_response(data=_to_response(wo))


@router.get("/", summary="工单列表")
async def list_work_orders(
    status: str | None = Query(None, description="工单状态"),
    exclude_status: str | None = Query(None, description="排除状态"),
    equipment_id: uuid.UUID | None = Query(None, description="设备ID"),
    priority: str | None = Query(None, description="优先级"),
    order_type: str | None = Query(None, description="工单类型"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:work_order:read"),
    ),
) -> JSONResponse:
    work_orders, total = await service.get_work_orders(
        db, ctx, status=status, exclude_status=exclude_status,
        equipment_id=equipment_id,
        priority=priority, order_type=order_type,
        page=page, page_size=page_size,
    )
    return paginated_response(
        data=[_to_response(wo) for wo in work_orders],
        page=page, page_size=page_size, total=total,
    )


@router.get("/statistics", summary="工单统计")
async def get_work_order_statistics(
    exclude_status: str | None = Query(None, description="排除状态"),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:stats:read"),
    ),
) -> JSONResponse:
    stats = await service.get_work_order_statistics(
        db, ctx, exclude_status=exclude_status,
    )
    return success_response(data=WorkOrderStatistics.model_validate(stats))


@router.get("/{work_order_id}", summary="工单详情")
async def get_work_order(
    work_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:work_order:read"),
    ),
) -> JSONResponse:
    wo = await service.get_work_order_by_id(db, work_order_id)
    return success_response(data=_to_response(wo))


@router.put("/{work_order_id}/assign", summary="指派维修人")
async def assign_work_order(
    work_order_id: uuid.UUID,
    data: WorkOrderAssign,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:work_order:update"),
    ),
) -> JSONResponse:
    wo = await service.assign_work_order(db, work_order_id, data.assignee_id, ctx)
    return success_response(data=_to_response(wo))


@router.put("/{work_order_id}/start", summary="开始维修")
async def start_work_order(
    work_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:work_order:update"),
    ),
) -> JSONResponse:
    wo = await service.start_work_order(db, work_order_id, ctx)
    # 网页点击开始时飞书通知维修人（非关键路径）
    asyncio.ensure_future(_notify_start(wo))
    return success_response(data=_to_response(wo))


@router.put("/{work_order_id}/complete", summary="提交完成")
async def complete_work_order(
    work_order_id: uuid.UUID,
    data: WorkOrderComplete,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:work_order:update"),
    ),
) -> JSONResponse:
    wo = await service.complete_work_order(db, work_order_id, data, ctx)
    return success_response(data=_to_response(wo))


@router.put("/{work_order_id}/verify", summary="验收")
async def verify_work_order(
    work_order_id: uuid.UUID,
    data: WorkOrderVerify,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:work_order:approve"),
    ),
) -> JSONResponse:
    wo = await service.verify_work_order(db, work_order_id, ctx, data)
    return success_response(data=_to_response(wo))


@router.put("/{work_order_id}/close", summary="关闭工单")
async def close_work_order(
    work_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:work_order:update"),
    ),
) -> JSONResponse:
    wo = await service.close_work_order(db, work_order_id, ctx)
    return success_response(data=_to_response(wo))


@router.post("/{work_order_id}/materials", summary="领料")
async def consume_materials(
    work_order_id: uuid.UUID,
    data: MaterialConsumeRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:work_order:update"),
    ),
) -> JSONResponse:
    items = [item.model_dump() for item in data.items]
    transactions = await service.consume_materials(db, work_order_id, items, ctx)
    return success_response(
        data=[MaterialConsumeResponse.model_validate(t) for t in transactions]
    )


@router.get("/{work_order_id}/materials", summary="工单领料记录")
async def get_material_consumptions(
    work_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:work_order:read"),
    ),
) -> JSONResponse:
    from app.modules.equipment import repository as repo

    transactions = await repo.get_material_consumptions(db, work_order_id)
    return success_response(
        data=[MaterialConsumeResponse.model_validate(t) for t in transactions]
    )
