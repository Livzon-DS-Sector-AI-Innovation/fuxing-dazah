"""检定到期提醒查询、总览统计与日期聚合。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import today as time_today
from app.modules.meter import repository as repo
from app.modules.meter.models import GasDetectorRecord, InstrumentRecord
from app.modules.meter.schemas import (
    GasDetectorFilter,
    InstrumentFilter,
    _normalize_department,
)
from app.modules.meter.service.gas_detectors import _gas_detector_like_filters
from app.modules.meter.service.instruments import _instrument_like_filters


async def get_calibration_alerts(
    db: AsyncSession, *, days_before: int = 30, department: str | None = None, source: str | None = None
) -> list[dict[str, Any]]:
    """查询仪表中未来 N 天内到期的记录，合并返回。source 可选 instrument/gas_detector。"""
    instruments: list[InstrumentRecord] = []
    detectors: list[GasDetectorRecord] = []

    if source is None or source == "instrument":
        instruments = await repo.list_instruments_due_for_calibration(db, days_before=days_before)
    if source is None or source == "gas_detector":
        detectors = await repo.list_gas_detectors_due_for_calibration(db, days_before=days_before)

    today = time_today()
    alerts: list[dict[str, Any]] = []

    for obj in instruments:
        days = (obj.next_calibration_date - today).days if obj.next_calibration_date else None
        dept = _normalize_department(obj.department)
        if department and (not dept or department not in dept):
            continue
        alerts.append({
            "source": "instrument",
            "id": str(obj.id),
            "serial_number": obj.serial_number,
            "instrument_name": obj.instrument_name,
            "location": obj.location,
            "department": dept,
            "next_calibration_date": obj.next_calibration_date,
            "days_until_due": days,
        })

    for det in detectors:
        days = (det.next_calibration_date - today).days if det.next_calibration_date else None
        dept = _normalize_department(det.department)
        if department and (not dept or department not in dept):
            continue
        alerts.append({
            "source": "gas_detector",
            "id": str(det.id),
            "serial_number": det.product_number,
            "instrument_name": det.instrument_name,
            "location": det.installation_location,
            "department": dept,
            "next_calibration_date": det.next_calibration_date,
            "days_until_due": days,
        })

    return alerts




async def get_meter_overview(db: AsyncSession, source: str) -> dict[str, int]:
    """获取仪表总览统计数据。"""
    if source == "instrument":
        return await repo.get_instrument_overview(db)
    elif source == "gas_detector":
        return await repo.get_gas_detector_overview(db)
    else:
        raise ValueError(f"不支持的数据源: {source}")


# ═══════════════════════════════════════════
# 日期聚合统计
# ═══════════════════════════════════════════


def _build_date_stats_tree(rows: list[dict[str, int]]) -> list[dict[str, Any]]:
    """将 repo 返回的扁平行 [{year, month, day, count}] 组装为嵌套 year→month→day 结构。"""
    years_map: dict[int, dict[str, Any]] = {}
    for row in rows:
        y = row["year"]
        m = row["month"]
        d = row["day"]
        c = row["count"]

        if y not in years_map:
            years_map[y] = {"year": y, "count": 0, "months": {}}
        years_map[y]["count"] += c

        months_map: dict[int, dict[str, Any]] = years_map[y]["months"]
        if m not in months_map:
            months_map[m] = {"month": m, "count": 0, "days": {}}
        months_map[m]["count"] += c

        days_map: dict[int, dict[str, Any]] = months_map[m]["days"]
        days_map[d] = {"day": d, "count": c}

    # 转为列表并按年份降序、月降序、日降序排列
    result: list[dict[str, Any]] = []
    for y in sorted(years_map.keys(), reverse=True):
        y_data = years_map[y]
        months_list: list[dict[str, Any]] = []
        for m in sorted(y_data["months"].keys(), reverse=True):
            m_data = y_data["months"][m]
            days_list = [
                {"day": d, "count": m_data["days"][d]["count"]}
                for d in sorted(m_data["days"].keys(), reverse=True)
            ]
            months_list.append({"month": m, "count": m_data["count"], "days": days_list})
        result.append({"year": y, "count": y_data["count"], "months": months_list})
    return result


async def get_instrument_date_stats(
    db: AsyncSession, filters: InstrumentFilter, field: str
) -> dict[str, Any]:
    """获取标准计量器具的日期聚合统计。"""
    rows = await repo.get_instrument_date_stats(
        db,
        field=field,
        department=filters.department,
        asset_number=filters.asset_number,
        instrument_name=filters.instrument_name,
        model_spec=filters.model_spec,
        measurement_range=filters.measurement_range,
        accuracy_grade=filters.accuracy_grade,
        serial_number=filters.serial_number,
        location=filters.location,
        manufacturer=filters.manufacturer,
        status=filters.status,
        calibration_unit=filters.calibration_unit,
        calibration_result=filters.calibration_result,
        color_marking=filters.color_marking,
        keyword=filters.keyword,
        like_filters=_instrument_like_filters(filters),
    )
    return {"field": field, "years": _build_date_stats_tree(rows)}


async def get_gas_detector_date_stats(
    db: AsyncSession, filters: GasDetectorFilter, field: str
) -> dict[str, Any]:
    """获取有毒有害可燃探测器的日期聚合统计。"""
    rows = await repo.get_gas_detector_date_stats(
        db,
        field=field,
        department=filters.department,
        instrument_name=filters.instrument_name,
        detection_model=filters.detection_model,
        product_number=filters.product_number,
        measurement_range=filters.measurement_range,
        installation_type=filters.installation_type,
        installation_location=filters.installation_location,
        medium=filters.medium,
        detection_unit=filters.detection_unit,
        calibration_result=filters.calibration_result,
        calibration_factor=filters.calibration_factor,
        manufacturer_supplier=filters.manufacturer_supplier,
        manufacturer=filters.manufacturer,
        status=filters.status,
        keyword=filters.keyword,
        like_filters=_gas_detector_like_filters(filters),
    )
    return {"field": field, "years": _build_date_stats_tree(rows)}


# ═══════════════════════════════════════════
# 部门管理
# ═══════════════════════════════════════════
