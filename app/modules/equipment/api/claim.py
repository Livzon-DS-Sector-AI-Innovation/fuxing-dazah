"""抢单 API 路由."""

import asyncio
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AppException, ForbiddenException
from app.core.response import success_response
from app.modules.equipment import service
from app.modules.equipment.deps import EquipmentAccessContext, require_equipment_access
from app.modules.equipment.schemas import WorkOrderResponse
from app.platform.integrations.feishu.contact import is_department_member
from app.platform.integrations.feishu.message import send_claim_notification

router = APIRouter()


@router.put("/{work_order_id}/claim", summary="抢单（维修人员自主接单）")
async def claim_work_order(
    work_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    settings = Depends(get_settings),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:work_order:update"),
    ),
) -> JSONResponse:
    dept_id = settings.FEISHU_EQUIPMENT_DEPT_ID
    if not dept_id:
        raise AppException(message="设备部未配置")

    feishu_id = ctx.user.feishu_user_id or ""
    if not feishu_id:
        raise ForbiddenException(message="用户未关联飞书账号")

    is_member = await is_department_member(feishu_id, dept_id)
    if not is_member:
        raise ForbiddenException(message="只有设备部成员才能接单")

    wo = await service.claim_work_order(db, work_order_id, ctx.user.id)

    asyncio.ensure_future(
        send_claim_notification(wo.work_order_no, ctx.user.name)
    )

    resp = WorkOrderResponse.model_validate(wo)
    if wo.reporter:
        resp.reporter_name = wo.reporter.name
    if wo.assignee:
        resp.assignee_name = wo.assignee.name
    return success_response(data=resp)
