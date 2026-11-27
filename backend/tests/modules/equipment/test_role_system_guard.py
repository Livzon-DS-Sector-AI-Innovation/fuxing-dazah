"""系统内置角色守卫测试。

is_system 角色是自动派单/候选人筛选的硬依赖：不可删除、不可停用、
作用域锁定；名称与描述允许调整。用独立编码的临时内置角色测试，
不触碰库中真实的 repair 角色（可能已有人员绑定）。
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.equipment.models.personnel import EquipmentRole
from app.modules.equipment.schemas.personnel import RoleUpdate
from app.modules.equipment.service.personnel import (
    delete_role,
    update_role,
)


def _uid() -> str:
    return uuid.uuid4().hex[:8]


async def _make_role(
    db_session: AsyncSession, *, is_system: bool
) -> EquipmentRole:
    """建临时角色（独立 code 避开唯一索引与真实 repair 行）。"""
    role = EquipmentRole(
        name=f"守卫角色{_uid()}",
        code=f"guard-{_uid()}",
        scope="maintenance",
        is_system=is_system,
    )
    db_session.add(role)
    await db_session.flush()
    return role


async def test_system_role_cannot_be_deleted(
    db_session: AsyncSession,
) -> None:
    """内置角色删除被拒,软删不落地。"""
    role = await _make_role(db_session, is_system=True)
    with pytest.raises(AppException) as exc_info:
        await delete_role(db_session, role.id)
    assert "不可删除" in exc_info.value.message

    refetched = (
        await db_session.execute(
            select(EquipmentRole).where(EquipmentRole.id == role.id)
        )
    ).scalars().first()
    assert refetched is not None and refetched.is_deleted is False


async def test_system_role_cannot_be_deactivated(
    db_session: AsyncSession,
) -> None:
    """内置角色停用被拒。"""
    role = await _make_role(db_session, is_system=True)
    with pytest.raises(AppException) as exc_info:
        await update_role(db_session, role.id, RoleUpdate(is_active=False))
    assert "不可停用" in exc_info.value.message


async def test_system_role_scope_locked(db_session: AsyncSession) -> None:
    """内置角色改作用域被拒;传回原值不算修改,应放行。"""
    role = await _make_role(db_session, is_system=True)
    with pytest.raises(AppException) as exc_info:
        await update_role(db_session, role.id, RoleUpdate(scope="global"))
    assert "作用域" in exc_info.value.message

    # 传回当前值（前端锁定后 diff 不会产生,后端不应误伤）
    result = await update_role(
        db_session, role.id, RoleUpdate(scope=role.scope)
    )
    assert result.scope == role.scope


async def test_system_role_name_and_description_editable(
    db_session: AsyncSession,
) -> None:
    """内置角色名称/描述允许调整。"""
    role = await _make_role(db_session, is_system=True)
    result = await update_role(
        db_session,
        role.id,
        RoleUpdate(name="车间叫法", description="一线习惯叫法"),
    )
    assert result.name == "车间叫法"
    assert result.description == "一线习惯叫法"
    assert result.is_active is True  # 未动停用状态


async def test_normal_role_still_deletable(db_session: AsyncSession) -> None:
    """普通角色守卫不生效:可停用、可删除。"""
    role = await _make_role(db_session, is_system=False)

    stopped = await update_role(
        db_session, role.id, RoleUpdate(is_active=False, scope="global")
    )
    assert stopped.is_active is False
    assert stopped.scope == "global"

    await delete_role(db_session, role.id)
    refetched = (
        await db_session.execute(
            select(EquipmentRole).where(EquipmentRole.id == role.id)
        )
    ).scalars().first()
    assert refetched is not None and refetched.is_deleted is True
