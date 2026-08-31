"""有毒有害可燃探测器数据访问。"""

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
from app.modules.meter.models import CalibrationReport, Department, GasDetectorRecord
from app.modules.meter.repository._utils import (
    _coerce_date_fields,
    _escape_like,
    _parse_multi,
)

# 文本列（部分匹配/typeahead 允许的列；不含 department/status，二者单独处理）
_GAS_DETECTOR_TEXT_COLUMNS = [
    "instrument_name", "detection_model", "product_number", "measurement_range",
    "installation_type", "installation_location", "medium", "calibration_factor",
    "manufacturer_supplier", "manufacturer", "detection_unit", "calibration_result",
]
# typeahead 允许的列 → ORM 列（文本列 + status）
_GAS_DETECTOR_SEARCHABLE: dict[str, Any] = {
    name: getattr(GasDetectorRecord, name) for name in _GAS_DETECTOR_TEXT_COLUMNS
}
_GAS_DETECTOR_SEARCHABLE["status"] = GasDetectorRecord.status


async def create_gas_detector(
    db: AsyncSession, data: dict[str, Any]
) -> GasDetectorRecord:
    stmt = pg_insert(GasDetectorRecord).values(**data).returning(GasDetectorRecord)
    result = await db.execute(stmt)
    await db.flush()
    return result.scalar_one()


async def get_gas_detector_by_id(
    db: AsyncSession, detector_id: UUID, *, include_reports: bool = True
) -> GasDetectorRecord | None:
    stmt = select(GasDetectorRecord).where(
        GasDetectorRecord.id == detector_id,
        GasDetectorRecord.is_deleted == False,  # noqa: E712
    )
    if include_reports:
        stmt = stmt.options(selectinload(GasDetectorRecord.reports))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def exists_gas_detector_by_product_number(
    db: AsyncSession, product_number: str, *, exclude_id: UUID | None = None
) -> bool:
    stmt = select(GasDetectorRecord).where(
        GasDetectorRecord.product_number == product_number,
        GasDetectorRecord.is_deleted == False,  # noqa: E712
    )
    if exclude_id:
        stmt = stmt.where(GasDetectorRecord.id != exclude_id)
    sub = stmt.subquery()
    count_stmt = select(func.count()).select_from(sub)
    result = await db.execute(count_stmt)
    return (result.scalar() or 0) > 0


