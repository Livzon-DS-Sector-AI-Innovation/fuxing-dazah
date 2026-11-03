"""QA 主数据仓储：只写 SQL，状态与审计由 service 编排。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.qa.models import (
    MasterObject,
    MasterObjectAlias,
    MasterObjectSource,
)
from app.shared.sql import escape_like


async def get_master(db: AsyncSession, object_id: uuid.UUID) -> MasterObject | None:
    result = await db.execute(
        select(MasterObject).where(
            MasterObject.id == object_id,
            MasterObject.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def list_masters(
    db: AsyncSession,
    *,
    object_type: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
    include_deleted: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[MasterObject], int]:
    conditions: list[ColumnElement[bool]] = []
    if not include_deleted:
        conditions.append(MasterObject.is_deleted.is_(False))
    if object_type:
        conditions.append(MasterObject.object_type == object_type)
    if status:
        conditions.append(MasterObject.status == status)
    if keyword:
        # 用户输入的 % / _ 是字面量；不转义时 keyword="%" 会命中全表。
        term = f"%{escape_like(keyword.strip())}%"
        conditions.append(
            or_(
                MasterObject.code.ilike(term, escape="\\"),
                MasterObject.name.ilike(term, escape="\\"),
                MasterObject.normalized_code.ilike(term, escape="\\"),
                MasterObject.id.in_(
                    select(MasterObjectAlias.master_object_id).where(
                        MasterObjectAlias.normalized_alias.ilike(term, escape="\\"),
                        MasterObjectAlias.is_deleted.is_(False),
                    )
                ),
            )
        )
    base = select(MasterObject).where(*conditions)
    total = int(
        (
            await db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
    )
    result = await db.execute(
        base.order_by(MasterObject.object_type, MasterObject.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), total


async def get_aliases(
    db: AsyncSession, object_id: uuid.UUID
) -> list[MasterObjectAlias]:
    result = await db.execute(
        select(MasterObjectAlias)
        .where(
            MasterObjectAlias.master_object_id == object_id,
            MasterObjectAlias.is_deleted.is_(False),
        )
        .order_by(MasterObjectAlias.alias)
    )
    return list(result.scalars())


async def get_sources(
    db: AsyncSession, object_id: uuid.UUID
) -> list[MasterObjectSource]:
    result = await db.execute(
        select(MasterObjectSource)
        .where(
            MasterObjectSource.master_object_id == object_id,
            MasterObjectSource.is_deleted.is_(False),
        )
        .order_by(MasterObjectSource.source_module, MasterObjectSource.source_entity)
    )
    return list(result.scalars())


async def get_aliases_for_masters(
    db: AsyncSession, object_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[MasterObjectAlias]]:
    """批量取别名，供列表页一次查完（逐行查会变成 N+1）。"""
    if not object_ids:
        return {}
    result = await db.execute(
        select(MasterObjectAlias)
        .where(
            MasterObjectAlias.master_object_id.in_(object_ids),
            MasterObjectAlias.is_deleted.is_(False),
        )
        .order_by(MasterObjectAlias.alias)
    )
    grouped: dict[uuid.UUID, list[MasterObjectAlias]] = {}
    for row in result.scalars():
        grouped.setdefault(row.master_object_id, []).append(row)
    return grouped


async def get_sources_for_masters(
    db: AsyncSession, object_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[MasterObjectSource]]:
    """批量取外部来源，供列表页一次查完（逐行查会变成 N+1）。"""
    if not object_ids:
        return {}
    result = await db.execute(
        select(MasterObjectSource)
        .where(
            MasterObjectSource.master_object_id.in_(object_ids),
            MasterObjectSource.is_deleted.is_(False),
        )
        .order_by(MasterObjectSource.source_module, MasterObjectSource.source_entity)
    )
    grouped: dict[uuid.UUID, list[MasterObjectSource]] = {}
    for row in result.scalars():
        grouped.setdefault(row.master_object_id, []).append(row)
    return grouped
