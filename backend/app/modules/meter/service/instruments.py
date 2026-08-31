"""标准计量器具业务工作流。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.meter import repository as repo
from app.modules.meter.models import InstrumentRecord
from app.modules.meter.schemas import (
    InstrumentCreate,
    InstrumentFilter,
    InstrumentUpdate,
)
from app.modules.meter.service.common import _auto_calc_next_calibration_date


def _instrument_like_filters(filters: InstrumentFilter) -> dict[str, str]:
    """从筛选对象提取「文本列部分匹配」参数，供 repo 转成 ILIKE 查询。"""
    return {
        k: v
        for k, v in {
            "asset_number": filters.asset_number_like,
            "instrument_name": filters.instrument_name_like,
            "model_spec": filters.model_spec_like,
            "measurement_range": filters.measurement_range_like,
            "accuracy_grade": filters.accuracy_grade_like,
            "serial_number": filters.serial_number_like,
            "location": filters.location_like,
            "manufacturer": filters.manufacturer_like,
            "calibration_unit": filters.calibration_unit_like,
            "calibration_result": filters.calibration_result_like,
            "color_marking": filters.color_marking_like,
        }.items()
        if v
    }


async def create_instrument(
    db: AsyncSession, data: InstrumentCreate
) -> InstrumentRecord:
    if await repo.exists_instrument_by_asset_number(db, data.asset_number):
        raise DuplicateException("资产编号", data.asset_number)
    values = data.model_dump()
    _auto_calc_next_calibration_date(values)
    max_order = await repo.get_max_instrument_sort_order(db)
    values["sort_order"] = max_order + 1
    return await repo.create_instrument(db, values)


async def batch_create_instruments(
    db: AsyncSession, items: list[dict[str, Any]]
) -> dict[str, Any]:
    """批量新增标准计量器具。"""
    results: list[dict[str, Any]] = []
    created = skipped = 0

    max_order = await repo.get_max_instrument_sort_order(db)

    for i, item in enumerate(items):
        asset_number = item.get("asset_number")
        instrument_name = item.get("instrument_name", "").strip()

        if not instrument_name:
            skipped += 1
            results.append({
                "index": i, "asset_number": asset_number,
                "status": "skipped", "id": None, "message": "器具名称为空",
            })
            continue

        if asset_number:
            try:
                exists = await repo.exists_instrument_by_asset_number(db, asset_number)
            except Exception:
                skipped += 1
                results.append({
                    "index": i, "asset_number": asset_number,
                    "status": "skipped", "id": None, "message": "查询资产编号失败",
                })
                continue
            if exists:
                skipped += 1
                results.append({
                    "index": i, "asset_number": asset_number,
                    "status": "skipped", "id": None, "message": f"资产编号 {asset_number} 已存在",
                })
                continue

        try:
            _auto_calc_next_calibration_date(item)
            max_order += 1
            item["sort_order"] = max_order
            record = await repo.create_instrument(db, item)
            created += 1
            results.append({
                "index": i, "asset_number": asset_number,
                "status": "created", "id": str(record.id), "message": None,
            })
        except Exception as e:
            skipped += 1
            results.append({
                "index": i, "asset_number": asset_number,
                "status": "skipped", "id": None, "message": str(e),
            })

    await db.commit()
    return {"total": len(items), "created": created, "skipped": skipped, "results": results}


async def get_instrument(
    db: AsyncSession, instrument_id: UUID
) -> InstrumentRecord:
    obj = await repo.get_instrument_by_id(db, instrument_id)
    if obj is None:
        raise NotFoundException("标准计量器具", str(instrument_id))
    return obj


async def list_instruments(
    db: AsyncSession, filters: InstrumentFilter
) -> tuple[list[InstrumentRecord], int]:
    return await repo.list_instruments(
        db,
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
        next_calibration_before=filters.next_calibration_before,
        next_calibration_after=filters.next_calibration_after,
        calibration_date_before=filters.calibration_date_before,
        calibration_date_after=filters.calibration_date_after,
        keyword=filters.keyword,
        has_report=filters.has_report,
        like_filters=_instrument_like_filters(filters),
        page=filters.page,
        page_size=filters.page_size,
    )


async def update_instrument(
    db: AsyncSession, instrument_id: UUID, data: InstrumentUpdate
) -> InstrumentRecord:
    obj = await repo.get_instrument_by_id(db, instrument_id, include_reports=False)
    if obj is None:
        raise NotFoundException("标准计量器具", str(instrument_id))

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        # 无变更时也需 re-fetch reports，否则 API 层访问 .reports 会触发 MissingGreenlet
        obj = await repo.get_instrument_by_id(db, instrument_id, include_reports=True)
        if obj is None:
            raise NotFoundException("标准计量器具", str(instrument_id))
        return obj

    # 如果修改了 asset_number，检查唯一性
    if "asset_number" in updates and updates["asset_number"] != obj.asset_number:
        if await repo.exists_instrument_by_asset_number(
            db, updates["asset_number"], exclude_id=instrument_id
        ):
            raise DuplicateException("资产编号", updates["asset_number"])

    # 自动计算下次检定日期（如果只改了检定日期/周期而未提供 next）；
    # 显式传了 next_calibration_date（含 null=清空）时尊重用户意图，不自动推算
    if "next_calibration_date" not in updates:
        _auto_calc_next_calibration_date(updates)

    updated = await repo.update_instrument(db, instrument_id, updates)
    if updated is None:
        raise NotFoundException("标准计量器具", str(instrument_id))
    return updated


async def delete_instrument(db: AsyncSession, instrument_id: UUID) -> None:
    deleted = await repo.soft_delete_instrument(db, instrument_id)
    if not deleted:
        raise NotFoundException("标准计量器具", str(instrument_id))


async def batch_delete_instruments(db: AsyncSession, ids: list[UUID]) -> int:
    """批量软删除标准计量器具，返回实际删除数。"""
    return await repo.batch_soft_delete_instruments(db, ids)


async def get_all_instrument_ids(
    db: AsyncSession, filters: InstrumentFilter
) -> list[UUID]:
    """获取当前筛选条件下的所有记录 ID。"""
    return await repo.get_all_instrument_ids(
        db,
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
        next_calibration_before=filters.next_calibration_before,
        next_calibration_after=filters.next_calibration_after,
        calibration_date_before=filters.calibration_date_before,
        calibration_date_after=filters.calibration_date_after,
        keyword=filters.keyword,
        has_report=filters.has_report,
        like_filters=_instrument_like_filters(filters),
    )


async def get_instrument_departments(db: AsyncSession) -> list[str]:
    return await repo.get_instrument_departments(db)


async def search_instrument_filter_options(
    db: AsyncSession, *, field: str, q: str | None = None, limit: int = 50
) -> dict[str, Any]:
    """按字段 + 关键字搜索筛选项（typeahead）。"""
    return await repo.search_instrument_filter_options(db, field=field, q=q, limit=limit)


# ═══════════════════════════════════════════
# 有毒有害可燃探测器
# ═══════════════════════════════════════════


async def get_instrument_filter_options(db: AsyncSession) -> dict[str, list[str]]:
    """获取标准计量器具所有筛选列的 distinct 值。"""
    options = await repo.get_instrument_filter_options(db)
    # "超期" 是动态计算的状态，不在数据库中存储，需要手动加入筛选选项
    if "超期" not in options.get("status", []):
        options.setdefault("status", []).insert(0, "超期")
    return options