async def list_gas_detectors(
    db: AsyncSession,
    *,
    department: str | None = None,
    instrument_name: str | None = None,
    detection_model: str | None = None,
    product_number: str | None = None,
    measurement_range: str | None = None,
    installation_type: str | None = None,
    installation_location: str | None = None,
    medium: str | None = None,
    detection_unit: str | None = None,
    calibration_result: str | None = None,
    calibration_factor: str | None = None,
    manufacturer_supplier: str | None = None,
    manufacturer: str | None = None,
    status: str | None = None,
    next_calibration_before: date | None = None,
    next_calibration_after: date | None = None,
    calibration_date_before: date | None = None,
    calibration_date_after: date | None = None,
    keyword: str | None = None,
    has_report: bool | None = None,
    like_filters: dict[str, str] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[GasDetectorRecord], int]:
    query = select(GasDetectorRecord).where(
        GasDetectorRecord.is_deleted == False  # noqa: E712
    )

    # 多选字段：逗号分隔 → IN 查询
    for field, col in [
        ("detection_model", GasDetectorRecord.detection_model),
        ("product_number", GasDetectorRecord.product_number),
        ("measurement_range", GasDetectorRecord.measurement_range),
        ("installation_type", GasDetectorRecord.installation_type),
        ("installation_location", GasDetectorRecord.installation_location),
        ("medium", GasDetectorRecord.medium),
        ("detection_unit", GasDetectorRecord.detection_unit),
        ("calibration_result", GasDetectorRecord.calibration_result),
        ("calibration_factor", GasDetectorRecord.calibration_factor),
        ("manufacturer_supplier", GasDetectorRecord.manufacturer_supplier),
        ("manufacturer", GasDetectorRecord.manufacturer),
    ]:
        value = locals().get(field)
        parts = _parse_multi(value)
        if parts:
            query = query.where(col.in_(parts))

    # 文本列部分匹配（输入即过滤）：col ILIKE %text%
    for col_name in _GAS_DETECTOR_TEXT_COLUMNS:
        text = (like_filters or {}).get(col_name)
        if text:
            col_attr = getattr(GasDetectorRecord, col_name)
            query = query.where(col_attr.ilike(f"%{_escape_like(text)}%"))

    if department:
        parts = _parse_multi(department)
        if parts:
            query = query.where(GasDetectorRecord.department.in_(parts))
    if instrument_name:
        parts = _parse_multi(instrument_name)
        if parts:
            query = query.where(GasDetectorRecord.instrument_name.in_(parts))
    if status:
        parts = _parse_multi(status)
        if parts:
            today_val = time_today()
            conditions: list[Any] = []
            for s in parts:
                if s == "超期":
                    conditions.append(
                        GasDetectorRecord.status.in_(["超期", "在用"])
                        & (GasDetectorRecord.next_calibration_date < today_val)
                    )
                elif s == "在用":
                    conditions.append(
                        or_(
                            GasDetectorRecord.status.in_(["在用", "超期"])
                            & (
                                (GasDetectorRecord.next_calibration_date >= today_val)
                                | (GasDetectorRecord.next_calibration_date.is_(None))
                            ),
                            GasDetectorRecord.status.notin_(["在用", "超期", "停用"]),
                        )
                    )
                else:
                    conditions.append(GasDetectorRecord.status == s)
            query = query.where(or_(*conditions))
    if next_calibration_before:
        query = query.where(GasDetectorRecord.next_calibration_date <= next_calibration_before)
    if next_calibration_after:
        query = query.where(GasDetectorRecord.next_calibration_date >= next_calibration_after)
    if calibration_date_before:
        query = query.where(GasDetectorRecord.calibration_date <= calibration_date_before)
    if calibration_date_after:
        query = query.where(GasDetectorRecord.calibration_date >= calibration_date_after)
    if keyword:
        query = query.where(
            GasDetectorRecord.instrument_name.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | GasDetectorRecord.detection_model.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | GasDetectorRecord.product_number.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | GasDetectorRecord.installation_location.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | GasDetectorRecord.manufacturer.ilike(f"%{_escape_like(keyword)}%", escape="\\")
        )
    if has_report is not None:
        sub = select(CalibrationReport.id).where(
            CalibrationReport.gas_detector_id == GasDetectorRecord.id,
            CalibrationReport.is_deleted == False,  # noqa: E712
        )
        if has_report:
            query = query.where(sa_exists(sub))
        else:
            query = query.where(~sa_exists(sub))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(GasDetectorRecord.sort_order.asc(), GasDetectorRecord.id.asc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def count_reports_by_gas_detector_ids(
    db: AsyncSession, detector_ids: list[UUID]
) -> dict[UUID, int]:
    """批量查询探测器的报告数量。"""
    if not detector_ids:
        return {}
    stmt = (
        select(CalibrationReport.gas_detector_id, func.count())
        .where(
            CalibrationReport.gas_detector_id.in_(detector_ids),
            CalibrationReport.is_deleted == False,  # noqa: E712
        )
        .group_by(CalibrationReport.gas_detector_id)
    )
    rows = await db.execute(stmt)
    return {row[0]: row[1] for row in rows.all()}


async def update_gas_detector(
    db: AsyncSession, detector_id: UUID, updates: dict[str, Any]
) -> GasDetectorRecord | None:
    _coerce_date_fields(updates)
    stmt = (
        sa_update(GasDetectorRecord)
        .where(GasDetectorRecord.id == detector_id)
        .values(**updates)
    )
    await db.execute(stmt)
    await db.flush()
    return await get_gas_detector_by_id(db, detector_id, include_reports=True)


async def soft_delete_gas_detector(db: AsyncSession, detector_id: UUID) -> bool:
    stmt = (
        sa_update(GasDetectorRecord)
        .where(GasDetectorRecord.id == detector_id, GasDetectorRecord.is_deleted == False)  # noqa: E712
        .values(is_deleted=True)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount > 0  # type: ignore[no-any-return,attr-defined]


async def batch_soft_delete_gas_detectors(db: AsyncSession, ids: list[UUID]) -> int:
    """批量软删除有毒有害可燃探测器，返回实际删除数。"""
    stmt = (
        sa_update(GasDetectorRecord)
        .where(GasDetectorRecord.id.in_(ids), GasDetectorRecord.is_deleted == False)  # noqa: E712
        .values(is_deleted=True)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount  # type: ignore[no-any-return,attr-defined]


async def get_all_gas_detector_ids(
    db: AsyncSession,
    *,
    department: str | None = None,
    instrument_name: str | None = None,
    detection_model: str | None = None,
    product_number: str | None = None,
    measurement_range: str | None = None,
    installation_type: str | None = None,
    installation_location: str | None = None,
    medium: str | None = None,
    detection_unit: str | None = None,
    calibration_result: str | None = None,
    calibration_factor: str | None = None,
    manufacturer_supplier: str | None = None,
    manufacturer: str | None = None,
    status: str | None = None,
    next_calibration_before: date | None = None,
    next_calibration_after: date | None = None,
    calibration_date_before: date | None = None,
    calibration_date_after: date | None = None,
    keyword: str | None = None,
    has_report: bool | None = None,
    like_filters: dict[str, str] | None = None,
) -> list[UUID]:
    """获取当前筛选条件下所有记录 ID（用于跨页全选）。"""
    query = select(GasDetectorRecord.id).where(
        GasDetectorRecord.is_deleted == False  # noqa: E712
    )

    for field, col in [
        ("detection_model", GasDetectorRecord.detection_model),
        ("product_number", GasDetectorRecord.product_number),
        ("measurement_range", GasDetectorRecord.measurement_range),
        ("installation_type", GasDetectorRecord.installation_type),
        ("installation_location", GasDetectorRecord.installation_location),
        ("medium", GasDetectorRecord.medium),
        ("detection_unit", GasDetectorRecord.detection_unit),
        ("calibration_result", GasDetectorRecord.calibration_result),
        ("calibration_factor", GasDetectorRecord.calibration_factor),
        ("manufacturer_supplier", GasDetectorRecord.manufacturer_supplier),
        ("manufacturer", GasDetectorRecord.manufacturer),
    ]:
        value = locals().get(field)
        parts = _parse_multi(value)
        if parts:
            query = query.where(col.in_(parts))

    # 文本列部分匹配（输入即过滤）：col ILIKE %text%
    for col_name in _GAS_DETECTOR_TEXT_COLUMNS:
        text = (like_filters or {}).get(col_name)
        if text:
            col_attr = getattr(GasDetectorRecord, col_name)
            query = query.where(col_attr.ilike(f"%{_escape_like(text)}%"))

    if department:
        parts = _parse_multi(department)
        if parts:
            query = query.where(GasDetectorRecord.department.in_(parts))
    if instrument_name:
        parts = _parse_multi(instrument_name)
        if parts:
            query = query.where(GasDetectorRecord.instrument_name.in_(parts))
    if status:
        parts = _parse_multi(status)
        if parts:
            today_val = time_today()
            conditions: list[Any] = []
            for s in parts:
                if s == "超期":
                    conditions.append(
                        GasDetectorRecord.status.in_(["超期", "在用"])
                        & (GasDetectorRecord.next_calibration_date < today_val)
                    )
                elif s == "在用":
                    conditions.append(
                        or_(
                            GasDetectorRecord.status.in_(["在用", "超期"])
                            & (
                                (GasDetectorRecord.next_calibration_date >= today_val)
                                | (GasDetectorRecord.next_calibration_date.is_(None))
                            ),
                            GasDetectorRecord.status.notin_(["在用", "超期", "停用"]),
                        )
                    )
                else:
                    conditions.append(GasDetectorRecord.status == s)
            query = query.where(or_(*conditions))
    if next_calibration_before:
        query = query.where(GasDetectorRecord.next_calibration_date <= next_calibration_before)
    if next_calibration_after:
        query = query.where(GasDetectorRecord.next_calibration_date >= next_calibration_after)
    if calibration_date_before:
        query = query.where(GasDetectorRecord.calibration_date <= calibration_date_before)
    if calibration_date_after:
        query = query.where(GasDetectorRecord.calibration_date >= calibration_date_after)
    if keyword:
        query = query.where(
            GasDetectorRecord.instrument_name.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | GasDetectorRecord.detection_model.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | GasDetectorRecord.product_number.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | GasDetectorRecord.installation_location.ilike(f"%{_escape_like(keyword)}%", escape="\\")
            | GasDetectorRecord.manufacturer.ilike(f"%{_escape_like(keyword)}%", escape="\\")
        )
    if has_report is not None:
        sub = select(CalibrationReport.id).where(
            CalibrationReport.gas_detector_id == GasDetectorRecord.id,
            CalibrationReport.is_deleted == False,  # noqa: E712
        )
        if has_report:
            query = query.where(sa_exists(sub))
        else:
            query = query.where(~sa_exists(sub))

    query = query.order_by(GasDetectorRecord.sort_order.asc(), GasDetectorRecord.id.asc())
    result = await db.execute(query)
    return [row[0] for row in result.all()]


async def get_gas_detector_departments(db: AsyncSession) -> list[str]:
    """从 departments 表读取探测器部门列表。"""
    stmt = (
        select(Department.name)
        .where(Department.source == "gas_detector", Department.is_deleted == False)  # noqa: E712
        .distinct()
        .order_by(Department.name)
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all() if row[0]]


async def get_max_gas_detector_sort_order(db: AsyncSession) -> int:
    """获取当前最大的 sort_order，用于新增记录时追加到末尾。"""
    stmt = select(func.coalesce(func.max(GasDetectorRecord.sort_order), 0)).where(
        GasDetectorRecord.is_deleted == False  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.scalar() or 0


async def get_gas_detector_filter_options(
    db: AsyncSession,
) -> dict[str, list[str]]:
    """获取有毒有害可燃探测器所有筛选列的 distinct 值（全表）。"""
    columns = [
        "instrument_name", "detection_model", "product_number",
        "measurement_range",
        "installation_type", "installation_location", "medium",
        "calibration_factor", "manufacturer_supplier", "manufacturer",
        "detection_unit", "calibration_result", "status",
    ]
    result: dict[str, list[str]] = {}

    # 部门：从 departments 表读取
    dept_stmt = (
        select(Department.name)
        .where(Department.source == "gas_detector", Department.is_deleted == False)  # noqa: E712
        .distinct()
        .order_by(Department.name)
    )
    dept_rows = await db.execute(dept_stmt)
    result["department"] = sorted([row[0] for row in dept_rows.all() if row[0]])

    for col in columns:
        col_attr = getattr(GasDetectorRecord, col)
        stmt = (
            select(col_attr)
            .where(GasDetectorRecord.is_deleted == False, col_attr.isnot(None), col_attr != "")  # noqa: E712
            .distinct()
            .order_by(col_attr)
        )
        rows = await db.execute(stmt)
        result[col] = sorted([row[0] for row in rows.all() if row[0] and str(row[0]).strip()])
    return result


async def search_gas_detector_filter_options(
    db: AsyncSession,
    *,
    field: str,
    q: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """按字段名 + 关键字搜索 distinct 值（typeahead）。

    - 允许的字段由 `_GAS_DETECTOR_SEARCHABLE` + department 白名单决定。
    - `q` 为空返回前 `limit` 个 distinct；非空则按 ILIKE 部分匹配。
    - `department` 从 departments 表读取；`status` 并入动态计算的「超期」。
    """
    if field == "department":
        conds = [Department.source == "gas_detector", Department.is_deleted == False]  # noqa: E712
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
        stmt = select(GasDetectorRecord.status).where(
            GasDetectorRecord.is_deleted == False,  # noqa: E712
            GasDetectorRecord.status.isnot(None),
            GasDetectorRecord.status != "",
        ).distinct()
        rows = await db.execute(stmt)
        candidates = sorted(
            {r[0] for r in rows.all() if r[0] and str(r[0]).strip()} | {"超期"}
        )
        if q:
            candidates = [c for c in candidates if q.lower() in c.lower()]
        return {"items": candidates[:limit], "total": len(candidates)}

    col = _GAS_DETECTOR_SEARCHABLE.get(field)
    if col is None:
        raise ValueError(f"不支持的筛选字段: {field}")

    col_conditions: list[Any] = [
        GasDetectorRecord.is_deleted == False,  # noqa: E712
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
