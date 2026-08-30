"""部门数据访问：CRUD、使用量统计与改名联动。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meter.models import Department, GasDetectorRecord, InstrumentRecord


async def create_department(db: AsyncSession, data: dict[str, Any]) -> Department:
    stmt = pg_insert(Department).values(**data).returning(Department)
    result = await db.execute(stmt)
    await db.flush()
    return result.scalar_one()


async def get_department_by_id(db: AsyncSession, dept_id: UUID) -> Department | None:
    stmt = select(Department).where(
        Department.id == dept_id,
        Department.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_departments(
    db: AsyncSession, *, source: str | None = None
) -> list[Department]:
    stmt = select(Department).where(
        Department.is_deleted == False,  # noqa: E712
    ).order_by(Department.name)
    if source:
        stmt = stmt.where(Department.source == source)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_department_by_source_and_name(
    db: AsyncSession, source: str, name: str, *, exclude_id: UUID | None = None
) -> Department | None:
    stmt = select(Department).where(
        Department.source == source,
        Department.name == name,
        Department.is_deleted == False,  # noqa: E712
    )
    if exclude_id:
        stmt = stmt.where(Department.id != exclude_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_department(
    db: AsyncSession, dept_id: UUID, updates: dict[str, Any]
) -> Department | None:
    stmt = (
        sa_update(Department)
        .where(Department.id == dept_id)
        .values(**updates)
    )
    await db.execute(stmt)
    await db.flush()
    # re-fetch for onupdate
    result = await db.execute(
        select(Department).where(Department.id == dept_id)
    )
    return result.scalar_one_or_none()


async def soft_delete_department(db: AsyncSession, dept_id: UUID) -> bool:
    stmt = (
        sa_update(Department)
        .where(Department.id == dept_id, Department.is_deleted == False)  # noqa: E712
        .values(is_deleted=True)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount > 0  # type: ignore[no-any-return,attr-defined]


async def count_records_by_department(
    db: AsyncSession, department_name: str
) -> dict[str, int]:
    """统计指定部门名在两张表中的使用量。"""
    inst_count = await db.execute(
        select(func.count()).where(
            InstrumentRecord.department == department_name,
            InstrumentRecord.is_deleted == False,  # noqa: E712
        )
    )
    det_count = await db.execute(
        select(func.count()).where(
            GasDetectorRecord.department == department_name,
            GasDetectorRecord.is_deleted == False,  # noqa: E712
        )
    )
    return {
        "instrument_count": inst_count.scalar() or 0,
        "gas_detector_count": det_count.scalar() or 0,
    }


async def rename_department_in_records(
    db: AsyncSession, old_name: str, new_name: str, source: str
) -> None:
    """批量更新指定来源表中所有匹配部门名的记录。"""
    if source == "instrument":
        stmt = (
            sa_update(InstrumentRecord)
            .where(InstrumentRecord.department == old_name)
            .values(department=new_name)
        )
    else:
        stmt = (
            sa_update(GasDetectorRecord)
            .where(GasDetectorRecord.department == old_name)
            .values(department=new_name)
        )
    await db.execute(stmt)


async def sync_departments(db: AsyncSession, source: str, names: set[str]) -> int:
    """同步部门名到 departments 表。返回新增的部门数。

    先清空该 source 下的所有部门，再写入新的部门集合。
    """
    # 1. 全部软删除
    clear_stmt = (
        sa_update(Department)
        .where(Department.source == source, Department.is_deleted == False)  # noqa: E712
        .values(is_deleted=True)
    )
    await db.execute(clear_stmt)

    # 2. 重新写入
    added = 0
    for name in names:
        if not name or not name.strip():
            continue
        name = name.strip()
        existing = await db.execute(
            select(Department).where(
                Department.source == source,
                Department.name == name,
                Department.is_deleted == False,  # noqa: E712
            )
        )
        dept = existing.scalar_one_or_none()
        if dept is None:
            # 软删除陷阱：同名部门可能被「删除→重建→再同步」留下多条已删除记录，
            # 只恢复最新一条，避免 scalar_one_or_none 命中多行报错
            deleted_stmt = (
                select(Department)
                .where(
                    Department.source == source,
                    Department.name == name,
                    Department.is_deleted.is_(True),
                )
                .order_by(Department.created_at.desc())
                .limit(1)
            )
            old = (await db.execute(deleted_stmt)).scalar_one_or_none()
            if old is not None:
                restore_stmt = (
                    sa_update(Department)
                    .where(Department.id == old.id)
                    .values(is_deleted=False)
                )
                await db.execute(restore_stmt)
                added += 1
            else:
                insert_stmt = pg_insert(Department).values(source=source, name=name)
                await db.execute(insert_stmt)
                added += 1
    await db.flush()
    return added


# ═══════════════════════════════════════════
# 全局设置
# ═══════════════════════════════════════════
