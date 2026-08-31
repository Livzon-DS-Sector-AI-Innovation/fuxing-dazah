"""标准计量器具数据访问。"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import exists as sa_exists
from sqlalchemy import func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.time import today as time_today
from app.modules.meter.models import CalibrationReport, Department, InstrumentRecord
from app.modules.meter.repository._utils import (
    _coerce_date_fields,
    _escape_like,
    _parse_multi,
)

# 文本列（部分匹配/typeahead 允许的列；不含 department/status，二者单独处理）
_INSTRUMENT_TEXT_COLUMNS = [
    "asset_number", "instrument_name", "model_spec", "measurement_range",
    "accuracy_grade", "serial_number", "location", "manufacturer",
    "calibration_unit", "calibration_result", "color_marking",
]
# typeahead 允许的列 → ORM 列（文本列 + status）
_INSTRUMENT_SEARCHABLE: dict[str, Any] = {
    name: getattr(InstrumentRecord, name) for name in _INSTRUMENT_TEXT_COLUMNS
}
_INSTRUMENT_SEARCHABLE["status"] = InstrumentRecord.status


async def create_instrument(
    db: AsyncSession, data: dict[str, Any]
) -> InstrumentRecord:
    stmt = pg_insert(InstrumentRecord).values(**data).returning(InstrumentRecord)
    result = await db.execute(stmt)
    await db.flush()
    return result.scalar_one()


async def get_instrument_by_id(
    db: AsyncSession, instrument_id: UUID, *, include_reports: bool = True
) -> InstrumentRecord | None:
    stmt = select(InstrumentRecord).where(
        InstrumentRecord.id == instrument_id,
        InstrumentRecord.is_deleted == False,  # noqa: E712
    )
    if include_reports:
        stmt = stmt.options(selectinload(InstrumentRecord.reports))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def exists_instrument_by_asset_number(
    db: AsyncSession, asset_number: str, *, exclude_id: UUID | None = None
) -> bool:
    conditions = [
        InstrumentRecord.asset_number == asset_number,
        InstrumentRecord.is_deleted == False,  # noqa: E712
    ]
    if exclude_id:
        conditions.append(InstrumentRecord.id != exclude_id)
    stmt = select(func.count()).select_from(
        select(InstrumentRecord).where(*conditions).subquery()
    )
    result = await db.execute(stmt)
    return (result.scalar() or 0) > 0


async def list_instruments(
    db: AsyncSession,
    *,
    department: str | None = None,
    asset_number: str | None = None,
    instrument_name: str | None = None,
    model_spec: str | None = None,
    measurement_range: str | None = None,
    accuracy_grade: str | None = None,
    serial_number: str | None = None,
    location: str | None = None,
    manufacturer: str | None = None,
    status: str | None = None,
    calibration_unit: str | None = None,
    calibration_result: str | None = None,
    color_marking: str | None = None,
    next_calibration_before: date | None = None,
    next_calibration_after: date | None = None,
    calibration_date_before: date | None = None,
    calibration_date_after: date | None = None,
    keyword: str | None = None,
    has_report: bool | None = None,
    like_filters: dict[str, str] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InstrumentRecord], int]:
    query = select(InstrumentRecord).where(
        InstrumentRecord.is_deleted == False  # noqa: E712
    )

    # 多选字段：逗号分隔 → IN 查询
    for field, col in [
        ("asset_number", InstrumentRecord.asset_number),
        ("instrument_name", InstrumentRecord.instrument_name),
        ("model_spec", InstrumentRecord.model_spec),
        ("measurement_range", InstrumentRecord.measurement_range),
        ("accuracy_grade", InstrumentRecord.accuracy_grade),
        ("serial_number", InstrumentRecord.serial_number),
        ("location", InstrumentRecord.location),
        ("manufacturer", InstrumentRecord.manufacturer),
        ("calibration_unit", InstrumentRecord.calibration_unit),
        ("calibration_result", InstrumentRecord.calibration_result),
        ("color_marking", InstrumentRecord.color_marking),
    ]:
        value = locals().get(field)
        parts = _parse_multi(value)
        if parts:
            query = query.where(col.in_(parts))

    # 文本列部分匹配（输入即过滤）：col ILIKE %text%
    for col_name in _INSTRUMENT_TEXT_COLUMNS:
        text = (like_filters or {}).get(col_name)
        if text:
            col_attr = getattr(InstrumentRecord, col_name)
            query = query.where(col_attr.ilike(f"%{_escape_like(text)}%"))

    if department:
        parts = _parse_multi(department)
        if parts:
            query = query.where(InstrumentRecord.department.in_(parts))
    if status:
        parts = _parse_multi(status)
        if parts:
            today_val = time_today()
            conditions: list[Any] = []
            for s in parts:
                if s == "超期":
                    # 有效状态为"超期"：DB 超期/在用 + 下次检定已过期
                    conditions.append(
                        InstrumentRecord.status.in_(["超期", "在用"])
                        & (InstrumentRecord.next_calibration_date < today_val)
                    )
                elif s == "在用":
                    # 有效状态为"在用"：DB 在用/超期 + 未过期，或非标准状态
                    conditions.append(
                        or_(
                            InstrumentRecord.status.in_(["在用", "超期"])
                            & (
                                (InstrumentRecord.next_calibration_date >= today_val)
                                | (InstrumentRecord.next_calibration_date.is_(None))
                            ),
                            InstrumentRecord.status.notin_(["在用", "超期", "停用"]),
                        )
                    )
                else:
                    conditions.append(InstrumentRecord.status == s)
            query = query.where(or_(*conditions))
    if next_calibration_before:
        query = query.where(InstrumentRecord.next_calibration_date <= next_calibration_before)
    if next_calibration_after:
        query = query.where(InstrumentRecord.next_calibration_date >= next_calibration_after)
    if calibration_date_before:
        query = query.where(InstrumentRecord.calibration_date <= calibration_date_before)
    if calibration_date_after:
        query = query.where(InstrumentRecord.calibration_date >= calibration_date_after)
    if keyword:
        query = query.where(
            InstrumentRecord.asset_number.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | InstrumentRecord.instrument_name.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | InstrumentRecord.model_spec.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | InstrumentRecord.serial_number.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | InstrumentRecord.location.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | InstrumentRecord.manufacturer.ilike(f"%{_escape_like(keyword)}%", escape="\\")
        )
    if has_report is not None:
        sub = select(CalibrationReport.id).where(
            CalibrationReport.instrument_id == InstrumentRecord.id,
            CalibrationReport.is_deleted == False,  # noqa: E712
        )
        if has_report:
            query = query.where(sa_exists(sub))
        else:
            query = query.where(~sa_exists(sub))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(InstrumentRecord.sort_order.asc(), InstrumentRecord.id.asc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def count_reports_by_instrument_ids(
    db: AsyncSession, instrument_ids: list[UUID]
) -> dict[UUID, int]:
    """批量查询标准计量器具的报告数量。"""
    if not instrument_ids:
        return {}
    stmt = (
        select(CalibrationReport.instrument_id, func.count())
        .where(
            CalibrationReport.instrument_id.in_(instrument_ids),
            CalibrationReport.is_deleted == False,  # noqa: E712
        )
        .group_by(CalibrationReport.instrument_id)
    )
    rows = await db.execute(stmt)
    return {row[0]: row[1] for row in rows.all()}


async def update_instrument(
    db: AsyncSession, instrument_id: UUID, updates: dict[str, Any]
) -> InstrumentRecord | None:
    """更新后 re-fetch 以获取 onupdate 回填值。"""
    _coerce_date_fields(updates)
    stmt = (
        sa_update(InstrumentRecord)
        .where(InstrumentRecord.id == instrument_id)
        .values(**updates)
    )
    await db.execute(stmt)
    await db.flush()
    return await get_instrument_by_id(db, instrument_id, include_reports=True)


async def soft_delete_instrument(db: AsyncSession, instrument_id: UUID) -> bool:
    stmt = (
        sa_update(InstrumentRecord)
        .where(InstrumentRecord.id == instrument_id, InstrumentRecord.is_deleted == False)  # noqa: E712
        .values(is_deleted=True)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount > 0  # type: ignore[no-any-return,attr-defined]


async def batch_soft_delete_instruments(db: AsyncSession, ids: list[UUID]) -> int:
    """批量软删除标准计量器具，返回实际删除数。"""
    stmt = (
        sa_update(InstrumentRecord)
        .where(InstrumentRecord.id.in_(ids), InstrumentRecord.is_deleted == False)  # noqa: E712
        .values(is_deleted=True)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount  # type: ignore[no-any-return,attr-defined]


async def get_all_instrument_ids(
    db: AsyncSession,
    *,
    department: str | None = None,
    asset_number: str | None = None,
    instrument_name: str | None = None,
    model_spec: str | None = None,
    measurement_range: str | None = None,
    accuracy_grade: str | None = None,
    serial_number: str | None = None,
    location: str | None = None,
    manufacturer: str | None = None,
    status: str | None = None,
    calibration_unit: str | None = None,
    calibration_result: str | None = None,
    color_marking: str | None = None,
    next_calibration_before: date | None = None,
    next_calibration_after: date | None = None,
    calibration_date_before: date | None = None,
    calibration_date_after: date | None = None,
    keyword: str | None = None,
    has_report: bool | None = None,
    like_filters: dict[str, str] | None = None,
) -> list[UUID]:
    """获取当前筛选条件下所有记录 ID（用于跨页全选）。"""
    query = select(InstrumentRecord.id).where(
        InstrumentRecord.is_deleted == False  # noqa: E712
    )

    for field, col in [
        ("asset_number", InstrumentRecord.asset_number),
        ("instrument_name", InstrumentRecord.instrument_name),
        ("model_spec", InstrumentRecord.model_spec),
        ("measurement_range", InstrumentRecord.measurement_range),
        ("accuracy_grade", InstrumentRecord.accuracy_grade),
        ("serial_number", InstrumentRecord.serial_number),
        ("location", InstrumentRecord.location),
        ("manufacturer", InstrumentRecord.manufacturer),
        ("calibration_unit", InstrumentRecord.calibration_unit),
        ("calibration_result", InstrumentRecord.calibration_result),
        ("color_marking", InstrumentRecord.color_marking),
    ]:
        value = locals().get(field)
        parts = _parse_multi(value)
        if parts:
            query = query.where(col.in_(parts))

    # 文本列部分匹配（输入即过滤）：col ILIKE %text%
    for col_name in _INSTRUMENT_TEXT_COLUMNS:
        text = (like_filters or {}).get(col_name)
        if text:
            col_attr = getattr(InstrumentRecord, col_name)
            query = query.where(col_attr.ilike(f"%{_escape_like(text)}%"))

    if department:
        parts = _parse_multi(department)
        if parts:
            query = query.where(InstrumentRecord.department.in_(parts))
    if status:
        parts = _parse_multi(status)
        if parts:
            today_val = time_today()
            conditions: list[Any] = []
            for s in parts:
                if s == "超期":
                    # 有效状态为"超期"：DB 超期/在用 + 下次检定已过期
                    conditions.append(
                        InstrumentRecord.status.in_(["超期", "在用"])
                        & (InstrumentRecord.next_calibration_date < today_val)
                    )
                elif s == "在用":
                    # 有效状态为"在用"：DB 在用/超期 + 未过期，或非标准状态
                    conditions.append(
                        or_(
                            InstrumentRecord.status.in_(["在用", "超期"])
                            & (
                                (InstrumentRecord.next_calibration_date >= today_val)
                                | (InstrumentRecord.next_calibration_date.is_(None))
                            ),
                            InstrumentRecord.status.notin_(["在用", "超期", "停用"]),
                        )
                    )
                else:
                    conditions.append(InstrumentRecord.status == s)
            query = query.where(or_(*conditions))
    if next_calibration_before:
        query = query.where(InstrumentRecord.next_calibration_date <= next_calibration_before)
    if next_calibration_after:
        query = query.where(InstrumentRecord.next_calibration_date >= next_calibration_after)
    if calibration_date_before:
        query = query.where(InstrumentRecord.calibration_date <= calibration_date_before)
    if calibration_date_after:
        query = query.where(InstrumentRecord.calibration_date >= calibration_date_after)
    if keyword:
        query = query.where(
            InstrumentRecord.asset_number.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | InstrumentRecord.instrument_name.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | InstrumentRecord.model_spec.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | InstrumentRecord.serial_number.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | InstrumentRecord.location.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | InstrumentRecord.manufacturer.ilike(f"%{_escape_like(keyword)}%", escape="\\")
        )
    if has_report is not None:
        sub = select(CalibrationReport.id).where(
            CalibrationReport.instrument_id == InstrumentRecord.id,
            CalibrationReport.is_deleted == False,  # noqa: E712
        )
        if has_report:
            query = query.where(sa_exists(sub))
        else:
            query = query.where(~sa_exists(sub))

    query = query.order_by(InstrumentRecord.sort_order.asc(), InstrumentRecord.id.asc())
    result = await db.execute(query)
    return [row[0] for row in result.all()]


async def get_instrument_departments(db: AsyncSession) -> list[str]:
    """从 departments 表读取标准计量器具部门列表。"""
    stmt = (
        select(Department.name)
        .where(Department.source == "instrument", Department.is_deleted == False)  # noqa: E712
        .distinct()
        .order_by(Department.name)
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all() if row[0]]


async def get_max_instrument_sort_order(db: AsyncSession) -> int:
    """获取当前最大的 sort_order，用于新增记录时追加到末尾。"""
    stmt = select(func.coalesce(func.max(InstrumentRecord.sort_order), 0)).where(
        InstrumentRecord.is_deleted == False  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.scalar() or 0


async def get_instrument_filter_options(
    db: AsyncSession,
) -> dict[str, list[str]]:
    """获取标准计量器具所有筛选列的 distinct 值（全表）。"""
    columns = [
        "asset_number", "instrument_name", "model_spec", "measurement_range",
        "accuracy_grade", "serial_number", "location", "manufacturer",
        "status", "calibration_unit", "calibration_result", "color_marking",
    ]
    result: dict[str, list[str]] = {}

    # 部门：从 departments 表读取
    dept_stmt = (
        select(Department.name)
        .where(Department.source == "instrument", Department.is_deleted == False)  # noqa: E712
        .distinct()
        .order_by(Department.name)
    )
    dept_rows = await db.execute(dept_stmt)
    result["department"] = sorted([row[0] for row in dept_rows.all() if row[0]])

    for col in columns:
        col_attr = getattr(InstrumentRecord, col)
        stmt = (
            select(col_attr)
            .where(InstrumentRecord.is_deleted == False, col_attr.isnot(None), col_attr != "")  # noqa: E712
            .distinct()
            .order_by(col_attr)
        )
        rows = await db.execute(stmt)
        result[col] = sorted([row[0] for row in rows.all() if row[0] and str(row[0]).strip()])
    return result


async def search_instrument_filter_options(
    db: AsyncSession,
    *,
    field: str,
    q: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """按字段名 + 关键字搜索 distinct 值（typeahead）。

    - 允许的字段由 `_INSTRUMENT_SEARCHABLE` + department 白名单决定。
    - `q` 为空返回前 `limit` 个 distinct；非空则按 ILIKE 部分匹配。
    - `department` 从 departments 表读取；`status` 并入动态计算的「超期」。
    """
    if field == "department":
        conds = [Department.source == "instrument", Department.is_deleted == False]  # noqa: E712
        if q:
            conds.append(Department.name.ilike(f"%{_escape_like(q)}%"))
        count_stmt = select(func.count()).select_from(
            select(Department.name).where(*conds).distinct().subquery()
        )
        total = (await db.execute(count_stmt)).scalar() or 0
        items_stmt = (
            select(Department.name)
            .where(*conds)
            .distinct()
            .order_by(Department.name)
            .limit(limit)
        )
        rows = await db.execute(items_stmt)
        items = sorted({r[0] for r in rows.all() if r[0] and str(r[0]).strip()})
        return {"items": items, "total": total}

    if field == "status":
        # 状态是动态计算状态，「超期」不在库里。用全量候选（DB 状态 + 超期）在 Python 侧按 q 过滤。
        stmt = select(InstrumentRecord.status).where(
            InstrumentRecord.is_deleted == False,  # noqa: E712
            InstrumentRecord.status.isnot(None),
            InstrumentRecord.status != "",
        ).distinct()
        rows = await db.execute(stmt)
        candidates = sorted(
            {r[0] for r in rows.all() if r[0] and str(r[0]).strip()} | {"超期"}
        )
        if q:
            candidates = [c for c in candidates if q.lower() in c.lower()]
        return {"items": candidates[:limit], "total": len(candidates)}

    col = _INSTRUMENT_SEARCHABLE.get(field)
    if col is None:
        raise ValueError(f"不支持的筛选字段: {field}")

    col_conditions: list[Any] = [
        InstrumentRecord.is_deleted == False,  # noqa: E712
        col.isnot(None),
        col != "",
    ]
    if q:
        col_conditions.append(col.ilike(f"%{_escape_like(q)}%"))

    count_stmt = select(func.count()).select_from(select(col).where(*col_conditions).distinct().subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    items_stmt = select(col).where(*col_conditions).distinct().order_by(col).limit(limit)
    rows = await db.execute(items_stmt)
    items = sorted({r[0] for r in rows.all() if r[0] and str(r[0]).strip()})
    return {"items": items, "total": total}
