"""Quality 模块数据读写。只负责查询与持久化，不做业务判断。"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.models import (
    InspectionImpurity,
    InspectionRecord,
)

# ─── 检验记录 ───


async def create_inspection_record(
    db: AsyncSession,
    product_name: str,
    batch_number: str,
    form_id: str | None,
    standard_type: str | None,
    total_peak_area_a_first: float | None,
    total_peak_area_a_second: float | None,
    main_peak_area_a_first: float | None,
    main_peak_area_a_second: float | None,
    total_impurity_area_first: float | None,
    total_impurity_area_second: float | None,
    any_unknown_impurity_first: float | None,
    any_unknown_impurity_second: float | None,
    main_peak_area_b_first: float | None,
    main_peak_area_b_second: float | None,
    all_pass: bool,
    raw_data: dict[str, Any] | None = None,
    excel_filename: str | None = None,
) -> InspectionRecord:
    """创建检验记录。INSERT 后 flush 返回（RETURNING 自动回填 id 等）。"""
    record = InspectionRecord(
        product_name=product_name,
        batch_number=batch_number,
        form_id=form_id,
        standard_type=standard_type,
        total_peak_area_a_first=total_peak_area_a_first,
        total_peak_area_a_second=total_peak_area_a_second,
        main_peak_area_a_first=main_peak_area_a_first,
        main_peak_area_a_second=main_peak_area_a_second,
        total_impurity_area_first=total_impurity_area_first,
        total_impurity_area_second=total_impurity_area_second,
        any_unknown_impurity_first=any_unknown_impurity_first,
        any_unknown_impurity_second=any_unknown_impurity_second,
        main_peak_area_b_first=main_peak_area_b_first,
        main_peak_area_b_second=main_peak_area_b_second,
        all_pass=all_pass,
        raw_data=raw_data,
        excel_filename=excel_filename,
    )
    db.add(record)
    await db.flush()
    return record


async def get_inspection_record(
    db: AsyncSession, record_id: uuid.UUID
) -> InspectionRecord | None:
    """按 ID 查询检验记录。"""
    stmt = select(InspectionRecord).where(
        InspectionRecord.id == record_id,
        InspectionRecord.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_inspection_by_batch(
    db: AsyncSession, product_name: str, batch_number: str
) -> InspectionRecord | None:
    """按产品名+批号查询检验记录（用于去重检查）。"""
    stmt = select(InspectionRecord).where(
        InspectionRecord.product_name == product_name,
        InspectionRecord.batch_number == batch_number,
        InspectionRecord.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_inspection_records(
    db: AsyncSession,
    product_name: str | None = None,
    batch_number: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InspectionRecord], int]:
    """分页查询检验记录列表。"""
    stmt = select(InspectionRecord).where(
        InspectionRecord.is_deleted == False  # noqa: E712
    )
    if product_name:
        stmt = stmt.where(InspectionRecord.product_name.ilike(f"%{product_name}%"))
    if batch_number:
        stmt = stmt.where(InspectionRecord.batch_number.ilike(f"%{batch_number}%"))

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = (
        stmt.order_by(InspectionRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars())
    return items, total


async def delete_inspection_record(
    db: AsyncSession, record_id: uuid.UUID
) -> InspectionRecord | None:
    """软删除检验记录（同时删除关联杂质明细）。"""
    record = await get_inspection_record(db, record_id)
    if not record:
        return None
    record.is_deleted = True

    # 同步删除关联杂质明细
    impurities = await get_impurities_by_record(db, record_id)
    for imp in impurities:
        imp.is_deleted = True

    await db.flush()
    # UPDATE 后 re-fetch（不过滤 is_deleted，确保软删除后也能查到）
    stmt = select(InspectionRecord).where(InspectionRecord.id == record_id)
    return (await db.execute(stmt)).scalar_one_or_none()


# ─── 杂质明细 ───


async def create_impurities(
    db: AsyncSession,
    inspection_record_id: uuid.UUID,
    impurities: list[dict[str, Any]],
) -> list[InspectionImpurity]:
    """批量创建杂质明细。INSERT 后 flush 返回。"""
    items = []
    for imp_data in impurities:
        imp = InspectionImpurity(
            inspection_record_id=inspection_record_id,
            name=imp_data["name"],
            first_percent=imp_data.get("first_percent"),
            second_percent=imp_data.get("second_percent"),
            limit_value=imp_data.get("limit"),
            is_pass=imp_data.get("is_pass", True),
        )
        db.add(imp)
        items.append(imp)
    await db.flush()
    return items


async def get_impurities_by_record(
    db: AsyncSession, inspection_record_id: uuid.UUID
) -> list[InspectionImpurity]:
    """获取某条检验记录的所有杂质明细。"""
    stmt = select(InspectionImpurity).where(
        InspectionImpurity.inspection_record_id == inspection_record_id,
        InspectionImpurity.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())
