"""Meter database queries and persistence."""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.meter.models import (
    CalibrationReport,
    Department,
    GasDetectorRecord,
    InstrumentRecord,
    MeterSettings,
)

# ── 工具函数 ──

_DATE_FIELDS = {"calibration_date", "next_calibration_date", "report_date"}


def _coerce_date_fields(updates: dict[str, Any]) -> None:
    """将 updates 中的日期字符串转为 Python date 对象，兼容 asyncpg 驱动。"""
    for field in _DATE_FIELDS & updates.keys():
        value = updates[field]
        if isinstance(value, str):
            updates[field] = date.fromisoformat(value)


def _parse_multi(value: str | None) -> list[str] | None:
    """将逗号分隔的筛选值拆分为列表，用于 IN 查询。"""
    if not value:
        return None
    parts = [v.strip() for v in value.split(",") if v.strip()]
    return parts if parts else None


# ═══════════════════════════════════════════
# 标准计量器具
# ═══════════════════════════════════════════


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

    if department:
        parts = _parse_multi(department)
        if parts:
            query = query.where(InstrumentRecord.department.in_(parts))
    if status:
        parts = _parse_multi(status)
        if parts:
            today_val = date.today()
            conditions: list = []
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
            InstrumentRecord.asset_number.ilike(f"%{keyword}%")
            | InstrumentRecord.instrument_name.ilike(f"%{keyword}%")
            | InstrumentRecord.model_spec.ilike(f"%{keyword}%")
            | InstrumentRecord.serial_number.ilike(f"%{keyword}%")
            | InstrumentRecord.location.ilike(f"%{keyword}%")
        )

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

    if department:
        parts = _parse_multi(department)
        if parts:
            query = query.where(InstrumentRecord.department.in_(parts))
    if status:
        parts = _parse_multi(status)
        if parts:
            today_val = date.today()
            conditions: list = []
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
            InstrumentRecord.asset_number.ilike(f"%{keyword}%")
            | InstrumentRecord.instrument_name.ilike(f"%{keyword}%")
            | InstrumentRecord.model_spec.ilike(f"%{keyword}%")
            | InstrumentRecord.serial_number.ilike(f"%{keyword}%")
            | InstrumentRecord.location.ilike(f"%{keyword}%")
        )

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


async def list_instruments_due_for_calibration(
    db: AsyncSession, *, days_before: int = 30
) -> list[InstrumentRecord]:
    """查询需检定的标准计量器具。

    days_before = 0  → 截止今天（含所有已过期 + 今天到期）
    days_before > 0  → 未来 N 天内到期
    """
    today = date.today()
    deadline = today + timedelta(days=days_before)
    stmt = select(InstrumentRecord).where(
        InstrumentRecord.is_deleted == False,  # noqa: E712
        InstrumentRecord.next_calibration_date.isnot(None),
        InstrumentRecord.next_calibration_date <= deadline,
    )
    if days_before > 0:
        # 未来 N 天：加下界
        stmt = stmt.where(InstrumentRecord.next_calibration_date >= today)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ═══════════════════════════════════════════
# 有毒有害可燃探测器
# ═══════════════════════════════════════════


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
            today_val = date.today()
            conditions: list = []
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
            GasDetectorRecord.instrument_name.ilike(f"%{keyword}%")
            | GasDetectorRecord.detection_model.ilike(f"%{keyword}%")
            | GasDetectorRecord.product_number.ilike(f"%{keyword}%")
            | GasDetectorRecord.installation_location.ilike(f"%{keyword}%")
        )

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
            today_val = date.today()
            conditions: list = []
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
            GasDetectorRecord.instrument_name.ilike(f"%{keyword}%")
            | GasDetectorRecord.detection_model.ilike(f"%{keyword}%")
            | GasDetectorRecord.product_number.ilike(f"%{keyword}%")
            | GasDetectorRecord.installation_location.ilike(f"%{keyword}%")
        )

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


