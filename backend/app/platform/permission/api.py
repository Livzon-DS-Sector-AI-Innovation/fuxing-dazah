"""Permission admin API routes."""

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.core.response import success_response
from app.platform.identity.models import Department as DeptModel
from app.platform.identity.models import User
from app.platform.permission.deps import require_admin
from app.platform.permission.models import DepartmentRole, UserRole
from app.platform.permission.repository import PermissionRepository
from app.platform.permission.schemas import (
    AssignDepartmentRoleInput,
    AssignRoleInput,
    CreateRoleInput,
    DepartmentRoleOut,
    PermissionModuleGroup,
    PermissionOut,
    RoleOut,
    RoleUserOut,
    UpdateRoleInput,
    UserPermissionOut,
    UserRoleOut,
)
from app.platform.permission.service import PermissionService
from app.shared.module_registry import MODULES_BY_CODE

router = APIRouter()
_service = PermissionService()
_repo = PermissionRepository()


@router.get("/permissions", summary="获取所有权限（按模块分组）")
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    permissions = await _repo.list_permissions(db)
    grouped: dict[str, list[PermissionOut]] = {}
    for p in permissions:
        grouped.setdefault(p.module, []).append(PermissionOut.model_validate(p))

    result = []
    for module_code, perms in grouped.items():
        module_def = MODULES_BY_CODE.get(module_code)
        if module_def:
            module_name = module_def.name
        elif module_code == "permission":
            module_name = "权限管理"
        else:
            module_name = module_code
        result.append(
            PermissionModuleGroup(
                module=module_code,
                module_name=module_name,
                permissions=perms,
            )
        )

    return success_response(data=[g.model_dump(mode="json") for g in result])


@router.get("/roles", summary="角色列表")
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    roles = await _repo.list_roles(db)

    # 批量查询权限 ID 和数据范围覆盖
    role_ids = [r.id for r in roles]
    perm_ids_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    override_map: dict[uuid.UUID, dict[str, str]] = {}
    user_count_map: dict[uuid.UUID, int] = {}
    dept_count_map: dict[uuid.UUID, int] = {}

    for rid in role_ids:
        perm_ids_map[rid] = await _repo.get_role_permission_ids(db, rid)
        override_map[rid] = await _repo.get_role_data_scope_overrides(db, rid)

    # 批量计数：一次 GROUP BY 替代 N 次 COUNT
    user_counts_stmt = (
        select(UserRole.role_id, func.count())
        .where(UserRole.role_id.in_(role_ids))
        .group_by(UserRole.role_id)
    )
    for row in (await db.execute(user_counts_stmt)).all():
        user_count_map[row[0]] = row[1]

    dept_counts_stmt = (
        select(DepartmentRole.role_id, func.count())
        .where(DepartmentRole.role_id.in_(role_ids))
        .group_by(DepartmentRole.role_id)
    )
    for row in (await db.execute(dept_counts_stmt)).all():
        dept_count_map[row[0]] = row[1]

    result = []
    for role in roles:
        result.append(
            RoleOut(
                id=role.id,
                code=role.code,
                name=role.name,
                description=role.description,
                data_scope=role.data_scope,
                is_system=role.is_system,
                created_at=role.created_at,
                updated_at=role.updated_at,
                permission_ids=perm_ids_map.get(role.id, []),
                data_scope_overrides=override_map.get(role.id, {}),
                user_count=user_count_map.get(role.id, 0),
                department_count=dept_count_map.get(role.id, 0),
            ).model_dump(mode="json")
        )

    return success_response(data=result)


