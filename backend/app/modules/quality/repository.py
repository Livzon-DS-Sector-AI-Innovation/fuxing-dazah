"""Quality 模块数据读写。只负责查询与持久化，不做业务判断。"""

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.models import (
    CoaTemplateBinding,
    InspectionImpurity,
    InspectionRecord,
    LcTemplateConfig,
    QualityStandardDocument,
    QualityStandardItem,
    QualityTestResult,
    QualityTestTask,
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
    template_path: str,
    product_name: str,
    batch_number: str,
    inspection_record_id: uuid.UUID | None = None,
    test_task_id: uuid.UUID | None = None,
    file_path: str | None = None,
    file_size: int | None = None,
) -> ReportRecord:
    """创建报告单记录（inspection_record_id 与 test_task_id 二选一，P2 任务驱动 COA）。"""
    report = ReportRecord(
        inspection_record_id=inspection_record_id,
        test_task_id=test_task_id,
        template_path=template_path,
        product_name=product_name,
        batch_number=batch_number,
        file_path=file_path,
        file_size=file_size,
    )
    db.add(report)
    await db.flush()
    return report


async def count_report_records_since(
    db: AsyncSession, since: datetime
) -> int:
    """统计某时间点之后生成的报告单数（流水号用）。"""
    stmt = select(func.count()).where(
        ReportRecord.is_deleted == False,  # noqa: E712
        ReportRecord.created_at >= since,
    )
    return int((await db.execute(stmt)).scalar_one())


