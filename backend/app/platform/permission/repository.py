"""Permission data access layer."""

import json
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.identity.models import Department, User
from app.platform.permission.models import (
    DepartmentRole,
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

    async def get_user_ids_by_role_id(
        self, db: AsyncSession, role_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """获取拥有某角色的所有用户 ID（直接分配，用于缓存失效）。"""
        stmt = select(UserRole.user_id).where(
            UserRole.role_id == role_id,
            UserRole.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    async def get_all_user_ids_for_role(
        self, db: AsyncSession, role_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """获取角色的所有受影响用户（直接分配 + 部门继承）。"""
        user_ids = set(await self.get_user_ids_by_role_id(db, role_id))

        dept_roles = await self.list_role_departments(db, role_id)
        if dept_roles:
            _, descendant_map = await self._build_dept_tree(db)
            all_dept_ids: set[str] = set()
            for dr in dept_roles:
                all_dept_ids.update(
                    descendant_map.get(dr.feishu_department_id, {dr.feishu_department_id})
                )
            dept_user_ids = await self.get_user_ids_by_departments(db, list(all_dept_ids))
            user_ids.update(dept_user_ids)

        return list(user_ids)

    async def get_role_users(self, db: AsyncSession, role_id: uuid.UUID) -> list[User]:
        """获取拥有某角色的用户列表（用于角色分配弹窗展示）。"""
        stmt = (
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .where(
                UserRole.role_id == role_id,
                UserRole.is_deleted == False,  # noqa: E712
                User.is_deleted == False,  # noqa: E712
            )
            .order_by(User.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    async def delete_role_associations(
        self, db: AsyncSession, role_id: uuid.UUID
    ) -> None:
        """硬删除角色的所有关联数据（含部门角色）。"""
        await db.execute(delete(UserRole).where(UserRole.role_id == role_id))
        await db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
        await db.execute(
            delete(RoleDataScopeOverride).where(RoleDataScopeOverride.role_id == role_id)
        )
        await db.execute(
            delete(DepartmentRole).where(DepartmentRole.role_id == role_id)
        )
        await db.flush()

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
        return result.rowcount > 0  # type: ignore[attr-defined,no-any-return]

    # ── 用户权限查询（合并所有角色） ──

    async def get_user_permission_codes(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> set[str]:
        """获取用户所有权限编码（合并：直接分配 + 部门继承）。"""
        # 1. 直接用户角色权限（现有逻辑）
        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                Permission.is_deleted == False,  # noqa: E712
                Role.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(stmt)
        perms = set(result.scalars())

        # 2. 部门继承角色权限
        expanded = await self._get_user_expanded_dept_ids(db, user_id)
        if expanded:
            dept_stmt = (
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .join(Role, Role.id == RolePermission.role_id)
                .join(DepartmentRole, DepartmentRole.role_id == Role.id)
                .where(
                    DepartmentRole.feishu_department_id.in_(list(expanded)),
                    DepartmentRole.is_deleted == False,  # noqa: E712
                    Permission.is_deleted == False,  # noqa: E712
                    Role.is_deleted == False,  # noqa: E712
                )
            )
            dept_result = await db.execute(dept_stmt)
            perms.update(dept_result.scalars())

        return perms

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
        self, db: AsyncSession, user_id: uuid.UUID, module: str, resource: str,
        all_role_ids: list[uuid.UUID] | None = None,
    ) -> set[uuid.UUID]:
        """返回用户在该 module+resource 下有至少一条权限的角色 ID 集合。

        合并直接分配 + 部门继承两种来源。
        all_role_ids 由调用方预计算后可避免重复查询。
        """
        # 直接分配的角色
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
        role_ids = set(result.scalars())

        # 部门继承的角色（使用预计算的 all_role_ids 避免重复查询）
        if all_role_ids is None:
            all_role_ids = await self._get_all_role_ids(db, user_id)
        dept_role_ids = set(all_role_ids) - role_ids
        if dept_role_ids:
            dept_stmt = (
                select(RolePermission.role_id)
                .join(Permission, Permission.id == RolePermission.permission_id)
                .where(
                    RolePermission.role_id.in_(list(dept_role_ids)),
                    Permission.module == module,
                    Permission.resource == resource,
                    Permission.is_deleted == False,  # noqa: E712
                )
                .distinct()
            )
            dept_result = await db.execute(dept_stmt)
            role_ids.update(dept_result.scalars())

        return role_ids

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

        role_ids = await self._get_all_role_ids(db, user_id)
        if not role_ids:
            return "self_only"

        # 按 resource 过滤：只保留确实有该资源权限的角色
        if resource:
            relevant_role_ids = await self._get_resource_role_ids(
                db, user_id, module, resource, all_role_ids=role_ids,
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

        # 批量查询所有角色的 overrides
        overrides_stmt = select(RoleDataScopeOverride).where(
            RoleDataScopeOverride.role_id.in_(role_ids)
        )
        overrides_result = await db.execute(overrides_stmt)
        all_overrides: dict[uuid.UUID, dict[str, str]] = {}
        for o in overrides_result.scalars():
            all_overrides.setdefault(o.role_id, {})[o.module] = o.data_scope

        best_scope = "self_only"
        best_priority = 0

        for role in roles:
            overrides = all_overrides.get(role.id, {})
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

        role_ids = await self._get_all_role_ids(db, user_id)
        if not role_ids:
            return {m: "self_only" for m in modules}

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
        # 1. 获取用户所有 distinct (module, resource) 组合（直接分配 + 部门继承）
        direct_stmt = (
            select(Permission.module, Permission.resource)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                Permission.is_deleted == False,  # noqa: E712
                Role.is_deleted == False,  # noqa: E712
            )
        )
        pair_result = await db.execute(direct_stmt)
        pairs = list(pair_result.all())

        # 部门继承的 (module, resource) 组合
        expanded = await self._get_user_expanded_dept_ids(db, user_id)
        if expanded:
            dept_stmt = (
                select(Permission.module, Permission.resource)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .join(Role, Role.id == RolePermission.role_id)
                .join(DepartmentRole, DepartmentRole.role_id == Role.id)
                .where(
                    DepartmentRole.feishu_department_id.in_(list(expanded)),
                    DepartmentRole.is_deleted == False,  # noqa: E712
                    Permission.is_deleted == False,  # noqa: E712
                    Role.is_deleted == False,  # noqa: E712
                )
                .distinct()
            )
            dept_result = await db.execute(dept_stmt)
            pairs.extend(dept_result.all())

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

    # ── 部门树展开辅助 ──

    async def _build_dept_tree(
        self, db: AsyncSession,
    ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        """一次查询构建 ancestor_map 和 descendant_map。

        ancestor_map: child_dept_id → {自身 + 所有祖先 dept_id}
        descendant_map: parent_dept_id → {自身 + 所有子孙 dept_id}

        含环检测和孤儿处理：环上的部门跳过不陷入死循环，
        无根孤儿部门以自身为入口单独展开。
        """
        stmt = select(Department).where(
            Department.is_deleted == False,  # noqa: E712
            Department.status_is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        depts = list(result.scalars())

        all_dept_ids = {d.feishu_department_id for d in depts}

        children: dict[str, list[str]] = {}
        for d in depts:
            pid = d.parent_feishu_department_id or ""
            children.setdefault(pid, []).append(d.feishu_department_id)

        # DFS 构建 ancestor_map（含 visited 防环）
        ancestor_map: dict[str, set[str]] = {}

        def dfs(dept_id: str, ancestors: frozenset[str]) -> None:
            if dept_id in ancestors:
                return  # 检测到环，跳过
            full = ancestors | {dept_id}
            ancestor_map[dept_id] = set(full)
            for child_id in children.get(dept_id, []):
                dfs(child_id, frozenset(full))

        for root_id in children.get("", []):
            dfs(root_id, frozenset())

        # 处理孤儿部门：父部门已删除导致没有从根可达的路径
        for dept_id in all_dept_ids - set(ancestor_map):
            dfs(dept_id, frozenset())

        # 从 ancestor_map 反推 descendant_map
        descendant_map: dict[str, set[str]] = {}
        for child_id, ancestors in ancestor_map.items():
            for ancestor_id in ancestors:
                descendant_map.setdefault(ancestor_id, set()).add(child_id)

        return ancestor_map, descendant_map

    async def _get_user_expanded_dept_ids(
        self, db: AsyncSession, user_id: uuid.UUID,
    ) -> set[str]:
        """获取用户所属部门 ID 展开为「自身 + 所有祖先」的集合。

        供权限查询和角色 ID 合并使用。
        """
        user_stmt = select(User.feishu_department_ids).where(
            User.id == user_id,
            User.is_deleted == False,  # noqa: E712
        )
        user_result = await db.execute(user_stmt)
        row = user_result.one_or_none()
        dept_ids: list[str] = []
        if row and row[0]:
            try:
                dept_ids = json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                dept_ids = []

        if not dept_ids:
            return set()

        ancestor_map, _ = await self._build_dept_tree(db)
        expanded: set[str] = set()
        for did in dept_ids:
            expanded.update(ancestor_map.get(did, {did}))
        return expanded

    # ── 部门角色 CRUD ──

    async def list_role_departments(
        self, db: AsyncSession, role_id: uuid.UUID,
    ) -> list[DepartmentRole]:
        """获取某角色已分配的所有部门。"""
        stmt = select(DepartmentRole).where(
            DepartmentRole.role_id == role_id,
            DepartmentRole.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    async def assign_role_to_department(
        self, db: AsyncSession, role_id: uuid.UUID,
        feishu_department_id: str,
    ) -> DepartmentRole:
        """将角色分配给部门（幂等 + 软删除 reactivate）。"""
        stmt = select(DepartmentRole).where(
            DepartmentRole.role_id == role_id,
            DepartmentRole.feishu_department_id == feishu_department_id,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            if existing.is_deleted:
                existing.is_deleted = False
                await db.flush()
            return existing
        dr = DepartmentRole(
            feishu_department_id=feishu_department_id, role_id=role_id,
        )
        db.add(dr)
        await db.flush()
        return dr

    async def remove_role_from_department(
        self, db: AsyncSession, role_id: uuid.UUID,
        feishu_department_id: str,
    ) -> bool:
        """软删除部门-角色关联。"""
        stmt = select(DepartmentRole).where(
            DepartmentRole.role_id == role_id,
            DepartmentRole.feishu_department_id == feishu_department_id,
            DepartmentRole.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        dr = result.scalar_one_or_none()
        if not dr:
            return False
        dr.is_deleted = True
        await db.flush()
        return True

    async def get_user_ids_by_departments(
        self, db: AsyncSession, feishu_department_ids: list[str],
    ) -> list[uuid.UUID]:
        """获取属于指定部门集合（任一）的所有用户 ID。

        通过 User.feishu_department_ids JSON 数组的 contains 匹配。
        """
        if not feishu_department_ids:
            return []
        from sqlalchemy import or_

        conditions = [
            User.feishu_department_ids.contains(did)
            for did in feishu_department_ids
        ]
        stmt = select(User.id).where(
            or_(*conditions),
            User.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    async def _get_all_role_ids(
        self, db: AsyncSession, user_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """获取用户所有角色 ID（直接分配 + 部门继承）。"""
        user_roles = await self.get_user_roles(db, user_id)
        role_ids = [ur.role_id for ur in user_roles]

        expanded = await self._get_user_expanded_dept_ids(db, user_id)
        if expanded:
            dept_stmt = select(DepartmentRole.role_id).where(
                DepartmentRole.feishu_department_id.in_(list(expanded)),
                DepartmentRole.is_deleted == False,  # noqa: E712
            )
            dept_result = await db.execute(dept_stmt)
            role_ids.extend(dept_result.scalars())

        return list(set(role_ids))
