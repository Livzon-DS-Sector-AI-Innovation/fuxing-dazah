"""人员配置 API 路由."""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.equipment import service
from app.modules.equipment.schemas.personnel import (
    PersonnelAddRequest,
    PersonnelCategoryAssign,
    PersonnelRoleAssign,
    PersonnelUpdate,
    RoleCreate,
    RoleUpdate,
)

router = APIRouter()


# ═══════════════ 角色 API ═══════════════

@router.post("/roles", summary="创建角色")
async def create_role(
    data: RoleCreate,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    role = await service.create_role(db, data)
    return success_response(data=role.model_dump(mode="json"))


@router.get("/roles", summary="角色列表")
async def list_roles(
    scope: str | None = Query(None, description="作用域筛选"),
    is_active: bool | None = Query(None, description="启用状态筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    roles, total = await service.list_roles(
        db, scope=scope, is_active=is_active, page=page, page_size=page_size,
    )
    return success_response(
        data=[r.model_dump(mode="json") for r in roles],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get("/roles/{role_id}", summary="角色详情")
async def get_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    role = await service.get_role(db, role_id)
    return success_response(data=role.model_dump(mode="json"))


@router.put("/roles/{role_id}", summary="更新角色")
async def update_role(
    role_id: uuid.UUID,
    data: RoleUpdate,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    role = await service.update_role(db, role_id, data)
    return success_response(data=role.model_dump(mode="json"))


@router.delete("/roles/{role_id}", summary="删除角色")
async def delete_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await service.delete_role(db, role_id)
    return success_response(message="角色已删除")


# ═══════════════ 人员 API ═══════════════

@router.post("", summary="从身份系统添加人员")
async def add_personnel(
    data: PersonnelAddRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await service.add_personnel(db, data)
    return success_response(data=result.model_dump(mode="json"))


@router.get("", summary="人员列表")
async def list_personnel(
    role_id: list[uuid.UUID] | None = Query(None, description="按角色 ID 筛选"),
    is_active: bool | None = Query(None, description="在岗状态筛选"),
    keyword: str | None = Query(None, description="姓名搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await service.list_personnel(
        db, role_ids=role_id, is_active=is_active, keyword=keyword,
        page=page, page_size=page_size,
    )
    return success_response(
        data=[r.model_dump(mode="json") for r in result.items],
        meta={
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
        },
    )


@router.get("/candidates", summary="按角色查询可分配人员")
async def get_candidates(
    role_codes: list[str] = Query(
        ..., description="角色编码列表，如 maintenance_tech",
    ),
    category_id: uuid.UUID | None = Query(None, description="设备分类ID（可选）"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    candidates = await service.get_candidates(
        db, role_codes, category_id=category_id,
    )
    return success_response(data=[c.model_dump(mode="json") for c in candidates])


@router.get("/{personnel_id}", summary="人员详情")
async def get_personnel(
    personnel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    person = await service.get_personnel(db, personnel_id)
    return success_response(data=person.model_dump(mode="json"))


@router.put("/{personnel_id}", summary="更新人员")
async def update_personnel(
    personnel_id: uuid.UUID,
    data: PersonnelUpdate,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    person = await service.update_personnel(db, personnel_id, data)
    return success_response(data=person.model_dump(mode="json"))


@router.delete("/{personnel_id}", summary="移除人员")
async def delete_personnel(
    personnel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await service.delete_personnel(db, personnel_id)
    return success_response(message="人员已移除")


@router.post("/{personnel_id}/roles", summary="为人员分配角色")
async def assign_roles(
    personnel_id: uuid.UUID,
    data: PersonnelRoleAssign,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    person = await service.assign_roles(db, personnel_id, data)
    return success_response(data=person.model_dump(mode="json"))


@router.put("/{personnel_id}/roles", summary="全量更新人员角色")
async def update_roles(
    personnel_id: uuid.UUID,
    data: PersonnelRoleAssign,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    person = await service.assign_roles(db, personnel_id, data)
    return success_response(data=person.model_dump(mode="json"))


@router.post("/{personnel_id}/categories", summary="设置人员角色设备分类")
async def assign_categories(
    personnel_id: uuid.UUID,
    data: PersonnelCategoryAssign,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    person = await service.update_categories(db, personnel_id, data)
    return success_response(data=person.model_dump(mode="json"))


@router.put("/{personnel_id}/categories", summary="全量更新人员角色分类")
async def update_categories(
    personnel_id: uuid.UUID,
    data: PersonnelCategoryAssign,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    person = await service.update_categories(db, personnel_id, data)
    return success_response(data=person.model_dump(mode="json"))


@router.post("/refresh-feishu", summary="手动刷新飞书信息")
async def refresh_feishu(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await service.refresh_feishu(db)
    return success_response(data=result.model_dump(mode="json"))
