"""Workflow API — 工作流定义 CRUD + 执行。"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.safety.workflow.schemas import (
    WorkflowDefCreate,
    WorkflowDefResponse,
    WorkflowDefUpdate,
    WorkflowRunRequest,
    WorkflowRunResponse,
)
from app.modules.safety.workflow.service import WorkflowService

workflow_router = APIRouter()


# ═══════════════════════════════════════════════════════════
# WorkflowDefinition CRUD
# ═══════════════════════════════════════════════════════════

@workflow_router.get(
    "/workflow/definitions",
    summary="获取工作流定义列表",
)
async def list_definitions(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=500, description="每页条数"),
    module_code: str | None = Query(None, description="模块代码"),
    is_enabled: bool | None = Query(None, description="是否启用"),
    db: AsyncSession = Depends(get_db),
):
    service = WorkflowService(db)
    skip = (page - 1) * page_size
    items, total = await service.list_definitions(
        skip=skip, limit=page_size, module_code=module_code, is_enabled=is_enabled,
    )
    return success_response(
        data=[WorkflowDefResponse.model_validate(item) for item in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@workflow_router.get(
    "/workflow/definitions/{id}",
    summary="获取工作流定义详情",
)
async def get_definition(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = WorkflowService(db)
    wf = await service.get_definition(id)
    if wf is None:
        return success_response(message="工作流不存在", status_code=404)
    return success_response(data=WorkflowDefResponse.model_validate(wf))


@workflow_router.post(
    "/workflow/definitions",
    summary="创建工作流定义",
)
async def create_definition(
    body: WorkflowDefCreate,
    db: AsyncSession = Depends(get_db),
):
    service = WorkflowService(db)
    try:
        wf = await service.create_definition(body)
        return success_response(
            data=WorkflowDefResponse.model_validate(wf),
            message="创建成功",
        )
    except ValueError as e:
        return success_response(message=str(e), status_code=400)


@workflow_router.put(
    "/workflow/definitions/{id}",
    summary="更新工作流定义",
)
async def update_definition(
    id: uuid.UUID,
    body: WorkflowDefUpdate,
    db: AsyncSession = Depends(get_db),
):
    service = WorkflowService(db)
    try:
        wf = await service.update_definition(id, body)
        if wf is None:
            return success_response(message="工作流不存在", status_code=404)
        return success_response(
            data=WorkflowDefResponse.model_validate(wf),
            message="更新成功",
        )
    except ValueError as e:
        return success_response(message=str(e), status_code=400)


@workflow_router.delete(
    "/workflow/definitions/{id}",
    summary="删除工作流定义（软删除）",
)
async def delete_definition(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = WorkflowService(db)
    deleted = await service.delete_definition(id)
    if not deleted:
        return success_response(message="工作流不存在", status_code=404)
    return success_response(message="删除成功")


# ═══════════════════════════════════════════════════════════
# Workflow Run
# ═══════════════════════════════════════════════════════════

@workflow_router.post(
    "/workflow/definitions/{id}/run",
    summary="执行工作流（blocking）",
)
async def run_workflow(
    id: uuid.UUID,
    body: WorkflowRunRequest = WorkflowRunRequest(),
    db: AsyncSession = Depends(get_db),
):
    service = WorkflowService(db)
    wf = await service.get_definition(id)
    if wf is None:
        return success_response(message="工作流不存在", status_code=404)

    # graphon 是同步执行引擎，用 run_in_executor 避免阻塞 FastAPI 事件循环
    loop = asyncio.get_running_loop()
    try:
        run = await loop.run_in_executor(
            None,
            lambda: asyncio.run(
                service.run_workflow(
                    workflow_id=id,
                    inputs=body.inputs,
                    entity_type=body.entity_type,
                    entity_id=body.entity_id,
                )
            ),
        )
        return success_response(
            data=WorkflowRunResponse.model_validate(run),
            message="执行成功",
        )
    except ValueError as e:
        return success_response(message=str(e), status_code=400)
    except Exception as e:
        return success_response(message=f"执行失败: {e}", status_code=500)


@workflow_router.get(
    "/workflow/runs",
    summary="获取运行记录列表",
)
async def list_runs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    workflow_id: uuid.UUID | None = Query(None, description="工作流 ID"),
    db: AsyncSession = Depends(get_db),
):
    service = WorkflowService(db)
    skip = (page - 1) * page_size
    items, total = await service.list_runs(
        workflow_id=workflow_id, skip=skip, limit=page_size,
    )
    return success_response(
        data=[WorkflowRunResponse.model_validate(item) for item in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@workflow_router.get(
    "/workflow/runs/{id}",
    summary="获取运行记录详情",
)
async def get_run(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = WorkflowService(db)
    run = await service.get_run(id)
    if run is None:
        return success_response(message="运行记录不存在", status_code=404)
    return success_response(data=WorkflowRunResponse.model_validate(run))
