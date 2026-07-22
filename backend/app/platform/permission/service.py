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
        await _repo.soft_delete_role(db, role_id)

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