async def list_gas_detectors_due_for_calibration(
    db: AsyncSession, *, days_before: int = 30
) -> list[GasDetectorRecord]:
    """查询需检定的有毒有害可燃探测器。

    days_before = 0  → 截止今天（含所有已过期 + 今天到期）
    days_before > 0  → 未来 N 天内到期
    """
    today = date.today()
    deadline = today + timedelta(days=days_before)
    stmt = select(GasDetectorRecord).where(
        GasDetectorRecord.is_deleted == False,  # noqa: E712
        GasDetectorRecord.next_calibration_date.isnot(None),
        GasDetectorRecord.next_calibration_date <= deadline,
    )
    if days_before > 0:
        # 未来 N 天：加下界
        stmt = stmt.where(GasDetectorRecord.next_calibration_date >= today)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_instruments_due_grouped(
    db: AsyncSession, department: str,
) -> dict[str, list[InstrumentRecord]]:
    """按 4 个时间窗口分组查询指定部门的标准器具到期记录。

    分组 key: "due_today"（截止今天, 含超期）, "due_7d"（未来 1-7 天）,
             "due_30d"（未来 8-30 天）, "due_90d"（未来 31-90 天）
    """
    today = date.today()
    ranges: list[tuple[str, date | None, date]] = [
        ("due_today", None, today),                                         # 截止今天（含超期）
        ("due_7d", today + timedelta(days=1), today + timedelta(days=7)),   # 1-7 天
        ("due_30d", today + timedelta(days=8), today + timedelta(days=30)), # 8-30 天
        ("due_90d", today + timedelta(days=31), today + timedelta(days=90)),# 31-90 天
    ]

    grouped: dict[str, list[InstrumentRecord]] = {}
    for key, start, end in ranges:
        stmt = select(InstrumentRecord).where(
            InstrumentRecord.is_deleted == False,  # noqa: E712
            InstrumentRecord.department == department,
            InstrumentRecord.next_calibration_date.isnot(None),
            InstrumentRecord.next_calibration_date <= end,
        )
        if start is not None:
            stmt = stmt.where(InstrumentRecord.next_calibration_date >= start)
        result = await db.execute(stmt)
        grouped[key] = list(result.scalars().all())

    return grouped


async def list_gas_detectors_due_grouped(
    db: AsyncSession, department: str,
) -> dict[str, list[GasDetectorRecord]]:
    """按 4 个时间窗口分组查询指定部门的探测器到期记录。

    分组 key: "due_today"（截止今天, 含超期）, "due_7d"（未来 1-7 天）,
             "due_30d"（未来 8-30 天）, "due_90d"（未来 31-90 天）
    """
    today = date.today()
    ranges: list[tuple[str, date | None, date]] = [
        ("due_today", None, today),                                         # 截止今天（含超期）
        ("due_7d", today + timedelta(days=1), today + timedelta(days=7)),   # 1-7 天
        ("due_30d", today + timedelta(days=8), today + timedelta(days=30)), # 8-30 天
        ("due_90d", today + timedelta(days=31), today + timedelta(days=90)),# 31-90 天
    ]

    grouped: dict[str, list[GasDetectorRecord]] = {}
    for key, start, end in ranges:
        stmt = select(GasDetectorRecord).where(
            GasDetectorRecord.is_deleted == False,  # noqa: E712
            GasDetectorRecord.department == department,
            GasDetectorRecord.next_calibration_date.isnot(None),
            GasDetectorRecord.next_calibration_date <= end,
        )
        if start is not None:
            stmt = stmt.where(GasDetectorRecord.next_calibration_date >= start)
        result = await db.execute(stmt)
        grouped[key] = list(result.scalars().all())

    return grouped


