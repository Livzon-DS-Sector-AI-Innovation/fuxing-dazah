"""部门管理 API 端点。"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from fastapi import Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.core.response import success_response
from app.modules.meter import repository as repo
from app.modules.meter import service
from app.modules.meter.api._router import router
from app.modules.meter.schemas import (
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    PersonnelCandidate,
)

# ═══════════════════════════════════════════
# 部门管理
# ═══════════════════════════════════════════


@router.get("/departments", summary="部门列表")
async def list_departments(
    source: str | None = Query(default=None, pattern="^(instrument|gas_detector)$", description="来源筛选"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await service.list_departments(db, source=source)
    return success_response(
        [DepartmentResponse(**r).model_dump(mode="json") for r in result]
    )



@router.post("/departments", summary="新增部门")
async def create_department(
    data: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    dept = await service.create_department(db, data)
    return success_response(
        DepartmentResponse(
            id=str(dept.id),
            source=dept.source,
            name=dept.name,
            heads=cast(Any, dept.heads or []),
            auto_notify_enabled=dept.auto_notify_enabled,
            created_at=dept.created_at,
            updated_at=dept.updated_at,
        ).model_dump(mode="json"),
        status_code=201,
    )



@router.put("/departments/{dept_id}", summary="更新部门（联动更新表中记录）")
async def update_department(
    dept_id: UUID,
    data: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    dept = await service.update_department(db, dept_id, data)
    return success_response(
        DepartmentResponse(
            id=str(dept.id),
            source=dept.source,
            name=dept.name,
            heads=cast(Any, dept.heads or []),
            auto_notify_enabled=dept.auto_notify_enabled,
            created_at=dept.created_at,
            updated_at=dept.updated_at,
        ).model_dump(mode="json")
    )



@router.put("/departments/{dept_id}/auto-notify", summary="切换部门自动提醒开关")
async def toggle_department_auto_notify(
    dept_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    dept = await repo.get_department_by_id(db, dept_id)
    if dept is None:
        raise NotFoundException("部门", str(dept_id))
    new_state = not dept.auto_notify_enabled
    updated = await service.update_department(
        db, dept_id,
        DepartmentUpdate(name=dept.name, auto_notify_enabled=new_state)
    )
    return success_response(
        DepartmentResponse(
            id=str(updated.id),
            source=updated.source,
            name=updated.name,
            heads=cast(Any, updated.heads or []),
            auto_notify_enabled=updated.auto_notify_enabled,
            created_at=updated.created_at,
            updated_at=updated.updated_at,
        ).model_dump(mode="json")
    )



@router.get("/departments/personnel-candidates", summary="获取可选负责人列表（从 identity.users 查询）")
async def get_personnel_candidates(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """从平台 identity.users 查询所有用户，作为负责人候选人列表。"""
    candidates = await service.get_personnel_candidates(db)
    return success_response(
        [PersonnelCandidate(**c).model_dump(mode="json") for c in candidates]
    )



@router.delete("/departments/{dept_id}", summary="删除部门")
async def delete_department(
    dept_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await service.delete_department(db, dept_id)
    return success_response(message="删除成功")
