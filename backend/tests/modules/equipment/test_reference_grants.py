"""设备跨模块引用授权业务测试。"""

import uuid
from collections.abc import Awaitable, Callable, Sequence

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ForbiddenException
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import Equipment, EquipmentReferenceGrant, Location
from app.modules.equipment.public_api import (
    get_equipment_references_by_ids,
    list_equipment_references,
    validate_equipment_references,
)
from app.modules.equipment.service import reference as reference_service
from app.platform.identity.models import User
from app.shared import module_registry
from app.shared.module_registry import ModuleDefinition


def _code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def _equipment(
    db: AsyncSession,
    *,
    department_id: uuid.UUID | None = None,
    status: str = "完好",
) -> Equipment:
    location = Location(name="引用测试位置", code=_code("LOC"))
    db.add(location)
    await db.flush()
    equipment = Equipment(
        equipment_no=_code("EQ"),
        name="跨模块测试设备",
        location_id=location.id,
        department_id=department_id,
        status=status,
    )
    db.add(equipment)
    await db.flush()
    return equipment


def _ctx(
    user: User,
    *,
    scope: str = "all",
    departments: Sequence[uuid.UUID] | None = None,
) -> EquipmentAccessContext:
    return EquipmentAccessContext(
        user=user,
        data_scope=scope,
        visible_department_ids=list(departments or []),
    )


def test_reference_target_modules_are_dynamic() -> None:
    modules = reference_service.list_reference_target_modules()
    codes = {module["code"] for module in modules}
    assert "equipment" not in codes
    assert "toolbox" not in codes
    assert {"safety", "environment", "quality", "warehouse", "meter"} <= codes


def test_new_registry_module_needs_no_reference_code_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """运行时从注册表读取，新增业务模块不需要增加专用授权字段或分支。"""
    extension = ModuleDefinition(
        code="custom_business",
        name="扩展业务",
        path="/custom-business",
        db_schema="custom_business",
        owner_hint="扩展负责人",
        description="测试动态业务模块",
    )
    monkeypatch.setattr(
        module_registry,
        "BUSINESS_MODULES",
        (*module_registry.BUSINESS_MODULES, extension),
    )

    assert reference_service.validate_target_module("CUSTOM_BUSINESS") == (
        "custom_business"
    )
    assert "custom_business" in {
        module["code"] for module in reference_service.list_reference_target_modules()
    }


@pytest.mark.parametrize("target", ["", "not-a-module", "equipment", "toolbox"])
def test_invalid_reference_target_rejected(target: str) -> None:
    with pytest.raises(AppException):
        reference_service.validate_target_module(target)


@pytest.mark.parametrize(
    "target_module",
    ["safety", "environment", "quality", "warehouse", "meter"],
)
async def test_auto_publish_owned_equipment_for_registered_module(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    target_module: str,
) -> None:
    user = User(name="引用用户", employee_no=_code("EMP"))
    db_session.add(user)
    await db_session.flush()
    equipment = await _equipment(db_session)
    ctx = _ctx(user)
    monkeypatch.setattr(
        reference_service,
        "build_access_context",
        _async_return(ctx),
    )

    refs = await validate_equipment_references(
        db_session,
        user,
        target_module,
        [equipment.id],
    )

    assert refs[0].source == "own_scope"
    grant = await db_session.scalar(
        select(EquipmentReferenceGrant).where(
            EquipmentReferenceGrant.equipment_id == equipment.id,
            EquipmentReferenceGrant.target_module == target_module,
        )
    )
    assert grant is not None
    assert grant.source == "auto_association"
    assert grant.revoked_at is None

    # 自动发布后，即使另一位业务用户不在该设备的台账范围内，也能按当前
    # 目标模块把它作为共享设备选择；设备详情权限本身不会随之扩大。
    viewer = User(name="共享设备使用人", employee_no=_code("EMP"))
    db_session.add(viewer)
    await db_session.flush()
    monkeypatch.setattr(
        reference_service,
        "build_access_context",
        _async_return(_ctx(viewer, scope="department", departments=[uuid.uuid4()])),
    )
    shared = await get_equipment_references_by_ids(
        db_session,
        viewer,
        target_module,
        [equipment.id],
    )
    assert [row.id for row in shared] == [equipment.id]
    assert shared[0].source == "shared"