async def get_latest_report_record_by_task(
    db: AsyncSession, task_id: uuid.UUID
) -> ReportRecord | None:
    """任务最近一次生成的报告单记录（进度查询「已出报时间」用）。"""
    stmt = select(ReportRecord).where(
        ReportRecord.test_task_id == task_id,
        ReportRecord.is_deleted == False,  # noqa: E712
    ).order_by(ReportRecord.created_at.desc())
    return (await db.execute(stmt)).scalars().first()


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
    ).where(*base_where)
    row = (await db.execute(agg)).one()
    total, pass_count = row.total, row.pass_count

    if total == 0:
        return {
            "total": 0, "pass_count": 0, "fail_count": 0,
            "pass_rate": 0.0, "products": [],
        }

    # 按产品分组
    product_agg = select(
        InspectionRecord.product_name,
        func.count().label("total"),
        func.count().filter(InspectionRecord.all_pass == True).label("pass_count"),  # noqa: E712
    ).where(*base_where).group_by(InspectionRecord.product_name).order_by(InspectionRecord.product_name)
    product_rows = (await db.execute(product_agg)).all()

    products = [
        {
            "product_name": r.product_name,
            "total": r.total,
            "pass_count": r.pass_count,
            "fail_count": r.total - r.pass_count,
        }
        for r in product_rows
    ]

    return {
        "total": total,
        "pass_count": pass_count,
        "fail_count": total - pass_count,
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


async def get_standard_document_by_file_no(
    db: AsyncSession, file_no: str
) -> QualityStandardDocument | None:
    """按文件编号查标准文档（表号↔标准文档映射用）。"""
    stmt = select(QualityStandardDocument).where(
        QualityStandardDocument.file_no == file_no,
        QualityStandardDocument.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


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


async def list_standard_documents_by_product(
    db: AsyncSession, product_name: str
) -> list[QualityStandardDocument]:
    """按产品名称查询全部标准文档（忽略名称中的空白差异，如半角空格）。

    同一产品的不同文档可能因导入批次不同而名称写法略有差异（如
    「Vancomycin Hydrochloride」vs「VancomycinHydrochloride」），
    建任务快照时必须全部命中，否则漏其他代号的项目行。
    """
    norm = re.sub(r"\s+", "", product_name)
    stmt = select(QualityStandardDocument).where(
        func.regexp_replace(QualityStandardDocument.product_name, r"\s", "", "g") == norm,
        QualityStandardDocument.is_deleted == False,  # noqa: E712
    ).order_by(QualityStandardDocument.created_at.desc())
    return list((await db.execute(stmt)).scalars())


# ─── COA 模板 ↔ 标准文档绑定（COA 唯一，SOP 可多 COA）───


async def list_coa_bindings(db: AsyncSession) -> list[CoaTemplateBinding]:
    stmt = select(CoaTemplateBinding).where(
        CoaTemplateBinding.is_deleted == False,  # noqa: E712
    ).order_by(CoaTemplateBinding.template_path)
    return list((await db.execute(stmt)).scalars())


async def get_coa_binding_by_template(
    db: AsyncSession, template_path: str
) -> CoaTemplateBinding | None:
    stmt = select(CoaTemplateBinding).where(
        CoaTemplateBinding.template_path == template_path,
        CoaTemplateBinding.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def upsert_coa_binding(
    db: AsyncSession,
    template_path: str,
    standard_document_id: uuid.UUID | None = None,
    sop_no: str | None = None,
    description: str | None = None,
) -> CoaTemplateBinding:
    """按模板路径 upsert（COA 唯一性）；返回 UPDATE 后 re-fetch 对象。"""
    binding = await get_coa_binding_by_template(db, template_path)
    if binding:
        binding.standard_document_id = standard_document_id or binding.standard_document_id
        binding.sop_no = sop_no or binding.sop_no
        if description is not None:
            binding.description = description
        await db.flush()
    else:
        binding = CoaTemplateBinding(
            template_path=template_path,
            standard_document_id=standard_document_id,
            sop_no=sop_no,
            description=description,
        )
        db.add(binding)
        await db.flush()
    stmt = select(CoaTemplateBinding).where(CoaTemplateBinding.id == binding.id)
    return (await db.execute(stmt)).scalar_one()


async def delete_coa_binding(
    db: AsyncSession, template_path: str
) -> CoaTemplateBinding | None:
    binding = await get_coa_binding_by_template(db, template_path)
    if not binding:
        return None
    binding.is_deleted = True
    await db.flush()
    stmt = select(CoaTemplateBinding).where(CoaTemplateBinding.id == binding.id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_coa_bindings_by_docs(
    db: AsyncSession, doc_ids: list[uuid.UUID]
) -> list[CoaTemplateBinding]:
    if not doc_ids:
        return []
    stmt = select(CoaTemplateBinding).where(
        CoaTemplateBinding.standard_document_id.in_(doc_ids),
        CoaTemplateBinding.is_deleted == False,  # noqa: E712
    ).order_by(CoaTemplateBinding.created_at)
    return list((await db.execute(stmt)).scalars())


# ─── 液相计算表模板配置 ───


async def get_lc_template_by_table_no(
    db: AsyncSession, table_no: str
) -> LcTemplateConfig | None:
    """按表号查模板配置（EX-xx-xxxx-vvv）。"""
    stmt = select(LcTemplateConfig).where(
        LcTemplateConfig.table_no == table_no,
        LcTemplateConfig.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_lc_template_configs(db: AsyncSession) -> list[LcTemplateConfig]:
    stmt = select(LcTemplateConfig).where(
        LcTemplateConfig.is_deleted == False,  # noqa: E712
    ).order_by(LcTemplateConfig.table_no)
    return list((await db.execute(stmt)).scalars())


# ─── 检验任务 ───


async def create_test_task(
    db: AsyncSession,
    product_name: str,
    batch_number: str,
    production_date: str | None,
    expiry_date: str | None,
    specification: str | None,
    form_id: str | None,
    standard_document_id: uuid.UUID | None,
    report_date: str | None = None,
) -> QualityTestTask:
    """创建任务。INSERT 后 flush 返回（RETURNING 回填 id）。"""
    task = QualityTestTask(
        product_name=product_name,
        batch_number=batch_number,
        production_date=production_date,
        expiry_date=expiry_date,
        specification=specification,
        form_id=form_id,
        standard_document_id=standard_document_id,
        report_date=report_date,
    )
    db.add(task)
    await db.flush()
    return task


async def get_test_task(db: AsyncSession, task_id: uuid.UUID) -> QualityTestTask | None:
    """按 ID 查询任务（过滤软删）。"""
    stmt = select(QualityTestTask).where(
        QualityTestTask.id == task_id,
        QualityTestTask.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_test_task_by_batch_number(
    db: AsyncSession, batch_number: str
) -> QualityTestTask | None:
    """仅按批号查未删除任务（飞书对话式填报：无需产品名）。"""
    stmt = select(QualityTestTask).where(
        QualityTestTask.batch_number == batch_number,
        QualityTestTask.is_deleted == False,  # noqa: E712
    ).order_by(QualityTestTask.created_at.desc())
    return (await db.execute(stmt)).scalars().first()


async def list_test_tasks_by_report_date(
    db: AsyncSession, report_date: str
) -> list[QualityTestTask]:
    """按出报日期查未作废任务（出报当日机器人每日推送）。"""
    stmt = select(QualityTestTask).where(
        QualityTestTask.report_date == report_date,
        QualityTestTask.status != "void",
        QualityTestTask.is_deleted == False,  # noqa: E712
    ).order_by(QualityTestTask.product_name, QualityTestTask.batch_number)
    return list((await db.execute(stmt)).scalars())


async def get_test_task_by_batch(
    db: AsyncSession, product_name: str, batch_number: str
) -> QualityTestTask | None:
    """按产品+批号查未删除任务（建任务重复检查；产品名忽略空白差异）。"""
    norm = re.sub(r"\s+", "", product_name)
    stmt = select(QualityTestTask).where(
        func.regexp_replace(QualityTestTask.product_name, r"\s", "", "g") == norm,
        QualityTestTask.batch_number == batch_number,
        QualityTestTask.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_test_tasks(
    db: AsyncSession,
    product_name: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[QualityTestTask], int]:
    """分页查询任务列表。"""
    stmt = select(QualityTestTask).where(QualityTestTask.is_deleted == False)  # noqa: E712
    if product_name:
        stmt = stmt.where(QualityTestTask.product_name.ilike(f"%{product_name}%"))
    if status:
        stmt = stmt.where(QualityTestTask.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(QualityTestTask.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars())
    return items, total


async def update_test_task(
    db: AsyncSession, task_id: uuid.UUID, **kwargs: Any
) -> QualityTestTask | None:
    """更新任务字段。UPDATE 后 flush + re-fetch（不过滤 is_deleted）。"""
    task = await get_test_task(db, task_id)
    if not task:
        return None
    for key, val in kwargs.items():
        if hasattr(task, key) and val is not None:
            setattr(task, key, val)
    await db.flush()
    stmt = select(QualityTestTask).where(QualityTestTask.id == task_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def update_test_task_report_date(
    db: AsyncSession, task_id: uuid.UUID, report_date: str | None
) -> QualityTestTask | None:
    """补录/清空出报日期（允许 None 清空）。UPDATE 后 flush + re-fetch。"""
    task = await get_test_task(db, task_id)
    if not task:
        return None
    task.report_date = report_date
    await db.flush()
    stmt = select(QualityTestTask).where(QualityTestTask.id == task_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def delete_test_task(db: AsyncSession, task_id: uuid.UUID) -> QualityTestTask | None:
    """软删除任务并级联软删结果行。"""
    task = await get_test_task(db, task_id)
    if not task:
        return None
    task.is_deleted = True
    results = await list_test_results(db, task_id)
    for r in results:
        r.is_deleted = True
    await db.flush()
    stmt = select(QualityTestTask).where(QualityTestTask.id == task_id)
    return (await db.execute(stmt)).scalar_one_or_none()


# ─── 任务结果行 ───


async def create_test_results(
    db: AsyncSession, task_id: uuid.UUID, items: list[dict[str, Any]]
) -> list[QualityTestResult]:
    """批量创建结果行（快照或追加）。INSERT 后 flush 返回。"""
    rows = [QualityTestResult(task_id=task_id, **data) for data in items]
    db.add_all(rows)
    await db.flush()
    return rows


async def list_test_results(db: AsyncSession, task_id: uuid.UUID) -> list[QualityTestResult]:
    """任务全部未删除结果行，按 seq、created_at 排序。"""
    stmt = select(QualityTestResult).where(
        QualityTestResult.task_id == task_id,
        QualityTestResult.is_deleted == False,  # noqa: E712
    ).order_by(QualityTestResult.seq, QualityTestResult.created_at)
    return list((await db.execute(stmt)).scalars())


async def list_task_standard_document_ids(
    db: AsyncSession, task_id: uuid.UUID
) -> list[uuid.UUID]:
    """任务结果行关联的标准文件 ID（结果行 standard_item_id → 标准行 document_id 去重；
    含任务主文档兜底，供逐份 COA 生成确定归属）。"""
    rows = await list_test_results(db, task_id)
    item_ids = {r.standard_item_id for r in rows if r.standard_item_id}
    doc_ids: list[uuid.UUID] = []
    if item_ids:
        stmt = select(QualityStandardItem.document_id).where(
            QualityStandardItem.id.in_(item_ids),
            QualityStandardItem.is_deleted == False,  # noqa: E712
        ).distinct()
        doc_ids = list((await db.execute(stmt)).scalars())
    task = await get_test_task(db, task_id)
    if task and task.standard_document_id and task.standard_document_id not in doc_ids:
        doc_ids.append(task.standard_document_id)
    return doc_ids


async def get_standard_item_doc_map(
    db: AsyncSession, item_ids: set[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """标准项目行 ID → 所属标准文档 ID 映射（逐份 COA 行归属）。"""
    if not item_ids:
        return {}
    stmt = select(QualityStandardItem.id, QualityStandardItem.document_id).where(
        QualityStandardItem.id.in_(item_ids),
        QualityStandardItem.is_deleted == False,  # noqa: E712
    )
    return {item_id: doc_id for item_id, doc_id in (await db.execute(stmt)).all()}


async def update_test_results_fill(
    db: AsyncSession, updates: list[dict[str, Any]]
) -> list[QualityTestResult]:
    """批量更新填报。每项 dict 含 result_id/result_text/result_value/is_pass/filled_by/filled_at，
    可选 source/inspection_record_id（P1 解析映射时传入）。

    未找到的 result_id 跳过；返回 UPDATE 后 re-fetch 的行列表（条数可能小于入参）。
    """
    ids = [u["result_id"] for u in updates]
    stmt = select(QualityTestResult).where(
        QualityTestResult.id.in_(ids),
        QualityTestResult.is_deleted == False,  # noqa: E712
    )
    rows = {r.id: r for r in (await db.execute(stmt)).scalars()}
    for u in updates:
        row = rows.get(u["result_id"])
        if row is None:
            continue
        row.result_text = u["result_text"]
        row.result_value = u["result_value"]
        row.is_pass = u["is_pass"]
        if u.get("source") is not None:
            row.source = u["source"]
        if u.get("inspection_record_id") is not None:
            row.inspection_record_id = u["inspection_record_id"]
        row.filled_by = u["filled_by"]
        row.filled_at = u["filled_at"]
    await db.flush()
    stmt = select(QualityTestResult).where(QualityTestResult.id.in_(ids))
    return list((await db.execute(stmt)).scalars())


async def delete_test_result(
    db: AsyncSession, result_id: uuid.UUID
) -> QualityTestResult | None:
    """软删除单行结果。"""
    stmt = select(QualityTestResult).where(
        QualityTestResult.id == result_id,
        QualityTestResult.is_deleted == False,  # noqa: E712
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        return None
    row.is_deleted = True
    await db.flush()
    stmt = select(QualityTestResult).where(QualityTestResult.id == result_id)
    return (await db.execute(stmt)).scalar_one_or_none()
