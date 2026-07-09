"""Permission data access layer."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.permission.models import (
    Permission,
    Role,
    RoleDataScopeOverride,
    RolePermission,
    UserRole,
)


class PermissionRepository:
    """权限、角色、关联关系的数据库操作。"""

    # ── 权限查询 ──

    async def list_permissions(self, db: AsyncSession) -> list[Permission]:
        stmt = (
            select(Permission)
            .where(Permission.is_deleted == False)  # noqa: E712
            .order_by(Permission.module, Permission.resource, Permission.action)
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    async def get_permission_by_id(
        self, db: AsyncSession, permission_id: uuid.UUID
    ) -> Permission | None:
        stmt = select(Permission).where(
            Permission.id == permission_id,
            Permission.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # ── 角色 CRUD ──

    async def list_roles(self, db: AsyncSession) -> list[Role]:
        stmt = (
            select(Role)
            .where(Role.is_deleted == False)  # noqa: E712
            .order_by(Role.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    async def get_role_by_id(self, db: AsyncSession, role_id: uuid.UUID) -> Role | None:
        stmt = select(Role).where(
            Role.id == role_id,
            Role.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_roles_by_ids(
        self, db: AsyncSession, role_ids: list[uuid.UUID]
    ) -> list[Role]:
        """批量获取角色，一次查询替代 N 次 get_role_by_id。"""
        if not role_ids:
            return []
        stmt = select(Role).where(
            Role.id.in_(role_ids),
            Role.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    async def get_role_by_code(self, db: AsyncSession, code: str) -> Role | None:
        stmt = select(Role).where(
            Role.code == code,
            Role.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_role(self, db: AsyncSession, role: Role) -> Role:
        db.add(role)
        await db.flush()
        return role

    async def soft_delete_role(self, db: AsyncSession, role_id: uuid.UUID) -> bool:
        stmt = select(Role).where(
            Role.id == role_id,
            Role.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        role = result.scalar_one_or_none()
        if not role:
            return False
        role.is_deleted = True
        await db.flush()
        # UPDATE 后必须 re-fetch，确保 updated_at 等字段回填
        re_fetch = select(Role).where(Role.id == role_id)
        re_result = await db.execute(re_fetch)
        re_result.scalar_one()
        return True

    # ── 角色权限关联 ──

    async def get_role_permission_ids(
        self, db: AsyncSession, role_id: uuid.UUID
    ) -> list[uuid.UUID]:
        stmt = select(RolePermission.permission_id).where(
            RolePermission.role_id == role_id
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    async def set_role_permissions(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
        permission_ids: list[uuid.UUID],
    ) -> None:
        """全量替换角色的权限列表。"""
        await db.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )
        for pid in permission_ids:
            db.add(RolePermission(role_id=role_id, permission_id=pid))
        await db.flush()

    # ── 用户角色关联 ──

    async def get_user_roles(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> list[UserRole]:
        stmt = select(UserRole).where(UserRole.user_id == user_id)
        result = await db.execute(stmt)
        return list(result.scalars())

    async def assign_role_to_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        department_id: uuid.UUID | None = None,
    ) -> UserRole:
        stmt = select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == role_id,
            UserRole.department_id == department_id,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        ur = UserRole(user_id=user_id, role_id=role_id, department_id=department_id)
        db.add(ur)
        await db.flush()
        return ur

    async def remove_role_from_user(
        self, db: AsyncSession, user_id: uuid.UUID, role_id: uuid.UUID
    ) -> bool:
        stmt = delete(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == role_id,
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    # ── 用户权限查询（合并所有角色） ──

    async def get_user_permission_codes(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> set[str]:
        """获取用户所有权限编码（合并所有角色的权限）。"""
        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(
                UserRole.user_id == user_id,
                Permission.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(stmt)
        return set(result.scalars())

    # ── 数据范围 ──

    async def get_role_data_scope_overrides(
        self, db: AsyncSession, role_id: uuid.UUID
    ) -> dict[str, str]:
        stmt = select(RoleDataScopeOverride).where(
            RoleDataScopeOverride.role_id == role_id
        )
        result = await db.execute(stmt)
        return {o.module: o.data_scope for o in result.scalars()}

    async def set_role_data_scope_overrides(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
        overrides: dict[str, str],
    ) -> None:
        """全量替换角色的模块级数据范围覆盖。"""
        await db.execute(
            delete(RoleDataScopeOverride).where(
                RoleDataScopeOverride.role_id == role_id
            )
        )
        for module, scope in overrides.items():
            db.add(
                RoleDataScopeOverride(role_id=role_id, module=module, data_scope=scope)
            )
        await db.flush()

    async def _get_resource_role_ids(
        self, db: AsyncSession, user_id: uuid.UUID, module: str, resource: str
    ) -> set[uuid.UUID]:
        """返回用户在该 module+resource 下有至少一条权限的角色 ID 集合。

        用于 get_effective_data_scope 过滤无关角色，避免其他角色的数据范围污染。
        """
        stmt = (
            select(UserRole.role_id)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(
                UserRole.user_id == user_id,
                Permission.module == module,
                Permission.resource == resource,
                Permission.is_deleted == False,  # noqa: E712
            )
            .distinct()
        )
        result = await db.execute(stmt)
        return set(result.scalars())

    async def get_effective_data_scope(
        self, db: AsyncSession, user_id: uuid.UUID, module: str,
        resource: str | None = None,
    ) -> str:
        """获取用户在某模块的有效数据范围（取最宽松）。

        优先级: all > department_and_children > department > self_only

        当 resource 指定时，仅计算拥有该 module+resource 权限的角色，
        避免无关角色的数据范围污染目标资源。
        """
        scope_priority = {
            "all": 4,
            "department_and_children": 3,
            "department": 2,
            "self_only": 1,
        }

        user_roles = await self.get_user_roles(db, user_id)
        if not user_roles:
            return "self_only"

        role_ids = [ur.role_id for ur in user_roles]

        # 按 resource 过滤：只保留确实有该资源权限的角色
        if resource:
            relevant_role_ids = await self._get_resource_role_ids(
                db, user_id, module, resource
            )
            if not relevant_role_ids:
                return "self_only"
            role_ids = [rid for rid in role_ids if rid in relevant_role_ids]

        stmt = select(Role).where(
            Role.id.in_(role_ids),
            Role.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        roles = list(result.scalars())

        best_scope = "self_only"
        best_priority = 0

        for role in roles:
            overrides = await self.get_role_data_scope_overrides(db, role.id)
            scope = overrides.get(module) or role.data_scope or "self_only"
            priority = scope_priority.get(scope, 0)
            if priority > best_priority:
                best_priority = priority
                best_scope = scope

        return best_scope

    async def get_user_all_data_scopes(
        self, db: AsyncSession, user_id: uuid.UUID, modules: list[str]
    ) -> dict[str, str]:
        """批量获取用户在所有模块的有效数据范围。

        一次查询所有角色的 overrides，在内存中计算每个模块的最宽范围。
        替代逐模块调用 get_effective_data_scope 的 O(modules × roles) 查询。
        """
        scope_priority = {
            "all": 4,
            "department_and_children": 3,
            "department": 2,
            "self_only": 1,
        }

        user_roles = await self.get_user_roles(db, user_id)
        if not user_roles:
            return {m: "self_only" for m in modules}

        role_ids = [ur.role_id for ur in user_roles]

        # 一次查询所有角色
        roles_stmt = select(Role).where(
            Role.id.in_(role_ids),
            Role.is_deleted == False,  # noqa: E712
        )
        roles_result = await db.execute(roles_stmt)
        roles = list(roles_result.scalars())

        # 一次查询所有 overrides
        overrides_stmt = select(RoleDataScopeOverride).where(
            RoleDataScopeOverride.role_id.in_(role_ids)
        )
        overrides_result = await db.execute(overrides_stmt)
        all_overrides = list(overrides_result.scalars())

        # 按 role_id 分组 overrides
        overrides_map: dict[uuid.UUID, dict[str, str]] = {}
        for o in all_overrides:
            overrides_map.setdefault(o.role_id, {})[o.module] = o.data_scope

        # 在内存中计算每个模块的最宽范围
        result: dict[str, str] = {}
        for mod in modules:
            best_scope = "self_only"
            best_priority = 0
            for role in roles:
                role_overrides = overrides_map.get(role.id, {})
                scope = role_overrides.get(mod) or role.data_scope or "self_only"
                priority = scope_priority.get(scope, 0)
                if priority > best_priority:
                    best_priority = priority
                    best_scope = scope
            result[mod] = best_scope

        return result

    async def get_user_resource_scopes(
        self, db: AsyncSession, user_id: uuid.UUID,
    ) -> dict[str, str]:
        """获取用户在每个 (module:resource) 维度的有效数据范围。

        key 格式: "module:resource"，如 "equipment:inspection"
        仅包含用户确实有权限的 module+resource 组合，
        且仅统计拥有该 resource 权限的角色。
        """
        # 1. 获取用户所有 distinct (module, resource) 组合
        stmt = (
            select(Permission.module, Permission.resource)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(
                UserRole.user_id == user_id,
                Permission.is_deleted == False,  # noqa: E712
            )
            .distinct()
        )
        pair_result = await db.execute(stmt)
        pairs = list(pair_result.all())

        if not pairs:
            return {}

        # 2. 对每个 pair 调用资源级数据范围计算
        result: dict[str, str] = {}
        for module, resource in pairs:
            key = f"{module}:{resource}"
            scope = await self.get_effective_data_scope(
                db, user_id, module, resource=resource,
            )
            result[key] = scope

        return result
