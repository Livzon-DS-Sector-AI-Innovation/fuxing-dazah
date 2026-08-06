"""角色管理与用户/部门角色分配业务测试。

覆盖业务场景：
- 创建角色：基础创建、绑定权限、设置数据范围覆盖；编码重复拒绝；编码格式校验
- 更新角色：修改名称/数据范围；全量替换权限；系统内置角色不可修改
- 删除角色：软删除后不可查；系统内置角色不可删除；不存在抛 NotFound
- 用户角色分配：分配/重复分配幂等/移除
- 部门角色分配：分配/重复分配幂等/软删后重新激活/移除
- 角色编码唯一（软删后可复用）
"""

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DuplicateException,
    ForbiddenException,
    NotFoundException,
)
from app.platform.permission.repository import PermissionRepository
from app.platform.permission.schemas import (
    CreateRoleInput,
    UpdateRoleInput,
)
from app.platform.permission.service import PermissionService

_service = PermissionService()
_repo = PermissionRepository()


class TestCreateRole:
    async def test_create_basic(
        self, db_session: AsyncSession, make_permission,
    ) -> None:
        """创建角色后可通过 ID 查询，默认数据范围为 department。"""
        perm = await make_permission()
        role = await _service.create_role(
            db_session,
            CreateRoleInput(
                code="equipment_inspector",
                name="设备巡检员",
                permission_ids=[perm.id],
            ),
        )
        assert role.code == "equipment_inspector"
        assert role.data_scope == "department"
        assert await _repo.get_role_permission_ids(db_session, role.id) == [perm.id]

    async def test_create_duplicate_code_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """同一角色编码创建两次，第二次抛 DuplicateException。"""
        await _service.create_role(
            db_session, CreateRoleInput(code="inspector", name="巡检员"),
        )
        with pytest.raises(DuplicateException):
            await _service.create_role(
                db_session, CreateRoleInput(code="inspector", name="另一个"),
            )

    async def test_create_code_format_validated(self) -> None:
        """角色编码必须以小写字母开头且仅含小写字母/数字/下划线。"""
        with pytest.raises(ValidationError):
            CreateRoleInput(code="Equipment-1", name="x")
        with pytest.raises(ValidationError):
            CreateRoleInput(code="1equipment", name="x")
        # 合法编码不抛错
        CreateRoleInput(code="equipment_inspector", name="x")

    async def test_create_with_data_scope_overrides(
        self, db_session: AsyncSession,
    ) -> None:
        """创建角色时设置的模块数据范围覆盖可读回。"""
        role = await _service.create_role(
            db_session,
            CreateRoleInput(
                code="inspector_all",
                name="全量巡检",
                data_scope="self_only",
                data_scope_overrides={"equipment": "all", "safety": "department"},
            ),
        )
        overrides = await _repo.get_role_data_scope_overrides(db_session, role.id)
        assert overrides == {"equipment": "all", "safety": "department"}


class TestUpdateRole:
    async def test_update_name_and_data_scope(
        self, db_session: AsyncSession, make_role,
    ) -> None:
        """更新角色的名称与数据范围。"""
        role = await make_role(data_scope="department")
        updated = await _service.update_role(
            db_session, role.id,
            UpdateRoleInput(name="新名称", data_scope="all"),
        )
        assert updated.name == "新名称"
        assert updated.data_scope == "all"

    async def test_update_replaces_permissions(
        self, db_session: AsyncSession, make_role, make_permission,
    ) -> None:
        """更新权限列表为全量替换：旧权限被清空。"""
        role = await make_role()
        p1 = await make_permission()
        p2 = await make_permission()
        await _repo.set_role_permissions(db_session, role.id, [p1.id])

        await _service.update_role(
            db_session, role.id, UpdateRoleInput(permission_ids=[p2.id]),
        )
        assert await _repo.get_role_permission_ids(db_session, role.id) == [p2.id]

    async def test_update_system_role_forbidden(
        self, db_session: AsyncSession, make_role,
    ) -> None:
        """系统内置角色不可修改。"""
        role = await make_role(is_system=True)
        with pytest.raises(ForbiddenException, match="不可修改"):
            await _service.update_role(
                db_session, role.id, UpdateRoleInput(name="x"),
            )

    async def test_update_nonexistent_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """更新不存在的角色抛 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await _service.update_role(
                db_session, uuid.uuid4(), UpdateRoleInput(name="x"),
            )


class TestDeleteRole:
    async def test_delete_soft(
        self, db_session: AsyncSession, make_role,
    ) -> None:
        """删除角色后通过仓库查询返回 None。"""
        role = await make_role()
        await _service.delete_role(db_session, role.id)
        assert await _repo.get_role_by_id(db_session, role.id) is None

    async def test_delete_removes_user_assignments(
        self, db_session: AsyncSession, make_role, make_user,
    ) -> None:
        """删除角色时同步移除用户的角色分配（用户不再拥有该角色）。"""
        role = await make_role()
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, role.id)
        await _service.delete_role(db_session, role.id)
        assert await _repo.get_user_roles(db_session, user.id) == []

    async def test_delete_system_role_forbidden(
        self, db_session: AsyncSession, make_role,
    ) -> None:
        """系统内置角色不可删除。"""
        role = await make_role(is_system=True)
        with pytest.raises(ForbiddenException, match="不可删除"):
            await _service.delete_role(db_session, role.id)

    async def test_delete_nonexistent_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """删除不存在的角色抛 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await _service.delete_role(db_session, uuid.uuid4())


