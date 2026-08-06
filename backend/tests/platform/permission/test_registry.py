"""权限注册表同步业务测试（sync_permissions）。

覆盖业务场景：
- 代码新声明的权限插入数据库
- 已有权限的名称/模块等字段变化时更新
- 代码中移除的权限软删除
- 软删除后重新声明的权限恢复
- 系统内置权限（is_system）即使代码移除也不软删
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.permission.registry as registry_mod
from app.platform.permission.models import Permission
from app.platform.permission.registry import PermissionDef, sync_permissions


async def _db_permission_by_code(
    db: AsyncSession, code: str,
) -> Permission | None:
    stmt = select(Permission).where(Permission.code == code)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _def(code: str, name: str | None = None) -> PermissionDef:
    parts = code.split(":")
    return PermissionDef(
        code=code,
        name=name or f"权限{code}",
        module=parts[0],
        resource=parts[1],
        action=parts[2],
    )


async def test_sync_inserts_new_permissions(
    db_session: AsyncSession, monkeypatch,
) -> None:
    """代码新声明的权限在同步后写入数据库。"""
    codes = [f"testmod:res:{uuid.uuid4().hex[:8]}" for _ in range(2)]
    defs = [_def(c) for c in codes]
    monkeypatch.setattr(registry_mod, "_discover_permissions", lambda: defs)

    await sync_permissions(db_session)

    for code in codes:
        perm = await _db_permission_by_code(db_session, code)
        assert perm is not None
        assert perm.is_deleted is False


async def test_sync_updates_changed_fields(
    db_session: AsyncSession, monkeypatch,
) -> None:
    """同名权限的名称变化时更新数据库记录。"""
    code = f"testmod:res:{uuid.uuid4().hex[:8]}"
    db_session.add(Permission(
        code=code, name="旧名称",
        module="testmod", resource="res", action="read",
    ))
    await db_session.flush()
    monkeypatch.setattr(
        registry_mod, "_discover_permissions", lambda: [_def(code, name="新名称")],
    )

    await sync_permissions(db_session)

    perm = await _db_permission_by_code(db_session, code)
    assert perm is not None and perm.name == "新名称"


async def test_sync_soft_deletes_removed_permissions(
    db_session: AsyncSession, monkeypatch,
) -> None:
    """代码中移除的权限在同步后被软删除。"""
    code = f"testmod:res:{uuid.uuid4().hex[:8]}"
    db_session.add(Permission(
        code=code, name="即将移除",
        module="testmod", resource="res", action="read",
    ))
    await db_session.flush()
    monkeypatch.setattr(registry_mod, "_discover_permissions", lambda: [])

    await sync_permissions(db_session)

    perm = await _db_permission_by_code(db_session, code)
    assert perm is not None and perm.is_deleted is True


async def test_sync_reactivates_deleted_permission(
    db_session: AsyncSession, monkeypatch,
) -> None:
    """已软删除的权限被代码重新声明后恢复为可用。"""
    code = f"testmod:res:{uuid.uuid4().hex[:8]}"
    perm = Permission(
        code=code, name="回归权限",
        module="testmod", resource="res", action="read",
        is_deleted=True,
    )
    db_session.add(perm)
    await db_session.flush()
    monkeypatch.setattr(
        registry_mod, "_discover_permissions", lambda: [_def(code)],
    )

    await sync_permissions(db_session)

    refreshed = await _db_permission_by_code(db_session, code)
    assert refreshed is not None and refreshed.is_deleted is False


async def test_sync_preserves_system_permissions(
    db_session: AsyncSession, monkeypatch,
) -> None:
    """系统内置权限（is_system）即使代码不再声明也不会被软删。"""
    code = f"testmod:res:{uuid.uuid4().hex[:8]}"
    db_session.add(Permission(
        code=code, name="系统权限",
        module="testmod", resource="res", action="manage",
        is_system=True,
    ))
    await db_session.flush()
    monkeypatch.setattr(registry_mod, "_discover_permissions", lambda: [])

    await sync_permissions(db_session)

    perm = await _db_permission_by_code(db_session, code)
    assert perm is not None and perm.is_deleted is False
