"""检定/下次检定日期年-月-日聚合统计查询。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import today as time_today
from app.modules.meter.models import GasDetectorRecord, InstrumentRecord
from app.modules.meter.repository._utils import _parse_multi


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