class TestUserRoleAssignment:
    async def test_assign_and_list(
        self, db_session: AsyncSession, make_role, make_user,
    ) -> None:
        """分配角色后可在用户角色列表中查到。"""
        role = await make_role()
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, role.id)
        user_roles = await _repo.get_user_roles(db_session, user.id)
        assert [ur.role_id for ur in user_roles] == [role.id]

    async def test_assign_twice_idempotent(
        self, db_session: AsyncSession, make_role, make_user,
    ) -> None:
        """同一角色重复分配不产生重复记录。"""
        role = await make_role()
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, role.id)
        await _service.assign_role_to_user(db_session, user.id, role.id)
        assert len(await _repo.get_user_roles(db_session, user.id)) == 1

    async def test_assign_with_department_scoped_role(
        self, db_session: AsyncSession, make_role, make_user,
    ) -> None:
        """可分配限定在特定部门生效的角色（department_id 非空）。"""
        role = await make_role()
        user = await make_user()
        dept_id = uuid.uuid4()
        await _service.assign_role_to_user(
            db_session, user.id, role.id, department_id=dept_id,
        )
        user_roles = await _repo.get_user_roles(db_session, user.id)
        assert user_roles[0].department_id == dept_id

    async def test_assign_nonexistent_role_rejected(
        self, db_session: AsyncSession, make_user,
    ) -> None:
        """给用户分配不存在的角色抛 NotFoundException。"""
        user = await make_user()
        with pytest.raises(NotFoundException):
            await _service.assign_role_to_user(
                db_session, user.id, uuid.uuid4(),
            )

    async def test_remove_role(
        self, db_session: AsyncSession, make_role, make_user,
    ) -> None:
        """移除用户角色后列表中不再包含该角色。"""
        role = await make_role()
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, role.id)
        await _service.remove_role_from_user(db_session, user.id, role.id)
        assert await _repo.get_user_roles(db_session, user.id) == []


class TestDepartmentRoleAssignment:
    async def test_assign_and_list(
        self, db_session: AsyncSession, make_role,
    ) -> None:
        """角色分配给部门后可在该角色的部门列表中查到。"""
        role = await make_role()
        await _service.assign_role_to_department(
            db_session, role.id, ["od-dept-a"],
        )
        dept_roles = await _repo.list_role_departments(db_session, role.id)
        assert [dr.feishu_department_id for dr in dept_roles] == ["od-dept-a"]

    async def test_assign_twice_idempotent(
        self, db_session: AsyncSession, make_role,
    ) -> None:
        """同一部门重复分配同一角色不产生重复记录。"""
        role = await make_role()
        await _service.assign_role_to_department(
            db_session, role.id, ["od-dept-a"],
        )
        await _service.assign_role_to_department(
            db_session, role.id, ["od-dept-a"],
        )
        assert len(await _repo.list_role_departments(db_session, role.id)) == 1

    async def test_remove_then_reassign_reactivates(
        self, db_session: AsyncSession, make_role,
    ) -> None:
        """移除部门角色后再重新分配可恢复（软删除重新激活）。"""
        role = await make_role()
        await _service.assign_role_to_department(
            db_session, role.id, ["od-dept-a"],
        )
        await _service.remove_role_from_department(
            db_session, role.id, "od-dept-a",
        )
        assert await _repo.list_role_departments(db_session, role.id) == []
        await _service.assign_role_to_department(
            db_session, role.id, ["od-dept-a"],
        )
        assert len(await _repo.list_role_departments(db_session, role.id)) == 1

    async def test_remove_nonexistent_rejected(
        self, db_session: AsyncSession, make_role,
    ) -> None:
        """移除不存在的部门角色关联抛 NotFoundException。"""
        role = await make_role()
        with pytest.raises(NotFoundException):
            await _service.remove_role_from_department(
                db_session, role.id, "od-unknown",
            )


class TestRoleCodeReuse:
    async def test_soft_deleted_code_reusable(
        self, db_session: AsyncSession,
    ) -> None:
        """角色软删除后可复用同一编码创建新角色。"""
        role = await _service.create_role(
            db_session, CreateRoleInput(code="reusable_role", name="旧角色"),
        )
        await _service.delete_role(db_session, role.id)
        role2 = await _service.create_role(
            db_session, CreateRoleInput(code="reusable_role", name="新角色"),
        )
        assert role2.id != role.id
