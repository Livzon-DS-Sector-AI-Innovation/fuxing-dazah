"""用户权限合并与数据范围计算业务测试。

覆盖业务场景：
- 直接分配：用户角色权限合并为权限编码集合
- 部门继承：角色分配给部门后，部门成员自动继承；父部门角色对子部门成员生效（层级穿透）
- 合并去重：直接分配与部门继承的权限合并
- 数据范围：无角色默认 self_only；多角色取最宽松（all > department_and_children
  > department > self_only）；模块级 override 覆盖角色默认范围；
  指定 resource 时仅统计拥有该资源权限的角色
- 权限软删除后不再参与查询
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.permission.repository import PermissionRepository
from app.platform.permission.schemas import CreateRoleInput
from app.platform.permission.service import PermissionService

_repo = PermissionRepository()
_service = PermissionService()


class TestDirectPermissionMerge:
    async def test_permissions_from_direct_roles(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user,
    ) -> None:
        """用户通过直接分配的角色获得权限编码集合。"""
        perm1 = await make_permission()
        perm2 = await make_permission()
        role = await make_role()
        await _repo.set_role_permissions(db_session, role.id, [perm1.id, perm2.id])
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, role.id)

        perms = await _repo.get_user_permission_codes(db_session, user.id)
        assert perms == {perm1.code, perm2.code}

    async def test_permissions_merge_across_roles(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user,
    ) -> None:
        """多个角色的权限合并为并集。"""
        p1 = await make_permission()
        p2 = await make_permission(module="safety")
        r1 = await make_role()
        r2 = await make_role()
        await _repo.set_role_permissions(db_session, r1.id, [p1.id])
        await _repo.set_role_permissions(db_session, r2.id, [p2.id])
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, r1.id)
        await _service.assign_role_to_user(db_session, user.id, r2.id)

        perms = await _repo.get_user_permission_codes(db_session, user.id)
        assert perms == {p1.code, p2.code}

    async def test_removed_role_loses_permissions(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user,
    ) -> None:
        """移除用户角色后权限随之消失。"""
        perm = await make_permission()
        role = await make_role()
        await _repo.set_role_permissions(db_session, role.id, [perm.id])
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, role.id)
        await _service.remove_role_from_user(db_session, user.id, role.id)

        assert await _repo.get_user_permission_codes(db_session, user.id) == set()


class TestDepartmentInheritance:
    async def test_role_assigned_to_own_department(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user,
    ) -> None:
        """角色分配给用户所在部门，用户继承该角色权限。"""
        perm = await make_permission()
        role = await make_role()
        await _repo.set_role_permissions(db_session, role.id, [perm.id])
        await _service.assign_role_to_department(
            db_session, role.id, ["od-dept-a"],
        )
        user = await make_user(dept_ids=["od-dept-a"])

        perms = await _repo.get_user_permission_codes(db_session, user.id)
        assert perm.code in perms

    async def test_parent_department_role_inherited_by_child_member(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user, make_department,
    ) -> None:
        """父部门角色对子部门成员生效（层级穿透）。"""
        await make_department("od-parent", parent_id=None)
        await make_department("od-child", parent_id="od-parent")
        perm = await make_permission()
        role = await make_role()
        await _repo.set_role_permissions(db_session, role.id, [perm.id])
        await _service.assign_role_to_department(
            db_session, role.id, ["od-parent"],
        )
        child_user = await make_user(dept_ids=["od-child"])

        perms = await _repo.get_user_permission_codes(db_session, child_user.id)
        assert perm.code in perms

    async def test_direct_and_department_permissions_dedup(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user,
    ) -> None:
        """直接分配与部门继承同一权限时合并去重。"""
        perm = await make_permission()
        role = await make_role()
        await _repo.set_role_permissions(db_session, role.id, [perm.id])
        await _service.assign_role_to_department(
            db_session, role.id, ["od-dept-a"],
        )
        user = await make_user(dept_ids=["od-dept-a"])
        await _service.assign_role_to_user(db_session, user.id, role.id)

        perms = await _repo.get_user_permission_codes(db_session, user.id)
        assert perms == {perm.code}

    async def test_unrelated_user_has_no_permissions(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user,
    ) -> None:
        """与部门无关的用户不继承部门角色权限。"""
        perm = await make_permission()
        role = await make_role()
        await _repo.set_role_permissions(db_session, role.id, [perm.id])
        await _service.assign_role_to_department(
            db_session, role.id, ["od-dept-a"],
        )
        other_user = await make_user(dept_ids=["od-other"])

        assert await _repo.get_user_permission_codes(db_session, other_user.id) == set()

    async def test_deleted_department_role_no_longer_inherited(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user,
    ) -> None:
        """移除部门角色后，部门成员不再继承权限。"""
        perm = await make_permission()
        role = await make_role()
        await _repo.set_role_permissions(db_session, role.id, [perm.id])
        await _service.assign_role_to_department(
            db_session, role.id, ["od-dept-a"],
        )
        user = await make_user(dept_ids=["od-dept-a"])
        assert perm.code in await _repo.get_user_permission_codes(db_session, user.id)

        await _service.remove_role_from_department(
            db_session, role.id, "od-dept-a",
        )
        assert await _repo.get_user_permission_codes(db_session, user.id) == set()


class TestDataScope:
    async def test_no_role_defaults_self_only(
        self, db_session: AsyncSession, make_user,
    ) -> None:
        """无任何角色的用户数据范围为 self_only。"""
        user = await make_user()
        scope = await _repo.get_effective_data_scope(
            db_session, user.id, "equipment",
        )
        assert scope == "self_only"

    async def test_role_data_scope_applied(
        self, db_session: AsyncSession,
        make_role, make_user,
    ) -> None:
        """角色的数据范围作用于该模块。"""
        role = await make_role(data_scope="department")
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, role.id)
        scope = await _repo.get_effective_data_scope(
            db_session, user.id, "equipment",
        )
        assert scope == "department"

    async def test_widest_scope_wins(
        self, db_session: AsyncSession,
        make_role, make_user,
    ) -> None:
        """多角色时取最宽松的数据范围：all 优先于 department。"""
        r1 = await make_role(data_scope="department")
        r2 = await make_role(data_scope="all")
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, r1.id)
        await _service.assign_role_to_user(db_session, user.id, r2.id)
        scope = await _repo.get_effective_data_scope(
            db_session, user.id, "equipment",
        )
        assert scope == "all"

    async def test_scope_priority_order(
        self, db_session: AsyncSession,
        make_role, make_user,
    ) -> None:
        """数据范围优先级：department_and_children 高于 department。"""
        r1 = await make_role(data_scope="department")
        r2 = await make_role(data_scope="department_and_children")
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, r1.id)
        await _service.assign_role_to_user(db_session, user.id, r2.id)
        scope = await _repo.get_effective_data_scope(
            db_session, user.id, "equipment",
        )
        assert scope == "department_and_children"

    async def test_module_override_beats_role_default(
        self, db_session: AsyncSession,
        make_user,
    ) -> None:
        """模块级数据范围覆盖优先于角色默认范围。"""
        role = await _service.create_role(
            db_session,
            CreateRoleInput(
                code="inspector_override",
                name="覆盖角色",
                data_scope="self_only",
                data_scope_overrides={"equipment": "all"},
            ),
        )
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, role.id)
        scope = await _repo.get_effective_data_scope(
            db_session, user.id, "equipment",
        )
        assert scope == "all"
        # 未配置覆盖的模块仍用角色默认范围
        other_scope = await _repo.get_effective_data_scope(
            db_session, user.id, "safety",
        )
        assert other_scope == "self_only"

    async def test_resource_filter_ignores_irrelevant_roles(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user,
    ) -> None:
        """指定 resource 时仅统计拥有该资源权限的角色，避免无关角色污染范围。"""
        perm_equip = await make_permission()  # 默认 module=equipment, resource=res
        perm_safety = await make_permission(module="safety")
        r_equip = await make_role(data_scope="self_only")
        r_safety = await make_role(data_scope="all")
        await _repo.set_role_permissions(db_session, r_equip.id, [perm_equip.id])
        await _repo.set_role_permissions(db_session, r_safety.id, [perm_safety.id])
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, r_equip.id)
        await _service.assign_role_to_user(db_session, user.id, r_safety.id)

        # 模块级：所有角色都统计 → all
        module_scope = await _repo.get_effective_data_scope(
            db_session, user.id, "equipment",
        )
        assert module_scope == "all"
        # 资源级：只有拥有 equipment:res 权限的角色参与 → self_only
        resource_scope = await _repo.get_effective_data_scope(
            db_session, user.id, "equipment", resource="res",
        )
        assert resource_scope == "self_only"

    async def test_batch_data_scopes(
        self, db_session: AsyncSession,
        make_user,
    ) -> None:
        """批量查询多个模块的数据范围。"""
        role = await _service.create_role(
            db_session,
            CreateRoleInput(
                code="batch_scopes",
                name="批量范围",
                data_scope="department",
                data_scope_overrides={"equipment": "all"},
            ),
        )
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, role.id)
        scopes = await _repo.get_user_all_data_scopes(
            db_session, user.id, ["equipment", "safety"],
        )
        assert scopes["equipment"] == "all"
        assert scopes["safety"] == "department"


class TestDeletedRecords:
    async def test_deleted_permission_not_in_merge(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user,
    ) -> None:
        """权限软删除后不再出现在用户的权限集合中。"""
        perm = await make_permission()
        role = await make_role()
        await _repo.set_role_permissions(db_session, role.id, [perm.id])
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, role.id)

        perm.is_deleted = True
        await db_session.flush()
        assert await _repo.get_user_permission_codes(db_session, user.id) == set()
