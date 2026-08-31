"""有毒有害可燃探测器业务工作流。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.meter import repository as repo
from app.modules.meter.models import GasDetectorRecord
from app.modules.meter.schemas import (
    GasDetectorCreate,
    GasDetectorFilter,
    GasDetectorUpdate,
)


def _gas_detector_like_filters(filters: GasDetectorFilter) -> dict[str, str]:
    """从筛选对象提取「文本列部分匹配」参数，供 repo 转成 ILIKE 查询。"""
    return {
        k: v
        for k, v in {
            "instrument_name": filters.instrument_name_like,
            "detection_model": filters.detection_model_like,
            "product_number": filters.product_number_like,
            "measurement_range": filters.measurement_range_like,
            "installation_type": filters.installation_type_like,
            "installation_location": filters.installation_location_like,
            "medium": filters.medium_like,
            "calibration_factor": filters.calibration_factor_like,
            "manufacturer_supplier": filters.manufacturer_supplier_like,
            "manufacturer": filters.manufacturer_like,
            "detection_unit": filters.detection_unit_like,
            "calibration_result": filters.calibration_result_like,
        }.items()
        if v
    }


async def batch_create_gas_detectors(
    db: AsyncSession, items: list[dict[str, Any]]
) -> dict[str, Any]:
    """批量新增有毒有害可燃探测器。"""
    results: list[dict[str, Any]] = []
    created = skipped = 0

    max_order = await repo.get_max_gas_detector_sort_order(db)

    for i, item in enumerate(items):
        instrument_name = item.get("instrument_name", "").strip()

        if not instrument_name:
            skipped += 1
            results.append({
                "index": i, "asset_number": None,
                "status": "skipped", "id": None, "message": "器具名称为空",
            })
            continue

        try:
            max_order += 1
            item["sort_order"] = max_order
            record = await repo.create_gas_detector(db, item)
            created += 1
            results.append({
                "index": i, "asset_number": None,
                "status": "created", "id": str(record.id), "message": None,
            })
        except Exception as e:
            skipped += 1
            results.append({
                "index": i, "asset_number": None,
                "status": "skipped", "id": None, "message": str(e),
            })

    await db.commit()
    return {"total": len(items), "created": created, "skipped": skipped, "results": results}


async def create_gas_detector(
    db: AsyncSession, data: GasDetectorCreate
) -> GasDetectorRecord:
    if data.product_number and await repo.exists_gas_detector_by_product_number(
        db, data.product_number
    ):
        raise DuplicateException("产品编号", data.product_number)
    values = data.model_dump()
    max_order = await repo.get_max_gas_detector_sort_order(db)
    values["sort_order"] = max_order + 1
    return await repo.create_gas_detector(db, values)


async def get_gas_detector(
    db: AsyncSession, detector_id: UUID
) -> GasDetectorRecord:
    obj = await repo.get_gas_detector_by_id(db, detector_id)
    if obj is None:
        raise NotFoundException("有毒有害可燃探测器", str(detector_id))
    return obj


async def list_gas_detectors(
    db: AsyncSession, filters: GasDetectorFilter
) -> tuple[list[GasDetectorRecord], int]:
    return await repo.list_gas_detectors(
        db,
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
        next_calibration_before=filters.next_calibration_before,
        next_calibration_after=filters.next_calibration_after,
        calibration_date_before=filters.calibration_date_before,
        calibration_date_after=filters.calibration_date_after,
        keyword=filters.keyword,
        has_report=filters.has_report,
        like_filters=_gas_detector_like_filters(filters),
        page=filters.page,
        page_size=filters.page_size,
    )


async def update_gas_detector(
    db: AsyncSession, detector_id: UUID, data: GasDetectorUpdate
) -> GasDetectorRecord:
    obj = await repo.get_gas_detector_by_id(db, detector_id, include_reports=False)
    if obj is None:
        raise NotFoundException("有毒有害可燃探测器", str(detector_id))

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        # 无变更时也需 re-fetch reports，否则 API 层访问 .reports 会触发 MissingGreenlet
        obj = await repo.get_gas_detector_by_id(db, detector_id, include_reports=True)
        if obj is None:
            raise NotFoundException("有毒有害可燃探测器", str(detector_id))
        return obj

    if "product_number" in updates and updates["product_number"] != obj.product_number:
        if updates["product_number"] and await repo.exists_gas_detector_by_product_number(
            db, updates["product_number"], exclude_id=detector_id
        ):
            raise DuplicateException("产品编号", updates["product_number"])

    updated = await repo.update_gas_detector(db, detector_id, updates)
    if updated is None:
        raise NotFoundException("有毒有害可燃探测器", str(detector_id))
    return updated


async def delete_gas_detector(db: AsyncSession, detector_id: UUID) -> None:
    deleted = await repo.soft_delete_gas_detector(db, detector_id)
    if not deleted:
        raise NotFoundException("有毒有害可燃探测器", str(detector_id))


async def batch_delete_gas_detectors(db: AsyncSession, ids: list[UUID]) -> int:
    """批量软删除有毒有害可燃探测器，返回实际删除数。"""
    return await repo.batch_soft_delete_gas_detectors(db, ids)


async def get_all_gas_detector_ids(
    db: AsyncSession, filters: GasDetectorFilter
) -> list[UUID]:
    """获取当前筛选条件下的所有记录 ID。"""
    return await repo.get_all_gas_detector_ids(
        db,
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
        next_calibration_before=filters.next_calibration_before,
        next_calibration_after=filters.next_calibration_after,
        calibration_date_before=filters.calibration_date_before,
        calibration_date_after=filters.calibration_date_after,
        keyword=filters.keyword,
        has_report=filters.has_report,
        like_filters=_gas_detector_like_filters(filters),
    )


async def get_gas_detector_departments(db: AsyncSession) -> list[str]:
    return await repo.get_gas_detector_departments(db)


async def search_gas_detector_filter_options(
    db: AsyncSession, *, field: str, q: str | None = None, limit: int = 50
) -> dict[str, Any]:
    """按字段 + 关键字搜索筛选项（typeahead）。"""
    return await repo.search_gas_detector_filter_options(db, field=field, q=q, limit=limit)


async def get_gas_detector_filter_options(db: AsyncSession) -> dict[str, list[str]]:
    """获取有毒有害可燃探测器所有筛选列的 distinct 值。"""
    options = await repo.get_gas_detector_filter_options(db)
    # "超期" 是动态计算的状态，不在数据库中存储，需要手动加入筛选选项
    if "超期" not in options.get("status", []):
        options.setdefault("status", []).insert(0, "超期")
    return options


# ═══════════════════════════════════════════
# 检测报告
# ═══════════════════════════════════════════
