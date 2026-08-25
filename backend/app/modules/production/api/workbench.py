"""生产-工作台 HTTP 路由。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.production.schemas.assignment import ReceiveAndStartIn
from app.modules.production.service import workbench_service
from app.platform.permission.deps import RequireUser

router = APIRouter(tags=["生产-工作台"])


@router.get("/workbench", summary="工作台待办查询")
async def get_workbench(
    current_user: RequireUser,
    db: AsyncSession = Depends(get_db),
    view_mode: str = Query("mine", description="mine=只看自己的批次；all=查看全部（他人批次仅读）"),
):
    result = await workbench_service.query_workbench(db, current_user.id, view_mode=view_mode)
    return success_response(data=result)


@router.get("/workbench/planned", summary="工作台计划批次排期")
async def get_planned_batches(
    current_user: RequireUser,
    db: AsyncSession = Depends(get_db),
):
    result = await workbench_service.query_planned_batches(db, current_user.id)
    return success_response(data=result)


@router.post("/workbench/receive-and-start", summary="接收批次并可选开始执行")
async def receive_and_start(
    body: ReceiveAndStartIn,
    current_user: RequireUser,
    db: AsyncSession = Depends(get_db),
):
    result = await workbench_service.receive_and_start(db, body, current_user)
    return success_response(data=result)


@router.post("/workbench/activate-planned/{batch_id}", summary="激活计划批次为待开工")
async def activate_planned_batch(
    batch_id: uuid.UUID,
    current_user: RequireUser,
    db: AsyncSession = Depends(get_db),
):
    batch = await workbench_service.activate_planned_batch(db, batch_id, current_user)
    return success_response(data={
        "id": str(batch.id),
        "batch_no": batch.batch_no,
        "status": batch.status,
    })
