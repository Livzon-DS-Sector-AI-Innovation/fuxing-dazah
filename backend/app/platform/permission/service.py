"""Permission business logic service."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppException,
    DuplicateException,
    ForbiddenException,
    NotFoundException,
)
from app.platform.permission.cache import invalidate_user_cache
from app.platform.permission.models import Permission, Role
from app.platform.permission.repository import PermissionRepository
from app.platform.permission.schemas import (
    CreateRoleInput,
    UpdateRoleInput,
)

_repo = PermissionRepository()

_ROLE_MANAGE = "permission:role:manage"
_SCOPE_PRIORITY = {
    "all": 4,
    "department_and_children": 3,
    "department": 2,
    "self_only": 1,
}


def _scope_rank(scope: str | None) -> int:
    """数据范围宽窄序；未知值按 0（比仅自己更窄），fail-closed。"""
    return _SCOPE_PRIORITY.get(scope or "", 0)


@dataclass
class _RoleState:
    """用于范围检查的角色状态（当前或提交后）。"""

    permission_ids: list[uuid.UUID]
    data_scope: str
    overrides: dict[str, str]


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
            group_feishu_department_id=data.group_feishu_department_id,
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

    # ── 委派范围检查（role:manage 全权跳过） ──

    async def assert_role_within_actor(
        self,
        db: AsyncSession,
        actor_id: uuid.UUID,
        *,
        permission_ids: list[uuid.UUID] | None = None,
        data_scope: str | None = None,
        overrides: dict[str, str] | None = None,
        existing_role_id: uuid.UUID | None = None,
    ) -> None:
        """非 role:manage 操作者只能操作权限码与数据范围都在自身范围内的角色。

        existing_role_id：检查角色当前状态（更新 / 删除 / 分配时必须传）。
        permission_ids / data_scope / overrides：检查提交后的目标状态（给了才查）。
        """
        actor_codes = await _repo.get_user_permission_codes(db, actor_id)
        if _ROLE_MANAGE in actor_codes:
            # 全权跳过范围比较，但仍校验 id 存在性（防写入悬空关联）
            if permission_ids is not None:
                await self._assert_permission_ids_exist(db, permission_ids)
            return
        actor_scopes = await _repo.get_user_resource_scopes(db, actor_id)

        current: _RoleState | None = None
        if existing_role_id is not None:
            current = await self._load_role_state(db, existing_role_id)
            if current is not None:
                await self._assert_state_within(db, actor_codes, actor_scopes, current)

        if permission_ids is None and data_scope is None and overrides is None:
            return
        after = _RoleState(
            permission_ids=(
                permission_ids
                if permission_ids is not None
                else (current.permission_ids if current else [])
            ),
            data_scope=(
                data_scope
                if data_scope is not None
                else (current.data_scope if current else "self_only")
            ),
            overrides=(
                overrides
                if overrides is not None
                else (current.overrides if current else {})
            ),
        )
        await self._assert_state_within(db, actor_codes, actor_scopes, after)

    async def filter_roles_within_actor(
        self, db: AsyncSession, actor_id: uuid.UUID, roles: list[Role]
    ) -> list[Role]:
        """列表口径：非全权只返回权限码都在自身范围内的角色（不查数据范围）。"""
        actor_codes = await _repo.get_user_permission_codes(db, actor_id)
        if _ROLE_MANAGE in actor_codes:
            return roles
        perms = {p.id: p for p in await _repo.list_permissions(db)}
        result: list[Role] = []
        for role in roles:
            ids = await _repo.get_role_permission_ids(db, role.id)
            codes = {
                perms[pid].code
                for pid in ids
                if pid in perms and not perms[pid].is_deleted
            }
            if codes <= actor_codes:
                result.append(role)
        return result

    async def _load_role_state(
        self, db: AsyncSession, role_id: uuid.UUID
    ) -> _RoleState | None:
        role = await _repo.get_role_by_id(db, role_id)
        if role is None:
            return None
        return _RoleState(
            permission_ids=await _repo.get_role_permission_ids(db, role_id),
            data_scope=role.data_scope,
            overrides=await _repo.get_role_data_scope_overrides(db, role_id),
        )

    async def _assert_permission_ids_exist(
        self, db: AsyncSession, permission_ids: list[uuid.UUID]
    ) -> list[Permission]:
        perms = await _repo.get_permissions_by_ids(db, permission_ids)
        known = {p.id for p in perms}
        missing = [pid for pid in permission_ids if pid not in known]
        if missing:
            raise AppException(
                status_code=400,
                message=f"权限不存在: {', '.join(str(pid) for pid in missing)}",
            )
        return perms

    async def _assert_state_within(
        self,
        db: AsyncSession,
        actor_codes: set[str],
        actor_scopes: dict[str, str],
        state: _RoleState,
    ) -> None:
        perms = await self._assert_permission_ids_exist(db, state.permission_ids)
        # 软删权限不参与授予能力/范围比较（仍允许原样回传保留关联行）
        live = [p for p in perms if not p.is_deleted]
        beyond = sorted({p.code for p in live} - actor_codes)
        if beyond:
            raise ForbiddenException(
                f"无权授予超出自己权限范围的权限: {', '.join(beyond[:5])}"
            )
        for perm in live:
            role_scope = state.overrides.get(perm.module) or state.data_scope
            actor_scope = actor_scopes.get(
                f"{perm.module}:{perm.resource}", "self_only"
            )
            if _scope_rank(role_scope) > _scope_rank(actor_scope):
                raise ForbiddenException(
                    f"角色在模块 {perm.module} 的数据范围超出你的权限范围"
                )

    async def update_role(
        self, db: AsyncSession, role_id: uuid.UUID, data: UpdateRoleInput
    ) -> Role:
        role = await _repo.get_role_by_id(db, role_id)
        if not role:
            raise NotFoundException("角色", str(role_id))

        # 分组是展示关注点而非安全属性：系统内置角色仅允许调整分组，其余字段仍锁定
        group_provided = "group_feishu_department_id" in data.model_fields_set
        if role.is_system:
            other_changes = any(
                getattr(data, field) is not None
                for field in (
                    "name",
                    "description",
                    "data_scope",
                    "permission_ids",
                    "data_scope_overrides",
                )
            )
            if other_changes:
                raise ForbiddenException("系统内置角色不可修改（仅支持调整分组）")

        if group_provided:
            role.group_feishu_department_id = data.group_feishu_department_id

        # 系统角色走到这里时其余字段必为 None，不会被改动
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
        # 权限码/数据范围变化影响所有持有者（直接 + 部门继承）：立即失效缓存，
        # 否则收回的权限最长要等 5 分钟 TTL 才生效
        if (
            data.permission_ids is not None
            or data.data_scope is not None
            or data.data_scope_overrides is not None
        ):
            for uid in await _repo.get_all_user_ids_for_role(db, role_id):
                await invalidate_user_cache(str(uid))

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
        if role.code == "super_admin":
            # 超管判定只认直接分配；部门分配会产生「有全部权限码但不是超管」的账号
            raise ForbiddenException("超级管理员角色不支持部门分配")

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
