"""设备跨模块引用授权的数据访问。"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, case, func, literal, select, union
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import Equipment, EquipmentReferenceGrant
from app.modules.equipment.service.data_scope import apply_equipment_scope
from app.shared.sql import escape_like

SCRAPPED_STATUS = "报废"


def _active_grant_clause(target_module: str) -> tuple[Any, ...]:
    return (
        EquipmentReferenceGrant.target_module == target_module,
        EquipmentReferenceGrant.is_deleted == False,  # noqa: E712
        EquipmentReferenceGrant.revoked_at.is_(None),
    )


def _revoked_grant_clause(target_module: str) -> tuple[Any, ...]:
    return (
        EquipmentReferenceGrant.target_module == target_module,
        # revoked_at 是“负责人明确阻断”的事实记录，即使历史行曾被软删除，
        # 也不能让 own-scope 查询重新绕过撤销。重新授权时 upsert 会恢复该行。
        EquipmentReferenceGrant.revoked_at.is_not(None),
    )


def _equipment_base_clause() -> tuple[Any, ...]:
    return (
        Equipment.is_deleted == False,  # noqa: E712
        Equipment.status != SCRAPPED_STATUS,
    )


def _owned_equipment_ids_query(
    db: AsyncSession,
    ctx: EquipmentAccessContext | None,
    *,
    only_active: bool = True,
) -> Select[Any]:
    """构造当前用户设备台账数据范围内的设备 ID 查询。

    ``only_active=False`` 用于授权管理：归属判断只看数据范围，不看设备当前
    是否报废/已删除。
    """
    query = select(Equipment.id)
    if only_active:
        query = query.where(*_equipment_base_clause())
    if ctx is not None:
        query = apply_equipment_scope(
            query,
            ctx,
            Equipment.department_id,
            "department_id",
        )
    return query


async def get_owned_equipment_ids(
    db: AsyncSession,
    ctx: EquipmentAccessContext | None,
    ids: Sequence[uuid.UUID],
    *,
    only_active: bool = True,
) -> set[uuid.UUID]:
    """返回指定 ID 中属于当前设备数据范围的设备。

    ``only_active=False`` 用于撤销授权：设备报废后负责人仍必须能撤销它此前
    发出的共享授权，否则设备一旦恢复（改回完好或取消删除），旧授权会因为
    revoked_at 仍为空而静默复活。
    """
    if not ids:
        return set()
    query = _owned_equipment_ids_query(db, ctx, only_active=only_active).where(
        Equipment.id.in_(ids)
    )
    result = await db.execute(query)
    return set(result.scalars())


async def get_active_grant_equipment_ids(
    db: AsyncSession,
    target_module: str,
    ids: Sequence[uuid.UUID] | None = None,
) -> set[uuid.UUID]:
    """返回目标模块当前有效授权的设备 ID。"""
    query = select(EquipmentReferenceGrant.equipment_id).where(
        *_active_grant_clause(target_module)
    )
    if ids:
        query = query.where(EquipmentReferenceGrant.equipment_id.in_(ids))
    result = await db.execute(query)
    return set(result.scalars())


async def get_revoked_grant_equipment_ids(
    db: AsyncSession,
    target_module: str,
    ids: Sequence[uuid.UUID] | None = None,
) -> set[uuid.UUID]:
    """返回目标模块明确撤销授权的设备 ID。

    撤销记录必须参与最终过滤，即使设备同时落在调用者自己的台账数据范围内。
    """
    query = select(EquipmentReferenceGrant.equipment_id).where(
        *_revoked_grant_clause(target_module)
    )
    if ids:
        query = query.where(EquipmentReferenceGrant.equipment_id.in_(ids))
    result = await db.execute(query)
    return set(result.scalars())


async def list_reference_equipments(
    db: AsyncSession,
    ctx: EquipmentAccessContext | None,
    target_module: str,
    *,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[tuple[Equipment, str]], int]:
    """查询“自有范围 + 模块共享”设备并标记来源。"""
    owned_ids_query = _owned_equipment_ids_query(db, ctx)
    granted_ids_query = select(EquipmentReferenceGrant.equipment_id).where(
        *_active_grant_clause(target_module)
    )
    revoked_ids_query = select(EquipmentReferenceGrant.equipment_id).where(
        *_revoked_grant_clause(target_module)
    )
    eligible_ids = union(owned_ids_query, granted_ids_query).subquery()

    query = select(
        Equipment,
        case(
            (
                Equipment.id.in_(select(owned_ids_query.subquery().c.id)),
                literal("own_scope"),
            ),
            else_=literal("shared"),
        ).label("source"),
    ).where(
        Equipment.id.in_(select(eligible_ids.c.id)),
        *_equipment_base_clause(),
    )
    if ctx is not None:
        query = query.where(
            ~Equipment.id.in_(select(revoked_ids_query.subquery().c.equipment_id))
        )
    if status:
        query = query.where(Equipment.status == status)
    if keyword:
        escaped = escape_like(keyword)
        query = query.where(
            Equipment.equipment_no.ilike(f"%{escaped}%", escape="\\")
            | Equipment.name.ilike(f"%{escaped}%", escape="\\")
        )

    count_query = select(func.count()).select_from(
        query.with_only_columns(Equipment.id, maintain_column_froms=True)
        .order_by(None)
        .subquery()
    )
    total_result = await db.execute(count_query)
    total = int(total_result.scalar() or 0)

    query = query.order_by(Equipment.equipment_no, Equipment.id)
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return [(row[0], str(row[1])) for row in result.all()], total


async def get_reference_equipments_by_ids(
    db: AsyncSession,
    ctx: EquipmentAccessContext | None,
    target_module: str,
    ids: Sequence[uuid.UUID],
) -> list[tuple[Equipment, str]]:
    """按输入顺序返回当前用户可引用的设备摘要来源。"""
    if not ids:
        return []
    # owned 侧也要按 ids 收窄：否则与 granted 侧 union 去重时，超管每次调用
    # 都会把全表设备 ID 物化一遍（QA 主数据列表按分组反复调用本方法）。
    owned_ids_query = _owned_equipment_ids_query(db, ctx).where(Equipment.id.in_(ids))
    granted_ids_query = select(EquipmentReferenceGrant.equipment_id).where(
        *_active_grant_clause(target_module),
        EquipmentReferenceGrant.equipment_id.in_(ids),
    )
    revoked_ids = (
        await get_revoked_grant_equipment_ids(db, target_module, ids)
        if ctx is not None
        else set()
    )
    eligible_ids = union(owned_ids_query, granted_ids_query).subquery()
    query = select(
        Equipment,
        case(
            (
                Equipment.id.in_(select(owned_ids_query.subquery().c.id)),
                literal("own_scope"),
            ),
            else_=literal("shared"),
        ).label("source"),
    ).where(
        Equipment.id.in_(ids),
        Equipment.id.in_(select(eligible_ids.c.id)),
        *_equipment_base_clause(),
    )
    if revoked_ids:
        query = query.where(~Equipment.id.in_(revoked_ids))
    result = await db.execute(query)
    by_id = {row[0].id: (row[0], str(row[1])) for row in result.all()}
    seen: set[uuid.UUID] = set()
    rows: list[tuple[Equipment, str]] = []
    for equipment_id in ids:
        if equipment_id in seen:
            continue
        seen.add(equipment_id)
        row = by_id.get(equipment_id)
        if row is not None:
            rows.append(row)
    return rows


async def get_reference_grant(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    target_module: str,
) -> EquipmentReferenceGrant | None:
    query = select(EquipmentReferenceGrant).where(
        EquipmentReferenceGrant.equipment_id == equipment_id,
        EquipmentReferenceGrant.target_module == target_module,
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def upsert_reference_grant(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    target_module: str,
    *,
    source: str = "manual",
    operator_id: uuid.UUID | None = None,
    remark: str | None = None,
) -> EquipmentReferenceGrant:
    """创建或恢复一条授权记录（幂等）。

    用 INSERT ... ON CONFLICT DO UPDATE 而不是「先查后插」：两人同时对同一
    设备首次授权时（同一设备的批次并发执行、同一计划单并发提交），先查后插
    会双双 add 并撞 uq_equipment_reference_grants_equipment_module 返回 500。
    """
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "equipment_id": equipment_id,
        "target_module": target_module,
        "source": source,
        "granted_by": operator_id,
        "granted_at": now,
    }
    if remark is not None:
        values["remark"] = remark
    update_set: dict[str, Any] = {
        "is_deleted": False,
        "source": source,
        "granted_by": operator_id,
        "granted_at": now,
        # 显式重新授权要清掉此前的撤销状态
        "revoked_by": None,
        "revoked_at": None,
    }
    if remark is not None:
        update_set["remark"] = remark
    stmt = (
        pg_insert(EquipmentReferenceGrant)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_equipment_reference_grants_equipment_module",
            set_=update_set,
        )
        .returning(EquipmentReferenceGrant)
        # 走的是 Core 层 UPDATE，session 里可能已有同一行的旧实例；
        # 不强制刷新的话调用方会拿到过期的 revoked_at/is_deleted。
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    return result.scalar_one()


async def upsert_reference_grants(
    db: AsyncSession,
    equipment_ids: Sequence[uuid.UUID],
    target_module: str,
    *,
    source: str = "manual",
    operator_id: uuid.UUID | None = None,
    remark: str | None = None,
) -> list[EquipmentReferenceGrant]:
    """批量版 upsert_reference_grant：一条语句覆盖整批设备，避免逐台往返。

    同一批次里重复的设备要先去掉：INSERT ... ON CONFLICT DO UPDATE 不允许
    一条语句里第二次命中同一行。
    """
    unique_ids = list(dict.fromkeys(equipment_ids))
    if not unique_ids:
        return []
    now = datetime.now(UTC)
    values: list[dict[str, Any]] = []
    for equipment_id in unique_ids:
        row: dict[str, Any] = {
            "equipment_id": equipment_id,
            "target_module": target_module,
            "source": source,
            "granted_by": operator_id,
            "granted_at": now,
        }
        if remark is not None:
            row["remark"] = remark
        values.append(row)
    update_set: dict[str, Any] = {
        "is_deleted": False,
        "source": source,
        "granted_by": operator_id,
        "granted_at": now,
        # 显式重新授权要清掉此前的撤销状态
        "revoked_by": None,
        "revoked_at": None,
    }
    if remark is not None:
        update_set["remark"] = remark
    stmt = (
        pg_insert(EquipmentReferenceGrant)
        .values(values)
        .on_conflict_do_update(
            constraint="uq_equipment_reference_grants_equipment_module",
            set_=update_set,
        )
        .returning(EquipmentReferenceGrant)
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    by_id = {row.equipment_id: row for row in result.scalars()}
    return [by_id[equipment_id] for equipment_id in unique_ids]


async def create_reference_grants_if_absent(
    db: AsyncSession,
    equipment_ids: Sequence[uuid.UUID],
    target_module: str,
    *,
    source: str = "auto_association",
    operator_id: uuid.UUID | None = None,
) -> None:
    """批量补建授权记录；已存在的行（含已撤销行）原样保留。

    ON CONFLICT DO NOTHING 一条语句覆盖两件事：并发首次授权不会撞唯一约束，
    且不会把负责人明确撤销过的授权悄悄恢复——重新授权必须由负责人显式发起。
    """
    if not equipment_ids:
        return
    now = datetime.now(UTC)
    stmt = pg_insert(EquipmentReferenceGrant).values(
        [
            {
                "equipment_id": equipment_id,
                "target_module": target_module,
                "source": source,
                "granted_by": operator_id,
                "granted_at": now,
            }
            for equipment_id in equipment_ids
        ]
    )
    await db.execute(
        stmt.on_conflict_do_nothing(
            constraint="uq_equipment_reference_grants_equipment_module"
        )
    )


async def revoke_reference_grants(
    db: AsyncSession,
    equipment_ids: Sequence[uuid.UUID],
    target_module: str,
    *,
    operator_id: uuid.UUID | None = None,
) -> list[EquipmentReferenceGrant]:
    """撤销目标模块授权，保留记录用于阻断自有范围绕过。"""
    if not equipment_ids:
        return []
    query = select(EquipmentReferenceGrant).where(
        EquipmentReferenceGrant.equipment_id.in_(equipment_ids),
        EquipmentReferenceGrant.target_module == target_module,
    )
    result = await db.execute(query)
    grants = list(result.scalars())
    existing_ids = {grant.equipment_id for grant in grants}
    now = datetime.now(UTC)
    # 即使此前从未发布过，也要写入撤销 tombstone；否则 own scope 会绕过
    # 撤销状态。设备负责人后续显式重新授权时，upsert 会恢复该记录。
    for equipment_id in equipment_ids:
        if equipment_id in existing_ids:
            continue
        grant = EquipmentReferenceGrant(
            equipment_id=equipment_id,
            target_module=target_module,
            source="manual",
            granted_by=operator_id,
            granted_at=now,
            revoked_by=operator_id,
            revoked_at=now,
        )
        db.add(grant)
        grants.append(grant)
    for grant in grants:
        # 兼容历史上被软删除的授权行：恢复同一逻辑记录，避免唯一键冲突。
        grant.is_deleted = False
        grant.revoked_at = now
        grant.revoked_by = operator_id
    await db.flush()
    return grants


async def list_reference_grants(
    db: AsyncSession,
    target_module: str,
    equipment_ids: Sequence[uuid.UUID] | None = None,
) -> list[EquipmentReferenceGrant]:
    query = select(EquipmentReferenceGrant).where(
        EquipmentReferenceGrant.target_module == target_module,
        EquipmentReferenceGrant.is_deleted == False,  # noqa: E712
    )
    if equipment_ids:
        query = query.where(EquipmentReferenceGrant.equipment_id.in_(equipment_ids))
    query = query.order_by(EquipmentReferenceGrant.granted_at.desc())
    result = await db.execute(query)
    return list(result.scalars())


__all__ = [
    "create_reference_grants_if_absent",
    "get_active_grant_equipment_ids",
    "get_owned_equipment_ids",
    "get_reference_equipments_by_ids",
    "get_reference_grant",
    "get_revoked_grant_equipment_ids",
    "list_reference_equipments",
    "list_reference_grants",
    "revoke_reference_grants",
    "upsert_reference_grant",
]