async def test_revoke_then_manual_regrant_restores_reference(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """撤销记录保留并阻断自有范围；负责人重新授权后才恢复。"""
    user = User(name="重新授权用户", employee_no=_code("EMP"))
    db_session.add(user)
    await db_session.flush()
    equipment = await _equipment(db_session)
    ctx = _ctx(user)
    monkeypatch.setattr(reference_service, "build_access_context", _async_return(ctx))

    await reference_service.revoke_equipment_references(
        db_session, ctx, "environment", [equipment.id]
    )
    grant = await db_session.scalar(
        select(EquipmentReferenceGrant).where(
            EquipmentReferenceGrant.equipment_id == equipment.id,
            EquipmentReferenceGrant.target_module == "environment",
        )
    )
    assert grant is not None and grant.revoked_at is not None
    with pytest.raises(ForbiddenException):
        await validate_equipment_references(
            db_session, user, "environment", [equipment.id]
        )

    await reference_service.grant_equipment_references(
        db_session, ctx, "environment", [equipment.id]
    )
    restored = await validate_equipment_references(
        db_session, user, "environment", [equipment.id]
    )
    assert restored[0].id == equipment.id
    assert grant.revoked_at is None

    repeated = await reference_service.grant_equipment_references(
        db_session, ctx, "environment", [equipment.id, equipment.id]
    )
    rows = list(
        (
            await db_session.execute(
                select(EquipmentReferenceGrant).where(
                    EquipmentReferenceGrant.equipment_id == equipment.id,
                    EquipmentReferenceGrant.target_module == "environment",
                )
            )
        ).scalars()
    )
    assert repeated[0].id == grant.id
    assert len(rows) == 1


async def test_revoke_works_after_equipment_scrapped(
    db_session: AsyncSession,
) -> None:
    """设备报废后负责人仍能撤销它此前发出的授权。

    撤销的归属判断只看数据范围，不看设备当前状态：否则报废即锁死撤销入口，
    而设备一旦恢复（改回完好）时 revoked_at 仍为空，旧授权会静默复活。
    """
    user = User(name="授权负责人", employee_no=_code("EMP"))
    db_session.add(user)
    await db_session.flush()
    department_id = uuid.uuid4()
    equipment = await _equipment(db_session, department_id=department_id)
    ctx = _ctx(user, scope="department", departments=[department_id])

    await reference_service.grant_equipment_references(
        db_session, ctx, "environment", [equipment.id]
    )
    equipment.status = "报废"
    await db_session.flush()

    grants = await reference_service.revoke_equipment_references(
        db_session, ctx, "environment", [equipment.id]
    )
    assert grants[0].revoked_at is not None

    # 设备恢复后仍是撤销态，不得复活
    equipment.status = "完好"
    await db_session.flush()
    grant = await db_session.scalar(
        select(EquipmentReferenceGrant).where(
            EquipmentReferenceGrant.equipment_id == equipment.id,
            EquipmentReferenceGrant.target_module == "environment",
        )
    )
    assert grant is not None and grant.revoked_at is not None


async def test_shared_equipment_is_union_and_revocation_wins(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dept_a = uuid.uuid4()
    dept_b = uuid.uuid4()
    user = User(name="部门引用用户", employee_no=_code("EMP"))
    db_session.add(user)
    await db_session.flush()
    own = await _equipment(db_session, department_id=dept_a)
    shared = await _equipment(db_session, department_id=dept_b)
    hidden = await _equipment(db_session, department_id=dept_b)
    ctx = _ctx(user, scope="department", departments=[dept_a])
    monkeypatch.setattr(reference_service, "build_access_context", _async_return(ctx))

    await reference_service.grant_equipment_references(
        db_session,
        _ctx(User(name="设备管理员")),
        "energy",
        [shared.id],
    )
    refs, total = await list_equipment_references(
        db_session,
        user,
        "energy",
        page_size=100,
    )
    assert total == 2
    assert {ref.id for ref in refs} == {own.id, shared.id}
    assert hidden.id not in {ref.id for ref in refs}
    assert next(ref for ref in refs if ref.id == own.id).source == "own_scope"
    assert next(ref for ref in refs if ref.id == shared.id).source == "shared"

    await reference_service.revoke_equipment_references(
        db_session,
        ctx,
        "energy",
        [own.id],
    )
    refs_after = await get_equipment_references_by_ids(
        db_session,
        user,
        "energy",
        [own.id, shared.id, hidden.id],
    )
    assert [ref.id for ref in refs_after] == [shared.id]
    with pytest.raises(ForbiddenException):
        await validate_equipment_references(
            db_session,
            user,
            "energy",
            [hidden.id],
        )


async def test_validate_rejects_any_partial_or_revoked_id(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(name="引用用户", employee_no=_code("EMP"))
    db_session.add(user)
    await db_session.flush()
    equipment = await _equipment(db_session)
    ctx = _ctx(user)
    monkeypatch.setattr(reference_service, "build_access_context", _async_return(ctx))
    await reference_service.revoke_equipment_references(
        db_session,
        ctx,
        "quality",
        [equipment.id],
    )

    with pytest.raises(ForbiddenException):
        await validate_equipment_references(
            db_session,
            user,
            "quality",
            [equipment.id, uuid.uuid4()],
        )


async def test_scrapped_soft_deleted_and_unknown_ids_are_hidden(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(name="状态校验用户", employee_no=_code("EMP"))
    db_session.add(user)
    await db_session.flush()
    ctx = _ctx(user)
    monkeypatch.setattr(reference_service, "build_access_context", _async_return(ctx))
    scrapped = await _equipment(db_session, status="报废")
    deleted = await _equipment(db_session)
    deleted.is_deleted = True
    await db_session.flush()

    rows = await get_equipment_references_by_ids(
        db_session, user, "warehouse", [scrapped.id, deleted.id, uuid.uuid4()]
    )
    assert rows == []
    with pytest.raises(ForbiddenException):
        await validate_equipment_references(
            db_session, user, "warehouse", [scrapped.id]
        )


async def test_reference_dto_has_no_equipment_detail_fields(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(name="摘要用户", employee_no=_code("EMP"))
    db_session.add(user)
    await db_session.flush()
    equipment = await _equipment(db_session)
    ctx = _ctx(user)
    monkeypatch.setattr(reference_service, "build_access_context", _async_return(ctx))
    refs = await validate_equipment_references(
        db_session, user, "meter", [equipment.id]
    )
    assert set(vars(refs[0])) == {
        "id",
        "equipment_no",
        "name",
        "status",
        "is_active",
        "source",
    }
    assert not hasattr(refs[0], "supplier")
    assert not hasattr(refs[0], "asset_value")


async def test_manual_grant_respects_equipment_data_scope(
    db_session: AsyncSession,
) -> None:
    owner = User(name="范围用户", employee_no=_code("EMP"))
    db_session.add(owner)
    await db_session.flush()
    own_department = uuid.uuid4()
    other_department = uuid.uuid4()
    equipment = await _equipment(db_session, department_id=other_department)
    ctx = _ctx(owner, scope="department", departments=[own_department])
    with pytest.raises(ForbiddenException):
        await reference_service.grant_equipment_references(
            db_session, ctx, "quality", [equipment.id]
        )


async def test_internal_user_none_returns_minimal_active_summary(
    db_session: AsyncSession,
) -> None:
    active = await _equipment(db_session)
    scrapped = await _equipment(db_session, status="报废")
    refs, total = await list_equipment_references(
        db_session,
        None,
        "meter",
        page_size=100,
    )
    ids = {ref.id for ref in refs}
    assert active.id in ids
    assert scrapped.id not in ids
    assert total == len(refs)
    assert not hasattr(refs[0], "supplier")


async def test_reference_management_api_requires_dedicated_permission(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """设备台账查看权限不能替代跨模块引用管理权限。"""

    async def _asset_only_permissions(user_id: str, db: object) -> set[str]:
        return {"equipment:asset:read"}

    monkeypatch.setattr(
        "app.platform.permission.deps.get_user_permissions",
        _asset_only_permissions,
    )
    response = await client.get("/api/v1/equipment/references/targets")
    assert response.status_code == 403


def _async_return[T](value: T) -> Callable[..., Awaitable[T]]:
    async def _wrapped(*args: object, **kwargs: object) -> T:
        return value

    return _wrapped
