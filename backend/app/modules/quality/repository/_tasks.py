"""Quality 模块数据读写。只负责查询与持久化，不做业务判断。"""

import re
import uuid
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.models import (
    QualityStandardItem,
    QualityTaskAssignment,
    QualityTaskAttachment,
    QualityTaskReview,
    QualityTestResult,
    QualityTestTask,
)

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
    standard_document_ids: list[str] | None = None,
    culture_days: int | None = None,
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
        standard_document_ids=standard_document_ids,
        culture_days=culture_days,
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


async def list_test_tasks_by_batch_fuzzy(
    db: AsyncSession, fragment: str, limit: int = 10
) -> list[QualityTestTask]:
    """批号片段模糊查询（机器人候选批号提示）。"""
    stmt = select(QualityTestTask).where(
        QualityTestTask.batch_number.ilike(f"%{fragment}%"),
        QualityTestTask.is_deleted == False,  # noqa: E712
    ).order_by(QualityTestTask.created_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars())


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
    """按产品+批号查未删除任务（建任务重复检查；产品名忽略空白差异）。

    取最近创建的一条（历史脏数据可能存在多行，scalar_one_or_none 会 500）。
    """
    norm = re.sub(r"\s+", "", product_name)
    stmt = (
        select(QualityTestTask)
        .where(
            func.regexp_replace(QualityTestTask.product_name, r"\s", "", "g") == norm,
            QualityTestTask.batch_number == batch_number,
            QualityTestTask.is_deleted == False,  # noqa: E712
            QualityTestTask.status != "void",  # 作废任务不占批号，允许重建
        )
        .order_by(QualityTestTask.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def list_test_tasks(
    db: AsyncSession,
    product_name: str | None = None,
    status: str | None = None,
    report_date: str | None = None,
    file_no: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[QualityTestTask], int]:
    """分页查询任务列表；file_no 按标准文件号（SOP.02.xxx）模糊过滤。"""
    stmt = select(QualityTestTask).where(QualityTestTask.is_deleted == False)  # noqa: E712
    if product_name:
        stmt = stmt.where(QualityTestTask.product_name.ilike(f"%{product_name}%"))
    if status:
        stmt = stmt.where(QualityTestTask.status == status)
    if report_date:
        stmt = stmt.where(QualityTestTask.report_date == report_date)
    if file_no:
        from app.modules.quality.models import QualityStandardDocument

        docs = (
            await db.execute(
                select(QualityStandardDocument).where(
                    QualityStandardDocument.file_no.ilike(f"%{file_no}%"),
                    QualityStandardDocument.is_deleted == False,  # noqa: E712
                )
            )
        ).scalars().all()
        if not docs:
            stmt = stmt.where(text("false"))
        else:
            conds: list[Any] = [QualityTestTask.standard_document_id.in_([d.id for d in docs])]
            for d in docs:
                conds.append(QualityTestTask.standard_document_ids.contains([str(d.id)]))
            stmt = stmt.where(or_(*conds))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(
        QualityTestTask.report_date.asc().nulls_last(),
        QualityTestTask.created_at.desc(),
    ).offset((page - 1) * page_size).limit(page_size)
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


async def list_test_results_for_tasks(
    db: AsyncSession, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[QualityTestResult]]:
    """批量取多个任务的结果行（一次查询，按 task_id 分组；看板等聚合场景避免 N+1）。"""
    if not task_ids:
        return {}
    stmt = select(QualityTestResult).where(
        QualityTestResult.task_id.in_(task_ids),
        QualityTestResult.is_deleted == False,  # noqa: E712
    ).order_by(QualityTestResult.seq, QualityTestResult.created_at)
    grouped: dict[uuid.UUID, list[QualityTestResult]] = {}
    for r in (await db.execute(stmt)).scalars():
        grouped.setdefault(r.task_id, []).append(r)
    return grouped


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


async def create_task_attachment(
    db: AsyncSession, data: dict[str, Any]
) -> QualityTaskAttachment:
    """创建任务附件记录。INSERT 后 flush 返回。"""
    att = QualityTaskAttachment(**data)
    db.add(att)
    await db.flush()
    return att


async def list_task_attachments(
    db: AsyncSession, task_id: uuid.UUID
) -> list[QualityTaskAttachment]:
    """任务全部未删除附件，按时间倒序。"""
    stmt = select(QualityTaskAttachment).where(
        QualityTaskAttachment.task_id == task_id,
        QualityTaskAttachment.is_deleted == False,  # noqa: E712
    ).order_by(QualityTaskAttachment.created_at.desc())
    return list((await db.execute(stmt)).scalars())


async def get_task_attachment(
    db: AsyncSession, attachment_id: uuid.UUID
) -> QualityTaskAttachment | None:
    """按 ID 查附件（过滤软删）。"""
    stmt = select(QualityTaskAttachment).where(
        QualityTaskAttachment.id == attachment_id,
        QualityTaskAttachment.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def delete_task_attachment(
    db: AsyncSession, attachment_id: uuid.UUID
) -> QualityTaskAttachment | None:
    """软删除附件并返回其对象键（供清理存储）。"""
    att = await get_task_attachment(db, attachment_id)
    if not att:
        return None
    att.is_deleted = True
    await db.flush()
    return att


async def create_task_review(
    db: AsyncSession, task_id: uuid.UUID, reviewer_id: uuid.UUID, comment: str | None
) -> QualityTaskReview:
    """记录一次复核通过。INSERT 后 flush 返回。"""
    review = QualityTaskReview(task_id=task_id, reviewer_id=reviewer_id, comment=comment)
    db.add(review)
    await db.flush()
    return review


async def list_task_reviews(db: AsyncSession, task_id: uuid.UUID) -> list[QualityTaskReview]:
    """任务全部未删除复核记录。"""
    stmt = select(QualityTaskReview).where(
        QualityTaskReview.task_id == task_id,
        QualityTaskReview.is_deleted == False,  # noqa: E712
    ).order_by(QualityTaskReview.created_at)
    return list((await db.execute(stmt)).scalars())


async def soft_delete_task_reviews(db: AsyncSession, task_id: uuid.UUID) -> None:
    """软删任务全部复核记录（重新进入待复核时清空上一轮）。"""
    reviews = await list_task_reviews(db, task_id)
    for r in reviews:
        r.is_deleted = True
    if reviews:
        await db.flush()


async def get_standard_item_doc_map(
    db: AsyncSession, item_ids: set[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """标准项目行 ID → 所属标准文档 ID 映射（逐份 COA 行归属）。"""
    if not item_ids:
        return {}
    # 不过滤软删：历史任务快照引用的行被覆盖导入删除后，归属映射必须
    # 仍可解析（否则逐份 COA 行归属静默漂移）
    stmt = select(QualityStandardItem.id, QualityStandardItem.document_id).where(
        QualityStandardItem.id.in_(item_ids),
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


async def list_task_reviews_with_names(db: AsyncSession, task_id: uuid.UUID) -> list[dict[str, Any]]:
    """任务复核记录（含复核人姓名，联查 identity.users）。"""
    from app.platform.identity.models import User as IdentityUser

    stmt = (
        select(QualityTaskReview, IdentityUser.name)
        .join(IdentityUser, IdentityUser.id == QualityTaskReview.reviewer_id, isouter=True)
        .where(
            QualityTaskReview.task_id == task_id,
            QualityTaskReview.is_deleted == False,  # noqa: E712
        )
        .order_by(QualityTaskReview.created_at)
    )
    out: list[dict[str, Any]] = []
    for r, reviewer_name in (await db.execute(stmt)).all():
        out.append({
            "reviewer_id": str(r.reviewer_id),
            "reviewer_name": reviewer_name,
            "comment": r.comment,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return out


# ─── 任务 SOP 分工 ───


async def list_task_assignments(db: AsyncSession, task_id: uuid.UUID) -> list[QualityTaskAssignment]:
    stmt = select(QualityTaskAssignment).where(
        QualityTaskAssignment.task_id == task_id,
        QualityTaskAssignment.is_deleted == False,  # noqa: E712
    ).order_by(QualityTaskAssignment.created_at)
    return list((await db.execute(stmt)).scalars().all())


async def list_task_assignments_with_names(
    db: AsyncSession, task_id: uuid.UUID
) -> list[dict[str, Any]]:
    """任务 SOP 分工（含负责人姓名与项目行明细/未填数）。"""
    from app.platform.identity.models import User as IdentityUser

    rows = await list_test_results(db, task_id)
    assignments = await list_task_assignments(db, task_id)
    user_ids = {a.assignee_id for a in assignments}
    users: dict[uuid.UUID, str] = {}
    if user_ids:
        stmt = select(IdentityUser).where(IdentityUser.id.in_(user_ids))
        for u in (await db.execute(stmt)).scalars():
            users[u.id] = u.name
    out: list[dict[str, Any]] = []
    for a in assignments:
        items = [r for r in rows if (r.sop_no or "").strip().upper() == (a.sop_no or "").strip().upper()]
        out.append({
            "sop_no": a.sop_no,
            "assignee_id": a.assignee_id,
            "assignee_name": users.get(a.assignee_id),
            "items": [r.item_name for r in items],
            "filled": sum(1 for r in items if r.is_pass is not None),
            "total": len(items),
            "remark": a.remark,
        })
    return out


async def replace_task_assignments(
    db: AsyncSession, task_id: uuid.UUID, rows: list[dict[str, Any]]
) -> None:
    """整组替换任务分工：软删旧分配，插入新分配（重复 SOP 覆盖）。"""
    for old in await list_task_assignments(db, task_id):
        old.is_deleted = True
    for row in rows:
        db.add(QualityTaskAssignment(**row))
    await db.flush()


async def list_board_tasks(
    db: AsyncSession, statuses: list[str] | None = None
) -> list[dict[str, Any]]:
    """任务看板数据：任务 + 分工明细（按任务聚合）。"""
    from app.modules.quality.repository import list_test_tasks  # 防循环导入

    items, _ = await list_test_tasks(db, product_name=None, status=None, page=1, page_size=500)
    if statuses:
        items = [t for t in items if t.status in statuses]
    out: list[dict[str, Any]] = []
    for t in items:
        assignments = await list_task_assignments_with_names(db, t.id)
        results = await list_test_results(db, t.id)
        out.append({
            "task_id": t.id,
            "product_name": t.product_name,
            "batch_number": t.batch_number,
            "status": t.status,
            "report_date": t.report_date,
            "filled": sum(1 for r in results if r.is_pass is not None),
            "total": len(results),
            "assignments": assignments,
            "unassigned_sops": sorted({
                (r.sop_no or "").strip()
                for r in results
                if (r.sop_no or "").strip()
                and (r.sop_no or "").strip().upper()
                not in {(a["sop_no"] or "").strip().upper() for a in assignments}
            }),
        })
    return out