async def get_notifiable_departments(db: AsyncSession) -> list[Department]:
    """查询所有开启自动提醒且有负责人的部门。"""
    stmt = select(Department).where(
        Department.is_deleted == False,  # noqa: E712
        Department.auto_notify_enabled == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    # 在 Python 侧过滤：heads 非空
    depts = result.scalars().all()
    return [d for d in depts if d.heads and len(d.heads) > 0]


async def get_instrument_overview(db: AsyncSession) -> dict[str, int]:
    """标准计量器具总览统计。"""
    from sqlalchemy import case

    today = date.today()

    # 子查询计算每条记录的有效状态
    # 在用/超期 + 已过期 → 超期；手动超期 + 未过期/无日期 → 在用
    status_expr = case(
        (
            InstrumentRecord.status.in_(["超期", "在用"])
            & (InstrumentRecord.next_calibration_date < today),
            "超期",
        ),
        (
            (InstrumentRecord.status == "超期")
            & (
                (InstrumentRecord.next_calibration_date >= today)
                | (InstrumentRecord.next_calibration_date.is_(None))
            ),
            "在用",
        ),
        else_=InstrumentRecord.status,
    ).label("effective_status")

    # 基础条件：未删除 + next_calibration_date 存在（用于到期统计）
    base = select(
        func.count().label("total"),
        func.sum(case((status_expr == "在用", 1), else_=0)).label("in_use"),
        func.sum(case((status_expr == "超期", 1), else_=0)).label("overdue"),
        func.sum(case((status_expr == "停用", 1), else_=0)).label("stopped"),
        func.sum(
            case(
                (
                    InstrumentRecord.next_calibration_date.isnot(None)
                    & (InstrumentRecord.next_calibration_date <= today),
                    1,
                ),
                else_=0,
            )
        ).label("due_today"),
        func.sum(
            case(
                (
                    InstrumentRecord.next_calibration_date.isnot(None)
                    & (InstrumentRecord.next_calibration_date >= today)
                    & (InstrumentRecord.next_calibration_date <= today + timedelta(days=7)),
                    1,
                ),
                else_=0,
            )
        ).label("due_7d"),
        func.sum(
            case(
                (
                    InstrumentRecord.next_calibration_date.isnot(None)
                    & (InstrumentRecord.next_calibration_date >= today)
                    & (InstrumentRecord.next_calibration_date <= today + timedelta(days=30)),
                    1,
                ),
                else_=0,
            )
        ).label("due_30d"),
        func.sum(
            case(
                (
                    InstrumentRecord.next_calibration_date.isnot(None)
                    & (InstrumentRecord.next_calibration_date >= today)
                    & (InstrumentRecord.next_calibration_date <= today + timedelta(days=90)),
                    1,
                ),
                else_=0,
            )
        ).label("due_90d"),
    ).where(
        InstrumentRecord.is_deleted == False,  # noqa: E712
    )

    result = await db.execute(base)
    row = result.one()
    return {
        "total": row.total or 0,
        "in_use": row.in_use or 0,
        "overdue": row.overdue or 0,
        "stopped": row.stopped or 0,
        "due_today": row.due_today or 0,
        "due_7d": row.due_7d or 0,
        "due_30d": row.due_30d or 0,
        "due_90d": row.due_90d or 0,
    }


async def get_gas_detector_overview(db: AsyncSession) -> dict[str, int]:
    """有毒有害可燃探测器总览统计。"""
    from sqlalchemy import case

    today = date.today()

    # 子查询计算每条记录的有效状态
    status_expr = case(
        (
            GasDetectorRecord.status.in_(["超期", "在用"])
            & (GasDetectorRecord.next_calibration_date < today),
            "超期",
        ),
        (
            (GasDetectorRecord.status == "超期")
            & (
                (GasDetectorRecord.next_calibration_date >= today)
                | (GasDetectorRecord.next_calibration_date.is_(None))
            ),
            "在用",
        ),
        else_=GasDetectorRecord.status,
    ).label("effective_status")

    base = select(
        func.count().label("total"),
        func.sum(case((status_expr == "在用", 1), else_=0)).label("in_use"),
        func.sum(case((status_expr == "超期", 1), else_=0)).label("overdue"),
        func.sum(case((status_expr == "停用", 1), else_=0)).label("stopped"),
        func.sum(
            case(
                (
                    GasDetectorRecord.next_calibration_date.isnot(None)
                    & (GasDetectorRecord.next_calibration_date <= today),
                    1,
                ),
                else_=0,
            )
        ).label("due_today"),
        func.sum(
            case(
                (
                    GasDetectorRecord.next_calibration_date.isnot(None)
                    & (GasDetectorRecord.next_calibration_date >= today)
                    & (GasDetectorRecord.next_calibration_date <= today + timedelta(days=7)),
                    1,
                ),
                else_=0,
            )
        ).label("due_7d"),
        func.sum(
            case(
                (
                    GasDetectorRecord.next_calibration_date.isnot(None)
                    & (GasDetectorRecord.next_calibration_date >= today)
                    & (GasDetectorRecord.next_calibration_date <= today + timedelta(days=30)),
                    1,
                ),
                else_=0,
            )
        ).label("due_30d"),
        func.sum(
            case(
                (
                    GasDetectorRecord.next_calibration_date.isnot(None)
                    & (GasDetectorRecord.next_calibration_date >= today)
                    & (GasDetectorRecord.next_calibration_date <= today + timedelta(days=90)),
                    1,
                ),
                else_=0,
            )
        ).label("due_90d"),
    ).where(
        GasDetectorRecord.is_deleted == False,  # noqa: E712
    )

    result = await db.execute(base)
    row = result.one()
    return {
        "total": row.total or 0,
        "in_use": row.in_use or 0,
        "overdue": row.overdue or 0,
        "stopped": row.stopped or 0,
        "due_today": row.due_today or 0,
        "due_7d": row.due_7d or 0,
        "due_30d": row.due_30d or 0,
        "due_90d": row.due_90d or 0,
    }


# ═══════════════════════════════════════════
# 检测报告
# ═══════════════════════════════════════════


async def create_report(db: AsyncSession, data: dict[str, Any]) -> CalibrationReport:
    stmt = pg_insert(CalibrationReport).values(**data).returning(CalibrationReport)
    result = await db.execute(stmt)
    await db.flush()
    return result.scalar_one()


async def get_report_by_id(db: AsyncSession, report_id: UUID) -> CalibrationReport | None:
    stmt = select(CalibrationReport).where(
        CalibrationReport.id == report_id,
        CalibrationReport.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_reports_by_instrument(
    db: AsyncSession, instrument_id: UUID
) -> list[CalibrationReport]:
    stmt = select(CalibrationReport).where(
        CalibrationReport.instrument_id == instrument_id,
        CalibrationReport.is_deleted == False,  # noqa: E712
    ).order_by(CalibrationReport.report_date.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_reports_by_gas_detector(
    db: AsyncSession, gas_detector_id: UUID
) -> list[CalibrationReport]:
    stmt = select(CalibrationReport).where(
        CalibrationReport.gas_detector_id == gas_detector_id,
        CalibrationReport.is_deleted == False,  # noqa: E712
    ).order_by(CalibrationReport.report_date.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def soft_delete_report(db: AsyncSession, report_id: UUID) -> bool:
    stmt = (
        sa_update(CalibrationReport)
        .where(CalibrationReport.id == report_id, CalibrationReport.is_deleted == False)  # noqa: E712
        .values(is_deleted=True)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount > 0  # type: ignore[no-any-return,attr-defined]


# ═══════════════════════════════════════════
# 文件匹配查询
# ═══════════════════════════════════════════


async def find_instrument_by_name_and_serial(
    db: AsyncSession, name: str, serial: str
) -> InstrumentRecord | None:
    """按器具名称（模糊）+ 器具编号精确匹配。"""
    stmt = select(InstrumentRecord).where(
        InstrumentRecord.instrument_name.ilike(f"%{name}%"),
        InstrumentRecord.serial_number == serial,
        InstrumentRecord.is_deleted == False,  # noqa: E712
    ).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def find_gas_detector_by_name_and_product(
    db: AsyncSession, name: str, product: str
) -> GasDetectorRecord | None:
    """按器具名称（模糊）+ 产品编号精确匹配。"""
    stmt = select(GasDetectorRecord).where(
        GasDetectorRecord.instrument_name.ilike(f"%{name}%"),
        GasDetectorRecord.product_number == product,
        GasDetectorRecord.is_deleted == False,  # noqa: E712
    ).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ═══════════════════════════════════════════
# 部门管理
# ═══════════════════════════════════════════


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
            )
        )
        dept = existing.scalar_one_or_none()
        if dept is None:
            insert_stmt = pg_insert(Department).values(source=source, name=name)
            await db.execute(insert_stmt)
            added += 1
        elif dept.is_deleted:
            restore_stmt = (
                sa_update(Department)
                .where(Department.id == dept.id)
                .values(is_deleted=False)
            )
            await db.execute(restore_stmt)
            added += 1
    await db.flush()
    return added


# ═══════════════════════════════════════════
# 全局设置
# ═══════════════════════════════════════════


async def get_instrument_date_stats(
    db: AsyncSession,
    *,
    field: str,
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
    keyword: str | None = None,
) -> list[dict[str, int]]:
    """按日期字段的年/月/日三级聚合统计标准计量器具数量。

    返回原始行列表 [{"year": 2026, "month": 3, "day": 15, "count": 7}, ...]，
    由 service 层组装为嵌套结构。
    """
    if field not in ("calibration_date", "next_calibration_date"):
        raise ValueError(f"不支持的日期字段: {field}")
    date_col = getattr(InstrumentRecord, field)

    query = select(
        func.extract("year", date_col).label("year"),
        func.extract("month", date_col).label("month"),
        func.extract("day", date_col).label("day"),
        func.count().label("count"),
    ).where(
        InstrumentRecord.is_deleted == False,  # noqa: E712
        date_col.isnot(None),
    )

    # 复用与 list_instruments 完全一致的筛选条件
    # 多选字段：逗号分隔 → IN 查询
    for col_name in [
        "asset_number", "instrument_name", "model_spec", "measurement_range",
        "accuracy_grade", "serial_number", "location", "manufacturer",
        "calibration_unit", "calibration_result", "color_marking",
    ]:
        value = locals().get(col_name)
        parts = _parse_multi(value)
        if parts:
            col = getattr(InstrumentRecord, col_name)
            query = query.where(col.in_(parts))

    if department:
        parts = _parse_multi(department)
        if parts:
            query = query.where(InstrumentRecord.department.in_(parts))
    if status:
        parts = _parse_multi(status)
        if parts:
            today_val = date.today()
            conditions: list = []
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
    if keyword:
        query = query.where(
            InstrumentRecord.asset_number.ilike(f"%{keyword}%")
            | InstrumentRecord.instrument_name.ilike(f"%{keyword}%")
            | InstrumentRecord.model_spec.ilike(f"%{keyword}%")
            | InstrumentRecord.serial_number.ilike(f"%{keyword}%")
            | InstrumentRecord.location.ilike(f"%{keyword}%")
        )

    query = query.group_by(
        func.extract("year", date_col),
        func.extract("month", date_col),
        func.extract("day", date_col),
    ).order_by(
        func.extract("year", date_col).desc(),
        func.extract("month", date_col).desc(),
        func.extract("day", date_col).desc(),
    )

    result = await db.execute(query)
    return [
        {"year": int(row.year), "month": int(row.month), "day": int(row.day), "count": int(row.count)}  # type: ignore[call-overload]
        for row in result.all()
    ]


async def get_gas_detector_date_stats(
    db: AsyncSession,
    *,
    field: str,
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
    keyword: str | None = None,
) -> list[dict[str, int]]:
    """按日期字段的年/月/日三级聚合统计探测器数量。

    返回原始行列表 [{"year": 2026, "month": 3, "day": 15, "count": 7}, ...]，
    由 service 层组装为嵌套结构。
    """
    if field not in ("calibration_date", "next_calibration_date"):
        raise ValueError(f"不支持的日期字段: {field}")
    date_col = getattr(GasDetectorRecord, field)

    query = select(
        func.extract("year", date_col).label("year"),
        func.extract("month", date_col).label("month"),
        func.extract("day", date_col).label("day"),
        func.count().label("count"),
    ).where(
        GasDetectorRecord.is_deleted == False,  # noqa: E712
        date_col.isnot(None),
    )

    # 多选字段：逗号分隔 → IN 查询
    for col_name in [
        "detection_model", "product_number", "measurement_range",
        "installation_type", "installation_location", "medium",
        "detection_unit", "calibration_result", "calibration_factor",
        "manufacturer_supplier", "manufacturer",
    ]:
        value = locals().get(col_name)
        parts = _parse_multi(value)
        if parts:
            col = getattr(GasDetectorRecord, col_name)
            query = query.where(col.in_(parts))

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
            today_val = date.today()
            conditions: list = []
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
    if keyword:
        query = query.where(
            GasDetectorRecord.instrument_name.ilike(f"%{keyword}%")
            | GasDetectorRecord.detection_model.ilike(f"%{keyword}%")
            | GasDetectorRecord.product_number.ilike(f"%{keyword}%")
            | GasDetectorRecord.installation_location.ilike(f"%{keyword}%")
        )

    query = query.group_by(
        func.extract("year", date_col),
        func.extract("month", date_col),
        func.extract("day", date_col),
    ).order_by(
        func.extract("year", date_col).desc(),
        func.extract("month", date_col).desc(),
        func.extract("day", date_col).desc(),
    )

    result = await db.execute(query)
    return [
        {"year": int(row.year), "month": int(row.month), "day": int(row.day), "count": int(row.count)}  # type: ignore[call-overload]
        for row in result.all()
    ]


# ═══════════════════════════════════════════
# 全局设置
# ═══════════════════════════════════════════


async def get_or_create_meter_settings(db: AsyncSession) -> MeterSettings:
    """获取全局 meter 设置；不存在时创建默认值（17:45）。"""
    result = await db.execute(select(MeterSettings).limit(1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = MeterSettings()
        db.add(settings)
        await db.flush()
    return settings


async def update_meter_settings(
    db: AsyncSession, notify_time: time,
) -> MeterSettings:
    """更新提醒时间并重新拉取配置。"""
    # 先确保只有一行，再更新
    settings = await get_or_create_meter_settings(db)
    stmt = (
        sa_update(MeterSettings)
        .where(MeterSettings.id == settings.id)
        .values(notify_time=notify_time)
    )
    await db.execute(stmt)
    await db.flush()
    result = await db.execute(select(MeterSettings).where(MeterSettings.id == settings.id))
    return result.scalar_one()
