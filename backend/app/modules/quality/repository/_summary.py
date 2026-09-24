"""Quality 模块数据读写。只负责查询与持久化，不做业务判断。"""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.models import (
    InspectionRecord,
    QualityTestTask,
)
from app.modules.quality.repository._tasks import list_test_results

# ─── 汇总查询 ───


async def get_product_names(db: AsyncSession) -> list[str]:
    """获取所有检验过的产品名称（检验记录与任务两源并集，去重）。"""
    rec_stmt = (
        select(InspectionRecord.product_name)
        .where(InspectionRecord.is_deleted == False)  # noqa: E712
        .distinct()
    )
    task_stmt = (
        select(QualityTestTask.product_name)
        .where(QualityTestTask.is_deleted == False)  # noqa: E712
        .distinct()
    )
    names = set((await db.execute(rec_stmt)).scalars())
    names.update((await db.execute(task_stmt)).scalars())
    return sorted(names)


async def get_summary_by_product(
    db: AsyncSession,
    product_name: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """按产品/时间段聚合汇总统计。

    批次口径：按 (产品, 批号) 去重合并两个数据源——
    ① 检验任务（completed 且全部结果已判定，判定以结果行为准，一手数据优先）；
    ② 液相检验记录（同批多次上传取最新一条的 all_pass）。
    """
    batches: dict[tuple[str, str], bool] = {}

    # ① 检验任务批次
    task_stmt = select(QualityTestTask).where(
        QualityTestTask.is_deleted == False,  # noqa: E712
        QualityTestTask.status == "completed",
    )
    if product_name:
        task_stmt = task_stmt.where(QualityTestTask.product_name == product_name)
    if date_from:
        task_stmt = task_stmt.where(QualityTestTask.created_at >= date_from)
    if date_to:
        task_stmt = task_stmt.where(QualityTestTask.created_at <= date_to)
    tasks = list((await db.execute(task_stmt)).scalars())
    for t in tasks:
        rows = await list_test_results(db, t.id)
        if not rows or any(r.is_pass is None for r in rows):
            continue  # 未完全判定的批次不计入合格率
        batches[(t.product_name, t.batch_number)] = all(r.is_pass for r in rows)

    # ② 液相检验记录批次（同批多次上传取最新一条）
    rec_stmt = select(
        InspectionRecord.product_name,
        InspectionRecord.batch_number,
        InspectionRecord.all_pass,
        InspectionRecord.created_at,
    ).where(InspectionRecord.is_deleted == False)  # noqa: E712
    if product_name:
        rec_stmt = rec_stmt.where(InspectionRecord.product_name == product_name)
    if date_from:
        rec_stmt = rec_stmt.where(InspectionRecord.created_at >= date_from)
    if date_to:
        rec_stmt = rec_stmt.where(InspectionRecord.created_at <= date_to)
    record_rows = (await db.execute(rec_stmt)).all()
    record_batches: dict[tuple[str, str], tuple[datetime, bool]] = {}
    for p, b, ap, ct in record_rows:
        key = (p, b)
        if key in batches:
            continue  # 已有任务一手数据，检验记录不覆盖
        if key not in record_batches or ct >= record_batches[key][0]:
            record_batches[key] = (ct, bool(ap))
    for key, (_ct, ap) in record_batches.items():
        batches[key] = ap

    # ③ 在途批次（填报中/待复核，不计入合格率分母，单独展示）
    prog_stmt = select(
        QualityTestTask.product_name, QualityTestTask.batch_number
    ).where(
        QualityTestTask.is_deleted == False,  # noqa: E712
        QualityTestTask.status.in_(["in_progress", "pending_review"]),
    )
    if product_name:
        prog_stmt = prog_stmt.where(QualityTestTask.product_name == product_name)
    if date_from:
        prog_stmt = prog_stmt.where(QualityTestTask.created_at >= date_from)
    if date_to:
        prog_stmt = prog_stmt.where(QualityTestTask.created_at <= date_to)
    # set[Any]：SQLAlchemy 的 Row 是 Sequence 而非 tuple 子类，无法标注为
    # set[tuple[str, str]]（运行时行为与 set[tuple[str, str]] 完全一致）
    in_progress_batches: set[Any] = set((await db.execute(prog_stmt)).all())

    total = len(batches)
    pass_count = sum(1 for v in batches.values() if v)
    fail_count = total - pass_count
    if total == 0 and not in_progress_batches:
        return {
            "total": 0, "pass_count": 0, "fail_count": 0,
            "pass_rate": 0.0, "in_progress": 0, "products": [],
        }

    # 按产品分组（完成批次 + 在途批次合并键）
    by_product: dict[str, dict[str, Any]] = {}
    all_keys = set(batches.keys()) | in_progress_batches
    for (p, _b) in all_keys:
        if p not in by_product:
            by_product[p] = {
                "product_name": p, "total": 0, "pass_count": 0, "fail_count": 0, "in_progress": 0,
            }
    for (p, _b), ok in batches.items():
        by_product[p]["total"] += 1
        by_product[p]["pass_count" if ok else "fail_count"] += 1
    for (p, _b) in in_progress_batches:
        by_product[p]["in_progress"] += 1
    products = sorted(by_product.values(), key=lambda x: -(x["total"] + x["in_progress"]))
    return {
        "total": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate": round(pass_count / total * 100, 1) if total else 0.0,
        "in_progress": len(in_progress_batches),
        "products": products,
    }
