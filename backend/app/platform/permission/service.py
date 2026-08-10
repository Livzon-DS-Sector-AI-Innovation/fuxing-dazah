"""Permission business logic service."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DuplicateException,
    ForbiddenException,
    NotFoundException,
)
from app.platform.permission.cache import invalidate_user_cache
from app.platform.permission.models import Role
from app.platform.permission.repository import PermissionRepository
from app.platform.permission.schemas import (
    CreateRoleInput,
    UpdateRoleInput,
)

_repo = PermissionRepository()


class PermissionService:
    """权限管理业务逻辑。"""

    async def create_role(self, db: AsyncSession, data: CreateRoleInput) -> Role:
        existing = await _repo.get_role_by_code(db, data.code)
        if existing:
            raise DuplicateException("角色编码", data.code)
        role = Role(
            code=data.code,
            name=data.name,
            description=data.description,
            data_scope=data.data_scope,
        )
        role = await _repo.create_role(db, role)

        if data.permission_ids:
            await _repo.set_role_permissions(db, role.id, data.permission_ids)

        if data.data_scope_overrides:
            await _repo.set_role_data_scope_overrides(
                db, role.id, data.data_scope_overrides
            )

        # re-fetch after updates
        return await _repo.get_role_by_id(db, role.id) or role

    async def update_role(
        self, db: AsyncSession, role_id: uuid.UUID, data: UpdateRoleInput
    ) -> Role:
        role = await _repo.get_role_by_id(db, role_id)
        if not role:
            raise NotFoundException("角色", str(role_id))
        if role.is_system:
            raise ForbiddenException("系统内置角色不可修改")

        if data.name is not None:
            role.name = data.name
        if data.description is not None:
            role.description = data.description
        if data.data_scope is not None:
            role.data_scope = data.data_scope
        await db.flush()

        if data.permission_ids is not None:
            await _repo.set_role_permissions(db, role_id, data.permission_ids)
        if data.data_scope_overrides is not None:
            await _repo.set_role_data_scope_overrides(
                db, role_id, data.data_scope_overrides
            )

        # UPDATE → re-fetch (SQLAlchemy async rule)
        return await _repo.get_role_by_id(db, role_id) or role

    async def delete_role(self, db: AsyncSession, role_id: uuid.UUID) -> None:
        role = await _repo.get_role_by_id(db, role_id)
        if not role:
            raise NotFoundException("角色", str(role_id))
        if role.is_system:
            raise ForbiddenException("系统内置角色不可删除")

        # 1. 找出所有受影响的用户（直接分配 + 部门继承）
        affected_user_ids = await _repo.get_all_user_ids_for_role(db, role_id)

        # 2. 硬删除所有关联记录
        await _repo.delete_role_associations(db, role_id)

        # 3. 软删除角色
        await _repo.soft_delete_role(db, role_id)

        # 4. 失效受影响用户的权限缓存
        for uid in affected_user_ids:
            await invalidate_user_cache(str(uid))

    async def assign_role_to_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        department_id: uuid.UUID | None = None,
    ) -> None:
        role = await _repo.get_role_by_id(db, role_id)
        if not role:
            raise NotFoundException("角色", str(role_id))
        await _repo.assign_role_to_user(db, user_id, role_id, department_id)
        await invalidate_user_cache(str(user_id))

    async def remove_role_from_user(
        self, db: AsyncSession, user_id: uuid.UUID, role_id: uuid.UUID
    ) -> None:
        await _repo.remove_role_from_user(db, user_id, role_id)
        await invalidate_user_cache(str(user_id))

    async def assign_role_to_department(
        self, db: AsyncSession, role_id: uuid.UUID,
        feishu_department_ids: list[str],
    ) -> None:
        """将角色分配给一个或多个部门（含子孙部门缓存失效）。"""
        role = await _repo.get_role_by_id(db, role_id)
        if not role:
            raise NotFoundException("角色", str(role_id))

        for dept_id in feishu_department_ids:
            await _repo.assign_role_to_department(db, role_id, dept_id)

        # 展开所有目标部门的子孙 → 失效受影响用户缓存
        _, descendant_map = await _repo._build_dept_tree(db)
        all_dept_ids: set[str] = set()
        for dept_id in feishu_department_ids:
            all_dept_ids.update(descendant_map.get(dept_id, {dept_id}))
        user_ids = await _repo.get_user_ids_by_departments(db, list(all_dept_ids))
        for uid in user_ids:
            await invalidate_user_cache(str(uid))

    async def remove_role_from_department(
        self, db: AsyncSession, role_id: uuid.UUID,
        feishu_department_id: str,
    ) -> None:
        """移除部门的角色分配。"""
        ok = await _repo.remove_role_from_department(db, role_id, feishu_department_id)
        if not ok:
            raise NotFoundException("部门角色关联")

        # 失效该部门及子孙的用户缓存
        _, descendant_map = await _repo._build_dept_tree(db)
        all_dept_ids = descendant_map.get(feishu_department_id, {feishu_department_id})
        user_ids = await _repo.get_user_ids_by_departments(db, list(all_dept_ids))
        for uid in user_ids:
            await invalidate_user_cache(str(uid))
