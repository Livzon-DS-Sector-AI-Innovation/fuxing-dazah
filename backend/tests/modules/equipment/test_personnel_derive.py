"""derive_maintainer_for_equipment 维修人自动推导测试。

覆盖：无 repair 角色返回 None、无分类约束人员入选、分类约束匹配
（设备挂父分类时绑定子孙分类的人员命中）、约束不匹配被排除、
候选人未绑定平台账号（user_id 为空）跳过、跨部门人员不入选。
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import (
    Equipment,
    EquipmentCategory,
    EquipmentCategoryLink,
    EquipmentPersonnel,
    EquipmentPersonnelCategory,
    EquipmentPersonnelRole,
    EquipmentRole,
    Location,
)
from app.modules.equipment.service.personnel import (
    REPAIR_ROLE_CODE,
    derive_maintainer_for_equipment,
)
from app.platform.identity.models import Department, User


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def repair_role(db_session: AsyncSession) -> EquipmentRole:
    """复用已存在的 repair 角色。

    该角色是自动指派功能的预置配置（code 上有唯一索引），已配置过的库
    （含开发库）里它已存在，直接 INSERT 会撞唯一键。
    """
    existing = (
        await db_session.execute(
            select(EquipmentRole).where(
                EquipmentRole.code == REPAIR_ROLE_CODE,
                EquipmentRole.is_deleted == False,  # noqa: E712
            )
        )
    ).scalars().first()
    if existing is not None:
        return existing

    role = EquipmentRole(name="维修工", code=REPAIR_ROLE_CODE)
    db_session.add(role)
    await db_session.flush()
    return role


@pytest.fixture
async def department(db_session: AsyncSession) -> Department:
    """推导用部门：自动指派只在设备所属部门内选人。"""
    dept = Department(
        name=f"推导部-{_uid()}", feishu_department_id=f"od-d-{_uid()}"
    )
    db_session.add(dept)
    await db_session.flush()
    return dept


@pytest.fixture
async def maintainer(db_session: AsyncSession) -> User:
    user = User(name="维修工甲", employee_no=f"EMP-M-{_uid()}")
    db_session.add(user)
    await db_session.flush()
    return user


async def _add_personnel(
    db_session: AsyncSession,
    role: EquipmentRole,
    *,
    user_id: uuid.UUID | None,
    department: str | None,
    name: str = "维修工甲",
) -> EquipmentPersonnel:
    person = EquipmentPersonnel(
        name=name,
        user_id=user_id,
        employee_no=f"PP-{_uid()}",
        department=department,
    )
    db_session.add(person)
    await db_session.flush()
    db_session.add(
        EquipmentPersonnelRole(personnel_id=person.id, role_id=role.id)
    )
    await db_session.flush()
    return person


async def _add_equipment(
    db_session: AsyncSession,
    department_id: uuid.UUID | None,
    *category_ids: uuid.UUID,
) -> Equipment:
    location = Location(name="推导车间", code=f"WS-{_uid()}")
    db_session.add(location)
    await db_session.flush()
    eq = Equipment(
        equipment_no=f"EQ-{_uid()}",
        name="推导用反应釜",
        location_id=location.id,
        status="完好",
        department_id=department_id,
    )
    db_session.add(eq)
    await db_session.flush()
    for cid in category_ids:
        db_session.add(
            EquipmentCategoryLink(equipment_id=eq.id, category_id=cid)
        )
    await db_session.flush()
    return eq


async def test_no_repair_role_returns_none(
    db_session: AsyncSession, department: Department
) -> None:
    """未创建 repair 角色时无法推导，返回 None（不阻塞建单）。

    开发库里 repair 角色已存在（真名配置），这里在事务内临时软删制造该分支，
    用例结束由 db_session 夹具回滚恢复。
    """
    for existing in (
        await db_session.execute(
            select(EquipmentRole).where(EquipmentRole.code == REPAIR_ROLE_CODE)
        )
    ).scalars().all():
        existing.is_deleted = True
    await db_session.flush()

    eq = await _add_equipment(db_session, department.id)
    assert await derive_maintainer_for_equipment(db_session, eq) is None


async def test_equipment_without_department_returns_none(
    db_session: AsyncSession,
    repair_role: EquipmentRole,
    maintainer: User,
) -> None:
    """设备没有归属部门时无人可选（跨部门指派会导致被指派人无权操作）。"""
    eq = await _add_equipment(db_session, None)
    await _add_personnel(
        db_session, repair_role, user_id=maintainer.id, department="推导部"
    )
    assert await derive_maintainer_for_equipment(db_session, eq) is None


async def test_unconstrained_personnel_selected(
    db_session: AsyncSession,
    repair_role: EquipmentRole,
    maintainer: User,
    department: Department,
) -> None:
    """无分类约束的同部门 repair 人员对任何设备（含无分类设备）可选。"""
    eq = await _add_equipment(db_session, department.id)
    await _add_personnel(
        db_session,
        repair_role,
        user_id=maintainer.id,
        department=department.name,
    )
    assert (
        await derive_maintainer_for_equipment(db_session, eq)
        == maintainer.id
    )


async def test_other_department_personnel_excluded(
    db_session: AsyncSession,
    repair_role: EquipmentRole,
    maintainer: User,
    department: Department,
) -> None:
    """部门不同的人不入选：派过去他也没有该设备的操作权限。"""
    eq = await _add_equipment(db_session, department.id)
    await _add_personnel(
        db_session,
        repair_role,
        user_id=maintainer.id,
        department=f"别的部-{_uid()}",
    )
    assert await derive_maintainer_for_equipment(db_session, eq) is None


async def test_child_category_binding_matches_parent_equipment(
    db_session: AsyncSession,
    repair_role: EquipmentRole,
    maintainer: User,
    department: Department,
) -> None:
    """设备挂父分类时，约束绑定其子孙分类的人员命中（子分类展开）。"""
    parent = EquipmentCategory(name="机械设备", code=f"CAT-P-{_uid()}")
    db_session.add(parent)
    await db_session.flush()
    child = EquipmentCategory(
        name="泵类", code=f"CAT-C-{_uid()}", parent_id=parent.id
    )
    db_session.add(child)
    await db_session.flush()

    eq = await _add_equipment(db_session, department.id, parent.id)
    person = await _add_personnel(
        db_session,
        repair_role,
        user_id=maintainer.id,
        department=department.name,
    )
    db_session.add(
        EquipmentPersonnelCategory(
            personnel_id=person.id, role_id=repair_role.id, category_id=child.id
        )
    )
    await db_session.flush()

    assert (
        await derive_maintainer_for_equipment(db_session, eq)
        == maintainer.id
    )


async def test_mismatched_category_binding_excluded(
    db_session: AsyncSession,
    repair_role: EquipmentRole,
    maintainer: User,
    department: Department,
) -> None:
    """约束绑定的分类与设备分类不相交的人员被排除。"""
    cat_a = EquipmentCategory(name="电气设备", code=f"CAT-A-{_uid()}")
    cat_b = EquipmentCategory(name="动力设备", code=f"CAT-B-{_uid()}")
    db_session.add_all([cat_a, cat_b])
    await db_session.flush()

    eq = await _add_equipment(db_session, department.id, cat_a.id)
    person = await _add_personnel(
        db_session,
        repair_role,
        user_id=maintainer.id,
        department=department.name,
    )
    db_session.add(
        EquipmentPersonnelCategory(
            personnel_id=person.id, role_id=repair_role.id, category_id=cat_b.id
        )
    )
    await db_session.flush()

    assert await derive_maintainer_for_equipment(db_session, eq) is None


async def test_personnel_without_user_id_skipped(
    db_session: AsyncSession,
    repair_role: EquipmentRole,
    department: Department,
) -> None:
    """人员池记录未绑定平台账号（user_id 为空）时不可指派。"""
    eq = await _add_equipment(db_session, department.id)
    await _add_personnel(
        db_session,
        repair_role,
        user_id=None,
        department=department.name,
    )
    assert await derive_maintainer_for_equipment(db_session, eq) is None