@router.post("/roles", summary="创建角色")
async def create_role(
    data: CreateRoleInput,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    role = await _service.create_role(db, data)
    perm_ids = await _repo.get_role_permission_ids(db, role.id)
    overrides = await _repo.get_role_data_scope_overrides(db, role.id)
    out = RoleOut(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        data_scope=role.data_scope,
        is_system=role.is_system,
        created_at=role.created_at,
        updated_at=role.updated_at,
        permission_ids=perm_ids,
        data_scope_overrides=overrides,
    )
    return success_response(data=out.model_dump(mode="json"), message="角色创建成功")


@router.put("/roles/{role_id}", summary="更新角色")
async def update_role(
    role_id: uuid.UUID,
    data: UpdateRoleInput,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    role = await _service.update_role(db, role_id, data)
    perm_ids = await _repo.get_role_permission_ids(db, role.id)
    overrides = await _repo.get_role_data_scope_overrides(db, role.id)
    out = RoleOut(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        data_scope=role.data_scope,
        is_system=role.is_system,
        created_at=role.created_at,
        updated_at=role.updated_at,
        permission_ids=perm_ids,
        data_scope_overrides=overrides,
    )
    return success_response(data=out.model_dump(mode="json"), message="角色更新成功")


@router.delete("/roles/{role_id}", summary="删除角色")
async def delete_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    await _service.delete_role(db, role_id)
    return success_response(message="角色删除成功")


@router.get("/roles/{role_id}/users", summary="获取角色下的用户列表")
async def get_role_users(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    users = await _repo.get_role_users(db, role_id)
    result = [RoleUserOut.model_validate(u).model_dump(mode="json") for u in users]
    return success_response(data=result)


@router.get("/users/{user_id}/roles", summary="获取用户的角色列表")
async def get_user_roles(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    user_roles = await _repo.get_user_roles(db, user_id)
    result = []
    for ur in user_roles:
        role = await _repo.get_role_by_id(db, ur.role_id)
        result.append(
            UserRoleOut(
                id=ur.id,
                user_id=ur.user_id,
                role_id=ur.role_id,
                department_id=ur.department_id,
                role_name=role.name if role else "",
                role_code=role.code if role else "",
            ).model_dump(mode="json")
        )
    return success_response(data=result)


@router.post("/users/{user_id}/roles", summary="给用户分配角色")
async def assign_user_role(
    user_id: uuid.UUID,
    data: AssignRoleInput,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    await _service.assign_role_to_user(db, user_id, data.role_id, data.department_id)
    return success_response(message="角色分配成功")


@router.delete("/users/{user_id}/roles/{role_id}", summary="移除用户角色")
async def remove_user_role(
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    await _service.remove_role_from_user(db, user_id, role_id)
    return success_response(message="角色移除成功")


@router.get("/users/{user_id}/permissions", summary="获取用户合并后的权限列表")
async def get_user_permissions_endpoint(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    user_stmt = select(User).where(User.id == user_id)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()
    if not user:
        raise NotFoundException("用户", str(user_id))

    user_roles = await _repo.get_user_roles(db, user_id)
    roles_out = []
    for ur in user_roles:
        role = await _repo.get_role_by_id(db, ur.role_id)
        roles_out.append(
            UserRoleOut(
                id=ur.id,
                user_id=ur.user_id,
                role_id=ur.role_id,
                department_id=ur.department_id,
                role_name=role.name if role else "",
                role_code=role.code if role else "",
            )
        )

    perm_codes = await _repo.get_user_permission_codes(db, user_id)

    data_scopes: dict[str, str] = {}
    for module_code in MODULES_BY_CODE:
        scope = await _repo.get_effective_data_scope(db, user_id, module_code)
        data_scopes[module_code] = scope

    resource_scopes = await _repo.get_user_resource_scopes(db, user_id)

    out = UserPermissionOut(
        user_id=user_id,
        user_name=user.name,
        roles=roles_out,
        permissions=sorted(perm_codes),
        data_scopes=data_scopes,
        resource_scopes=resource_scopes,
    )
    return success_response(data=out.model_dump(mode="json"))


# ── 部门角色分配 ──


@router.get("/roles/{role_id}/departments", summary="获取角色已分配的部门列表")
async def get_role_departments(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    dept_roles = await _repo.list_role_departments(db, role_id)
    dept_ids = [dr.feishu_department_id for dr in dept_roles]
    dept_map: dict[str, DeptModel] = {}
    if dept_ids:
        dept_stmt = select(DeptModel).where(
            DeptModel.feishu_department_id.in_(dept_ids),
            DeptModel.is_deleted == False,  # noqa: E712
        )
        dept_result = await db.execute(dept_stmt)
        dept_map = {d.feishu_department_id: d for d in dept_result.scalars()}

    result = []
    for dr in dept_roles:
        dept = dept_map.get(dr.feishu_department_id)
        result.append(
            DepartmentRoleOut(
                id=dr.id,
                feishu_department_id=dr.feishu_department_id,
                role_id=dr.role_id,
                department_name=dept.name if dept else "",
                member_count=dept.member_count if dept else 0,
            ).model_dump(mode="json")
        )
    return success_response(data=result)


@router.post("/roles/{role_id}/departments", summary="将角色分配给部门（支持多选）")
async def assign_role_to_department_endpoint(
    role_id: uuid.UUID,
    data: AssignDepartmentRoleInput,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    await _service.assign_role_to_department(
        db, role_id, data.feishu_department_ids,
    )
    return success_response(message="部门角色分配成功")


@router.delete(
    "/roles/{role_id}/departments/{feishu_department_id}",
    summary="移除部门的角色分配",
)
async def remove_role_from_department_endpoint(
    role_id: uuid.UUID,
    feishu_department_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> JSONResponse:
    await _service.remove_role_from_department(
        db, role_id, feishu_department_id,
    )
    return success_response(message="部门角色已移除")
