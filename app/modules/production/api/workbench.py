"""生产-工作台 HTTP 路由。"""

from fastapi import APIRouter, Depends
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
):
    result = await workbench_service.query_workbench(db, current_user.id)
    return success_response(data=result)


@router.post("/workbench/receive-and-start", summary="接收批次并可选开始执行")
async def receive_and_start(
    body: ReceiveAndStartIn,
    current_user: RequireUser,
    db: AsyncSession = Depends(get_db),
):
    result = await workbench_service.receive_and_start(db, body, current_user)
    return success_response(data=result)
