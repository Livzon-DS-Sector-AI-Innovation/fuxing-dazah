"""工序执行 API — 只做 HTTP 层。"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.production.schemas import (
    ExecutionCompleteIn,
    ExecutionOut,
    ExecutionStartIn,
)
from app.modules.production.service import execution_service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()
_submit = require_permission("production:batch:submit")
_read = require_permission("production:batch:read")


@router.post("/batches/{batch_id}/executions", summary="开始工序")
async def start_execution(
    batch_id: uuid.UUID,
    payload: ExecutionStartIn,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    execution = await execution_service.start_execution(db, batch_id, payload, user)
    return success_response(
        ExecutionOut.model_validate(execution).model_dump(mode="json")
    )


@router.post("/executions/{execution_id}/complete", summary="结束工序")
async def complete_execution(
    execution_id: uuid.UUID,
    payload: ExecutionCompleteIn,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    execution = await execution_service.complete_execution(
        db, execution_id, payload, user
    )
    return success_response(
        ExecutionOut.model_validate(execution).model_dump(mode="json")
    )


@router.post("/executions/{execution_id}/abort", summary="中止工序执行")
async def abort_execution(
    execution_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    execution = await execution_service.abort_execution(db, execution_id, user)
    return success_response(
        ExecutionOut.model_validate(execution).model_dump(mode="json")
    )


@router.get("/nodes/{node_id}/executions", summary="工序执行记录（跨批次）")
async def list_node_executions(
    node_id: uuid.UUID,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order_by: str = Query("started_at", pattern="^(batch_no|started_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await execution_service.list_node_executions(
        db, node_id, status, page, page_size, order_by, order
    )
    return paginated_response(
        [i.model_dump(mode="json") for i in items], page, page_size, total
    )
