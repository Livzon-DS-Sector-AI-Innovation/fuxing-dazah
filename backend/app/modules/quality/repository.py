"""Quality 模块数据读写。只负责查询与持久化，不做业务判断。"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.models import (
    InspectionImpurity,
    InspectionRecord,
    QualityStandardDocument,
    QualityStandardItem,
    ReportRecord,
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
    has_oot: bool,
    raw_data: dict | None = None,
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
        has_oot=has_oot,
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
    impurities: list[dict],
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


# ─── 报告单 ───


async def create_report_record(
    db: AsyncSession,
    inspection_record_id: uuid.UUID,
    template_path: str,
    product_name: str,
    batch_number: str,
    file_path: str | None = None,
    file_size: int | None = None,
) -> ReportRecord:
    """创建报告单记录。"""
    report = ReportRecord(
        inspection_record_id=inspection_record_id,
        template_path=template_path,
        product_name=product_name,
        batch_number=batch_number,
        file_path=file_path,
        file_size=file_size,
    )
    db.add(report)
    await db.flush()
    return report


async def get_report_record(
    db: AsyncSession, report_id: uuid.UUID
) -> ReportRecord | None:
    """按 ID 查询报告单记录。"""
    stmt = select(ReportRecord).where(
        ReportRecord.id == report_id,
        ReportRecord.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_report_records(
    db: AsyncSession,
    product_name: str | None = None,
    batch_number: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ReportRecord], int]:
    """分页查询报告单列表。"""
    stmt = select(ReportRecord).where(
        ReportRecord.is_deleted == False  # noqa: E712
    )
    if product_name:
        stmt = stmt.where(ReportRecord.product_name.ilike(f"%{product_name}%"))
    if batch_number:
        stmt = stmt.where(ReportRecord.batch_number.ilike(f"%{batch_number}%"))

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = (
        stmt.order_by(ReportRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars())
    return items, total


# ─── 汇总查询 ───


async def get_product_names(db: AsyncSession) -> list[str]:
    """获取所有检验过的产品名称（去重）。"""
    stmt = (
        select(InspectionRecord.product_name)
        .where(InspectionRecord.is_deleted == False)  # noqa: E712
        .distinct()
        .order_by(InspectionRecord.product_name)
    )
    return list((await db.execute(stmt)).scalars())


async def get_summary_by_product(
    db: AsyncSession,
    product_name: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    """按产品/时间段聚合汇总统计（SQL 聚合，不加载全量数据）。"""
    from sqlalchemy import case

    # 总体统计
    base_where = [InspectionRecord.is_deleted == False]  # noqa: E712
    if product_name:
        base_where.append(InspectionRecord.product_name == product_name)
    if date_from:
        base_where.append(InspectionRecord.created_at >= date_from)
    if date_to:
        base_where.append(InspectionRecord.created_at <= date_to)

    agg = select(
        func.count().label("total"),
        func.count().filter(InspectionRecord.all_pass == True).label("pass_count"),  # noqa: E712
        func.count().filter(InspectionRecord.has_oot == True).label("oot_count"),  # noqa: E712
    ).where(*base_where)
    row = (await db.execute(agg)).one()
    total, pass_count, oot_count = row.total, row.pass_count, row.oot_count

    if total == 0:
        return {
            "total": 0, "pass_count": 0, "fail_count": 0,
            "oot_count": 0, "pass_rate": 0.0, "products": [],
        }

    # 按产品分组
    product_agg = select(
        InspectionRecord.product_name,
        func.count().label("total"),
        func.count().filter(InspectionRecord.all_pass == True).label("pass_count"),  # noqa: E712
        func.count().filter(InspectionRecord.has_oot == True).label("oot_count"),  # noqa: E712
    ).where(*base_where).group_by(InspectionRecord.product_name).order_by(InspectionRecord.product_name)
    product_rows = (await db.execute(product_agg)).all()

    products = [
        {
            "product_name": r.product_name,
            "total": r.total,
            "pass_count": r.pass_count,
            "fail_count": r.total - r.pass_count,
            "oot_count": r.oot_count,
        }
        for r in product_rows
    ]

    return {
        "total": total,
        "pass_count": pass_count,
        "fail_count": total - pass_count,
        "oot_count": oot_count,
        "pass_rate": round(pass_count / total * 100, 1),
        "products": products,
    }


# ─── 质量标准文档 / 项目行（SOP 号为匹配键）───


async def list_standard_documents(
    db: AsyncSession,
    product_name: str | None = None,
) -> list[QualityStandardDocument]:
    stmt = select(QualityStandardDocument).where(
        QualityStandardDocument.is_deleted == False  # noqa: E712
    )
    if product_name:
        stmt = stmt.where(QualityStandardDocument.product_name.ilike(f"%{product_name}%"))
    stmt = stmt.order_by(QualityStandardDocument.product_name, QualityStandardDocument.file_no)
    return list((await db.execute(stmt)).scalars())


async def get_standard_document(
    db: AsyncSession, doc_id: uuid.UUID
) -> QualityStandardDocument | None:
    stmt = select(QualityStandardDocument).where(
        QualityStandardDocument.id == doc_id,
        QualityStandardDocument.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_standard_document(
    db: AsyncSession, data: dict
) -> QualityStandardDocument:
    doc = QualityStandardDocument(**data)
    db.add(doc)
    await db.flush()
    return doc


async def update_standard_document(
    db: AsyncSession, doc_id: uuid.UUID, **kwargs
) -> QualityStandardDocument | None:
    doc = await get_standard_document(db, doc_id)
    if not doc:
        return None
    for key, val in kwargs.items():
        if hasattr(doc, key) and val is not None:
            setattr(doc, key, val)
    await db.flush()
    return doc


async def delete_standard_document(
    db: AsyncSession, doc_id: uuid.UUID
) -> QualityStandardDocument | None:
    doc = await get_standard_document(db, doc_id)
    if not doc:
        return None
    doc.is_deleted = True
    items = await list_standard_items(db, doc_id)
    for it in items:
        it.is_deleted = True
    await db.flush()
    return doc


async def list_standard_items(
    db: AsyncSession, doc_id: uuid.UUID
) -> list[QualityStandardItem]:
    stmt = select(QualityStandardItem).where(
        QualityStandardItem.document_id == doc_id,
        QualityStandardItem.is_deleted == False,  # noqa: E712
    ).order_by(QualityStandardItem.seq, QualityStandardItem.created_at)
    return list((await db.execute(stmt)).scalars())


async def create_standard_item(
    db: AsyncSession, doc_id: uuid.UUID, data: dict
) -> QualityStandardItem:
    item = QualityStandardItem(document_id=doc_id, **data)
    db.add(item)
    await db.flush()
    return item


async def update_standard_item(
    db: AsyncSession, item_id: uuid.UUID, **kwargs
) -> QualityStandardItem | None:
    stmt = select(QualityStandardItem).where(
        QualityStandardItem.id == item_id,
        QualityStandardItem.is_deleted == False,  # noqa: E712
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if not item:
        return None
    for key, val in kwargs.items():
        if hasattr(item, key) and val is not None:
            setattr(item, key, val)
    await db.flush()
    return item


async def delete_standard_item(
    db: AsyncSession, item_id: uuid.UUID
) -> QualityStandardItem | None:
    stmt = select(QualityStandardItem).where(
        QualityStandardItem.id == item_id,
        QualityStandardItem.is_deleted == False,  # noqa: E712
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if not item:
        return None
    item.is_deleted = True
    await db.flush()
    return item


async def get_standard_item_by_sop(
    db: AsyncSession, sop_no: str
) -> list[QualityStandardItem]:
    """按 SOP 号查标准行（同名项目不同 SOP 的匹配入口）。"""
    stmt = select(QualityStandardItem).where(
        QualityStandardItem.sop_no == sop_no,
        QualityStandardItem.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())
