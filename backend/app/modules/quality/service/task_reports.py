"""Quality 业务逻辑编排。"""

import logging
import uuid
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.time import APP_TZ, today
from app.modules.quality.models import (
    QualityStandardDocument,
    QualityTestResult,
    QualityTestTask,
)
from app.modules.quality.repository import (
    count_report_records_since,
    get_standard_document,
    get_standard_item_doc_map,
    get_test_task,
    list_coa_bindings_by_docs,
    list_task_standard_document_ids,
    list_test_results,
    list_test_results_for_tasks,
    list_test_tasks,
    list_test_tasks_by_report_date,
)
from app.modules.quality.schemas import (
    TestTaskDetail,
    TestTaskListItem,
)
from app.modules.quality.service.task_core import _TaskCore

logger = logging.getLogger(__name__)


class _TaskReports(_TaskCore):
    """任务查询与报表：COA 拆分/看板/汇总矩阵/趋势/SOP 汇总。"""
    @staticmethod
    async def build_task_report_splits(
        db: AsyncSession, task_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """任务按标准文件逐份拆分的 COA 生成数据（一个批号多份标准 → 逐份报告单）。

        每份：{doc, template, rows, fill_data, product_name, batch_number}。
        行归属：标准快照行 → 其标准文件；无归属行（液相解析追加）→ 任务主文档。
        模板按该标准文件的 COA 绑定取，兜底文档 template_path。
        """
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        if task.status != "completed":
            raise AppException(status_code=400, detail="任务未完成，无法生成 COA")
        results = await list_test_results(db, task_id)
        if any(r.is_pass is None for r in results):
            raise AppException(status_code=400, detail="存在未判定项目，无法生成 COA")

        doc_ids = await list_task_standard_document_ids(db, task_id)
        docs: dict[uuid.UUID, QualityStandardDocument] = {}
        for doc_id in doc_ids:
            d = await get_standard_document(db, doc_id)
            if d:
                docs[d.id] = d
        if not docs:
            raise AppException(status_code=400, detail="任务无标准文件归属，无法生成 COA")

        item_ids = {r.standard_item_id for r in results if r.standard_item_id}
        item_doc = await get_standard_item_doc_map(db, item_ids)
        main_id = task.standard_document_id if task.standard_document_id in docs else None
        rows_by_doc: dict[uuid.UUID, list[QualityTestResult]] = {did: [] for did in docs}
        for r in results:
            did = item_doc.get(r.standard_item_id) if r.standard_item_id else None
            if did not in docs:
                did = main_id
            if did is None:
                raise AppException(
                    status_code=400,
                    detail=f"结果行「{r.item_name}」无法归属任何标准文件，无法生成 COA",
                )
            rows_by_doc[did].append(r)

        # 模板按标准文件解析：COA 绑定（该文档）→ 文档 template_path 兜底
        bindings = await list_coa_bindings_by_docs(db, list(docs.keys()))
        # 流水号按北京时间计日：当天已生成的报告数作为序号起点
        # 空行标准文件不生成 COA：此前空 rows 时 all([])==True 会产出「全合格」空报告单
        docs_with_rows = [d for d in sorted(docs.values(), key=lambda d: d.file_no)
                          if rows_by_doc.get(d.id)]
        if not docs_with_rows:
            raise AppException(status_code=400, detail="任务所有标准文件均无结果行，无法生成 COA")
        skipped = [d.file_no for d in docs.values() if not rows_by_doc.get(d.id)]
        today_start = datetime.combine(today(), time.min, tzinfo=APP_TZ)
        base_seq = await count_report_records_since(db, today_start)
        splits: list[dict[str, Any]] = []
        for i, d in enumerate(docs_with_rows):
            template = next(
                (b.template_path for b in bindings if b.standard_document_id == d.id), None
            ) or d.template_path or ""
            if not template:
                raise AppException(
                    status_code=400,
                    detail=f"标准文件 {d.file_no} 未绑定 COA 模板，无法逐份生成",
                )
            serial_no = f"{today():%y%m%d}{base_seq + i + 1:02d}"
            splits.append({
                "doc": d,
                "template": template,
                "rows": rows_by_doc[d.id],
                "fill_data": _TaskCore._build_report_data(
                    task, d, rows_by_doc[d.id], serial_no
                ),
                "product_name": task.product_name,
                "batch_number": task.batch_number,
                "skipped_file_nos": skipped,
            })
        return splits

    # ── 查询 ──

    @staticmethod
    async def build_dashboard(db: AsyncSession) -> dict[str, Any]:
        """质量总览看板：今日出报 / 待复核 / 在途 / 最近完成 / 标准文件到期提醒。"""
        today_str = today().isoformat()
        today_tasks = await list_test_tasks_by_report_date(db, today_str)
        review_items, _ = await list_test_tasks(db, status="pending_review", page=1, page_size=200)
        inprog_items, _ = await list_test_tasks(db, status="in_progress", page=1, page_size=200)
        completed_items, _ = await list_test_tasks(db, status="completed", page=1, page_size=5)

        # 一次批量取全部结果行，按 task_id 分组（此前每任务一次查询，看板 400+ SQL）
        all_tasks = today_tasks + review_items + completed_items
        rows_by_task = await list_test_results_for_tasks(db, [t.id for t in all_tasks])

        def _row(t: QualityTestTask) -> dict[str, Any]:
            rows = rows_by_task.get(t.id, [])
            return {
                "task_id": str(t.id),
                "product_name": t.product_name,
                "batch_number": t.batch_number,
                "status": t.status,
                "filled": sum(1 for r in rows if r.is_pass is not None),
                "total": len(rows),
                "report_date": t.report_date,
            }

        tomorrow_str = (today() + timedelta(days=1)).isoformat()
        tomorrow_tasks = await list_test_tasks_by_report_date(db, tomorrow_str)

        return {
            "today": [_row(t) for t in today_tasks],
            "pending_review": [_row(t) for t in review_items],
            "pending_review_count": len(review_items),
            "in_progress_count": len(inprog_items),
            "tomorrow_count": len([t for t in tomorrow_tasks if t.status != "void"]),
            "recent_completed": [_row(t) for t in completed_items],
        }

    @staticmethod
    async def build_summary_matrix(
        db: AsyncSession,
        product_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        include_in_progress: bool = False,
    ) -> dict[str, Any]:
        """QC 汇总表矩阵：行=批次，列=全部检验项目横向列出（含 SOP 分组信息）。

        单元格为数值结果（带单位与判定）；未判定/未覆盖项目为空。
        include_in_progress=True 时包含填报中的批次（已填显示、未填留空）。
        """
        from datetime import datetime as _dt

        statuses = ["completed", "pending_review"] + (["in_progress"] if include_in_progress else [])
        stmt = select(QualityTestTask).where(
            QualityTestTask.is_deleted == False,  # noqa: E712
            QualityTestTask.status.in_(statuses),
        )
        if product_name:
            stmt = stmt.where(QualityTestTask.product_name == product_name)
        if date_from:
            stmt = stmt.where(QualityTestTask.created_at >= _dt.fromisoformat(date_from))
        if date_to:
            stmt = stmt.where(QualityTestTask.created_at <= _dt.fromisoformat(date_to))
        stmt = stmt.order_by(QualityTestTask.production_date.asc().nulls_last(), QualityTestTask.batch_number)
        tasks = list((await db.execute(stmt)).scalars())

        columns: list[dict[str, str | None]] = []
        seen_cols: set[str] = set()
        rows: list[dict[str, Any]] = []
        for t in tasks:
            results = await list_test_results(db, t.id)
            cells: dict[str, dict[str, Any]] = {}
            all_pass = all(r.is_pass for r in results if r.is_pass is not None)
            for r in results:
                if r.is_pass is None:
                    continue
                key = r.item_name
                if key not in seen_cols:
                    seen_cols.add(key)
                    columns.append({"name": key, "sop_no": r.sop_no or None})
                value: Any = r.result_value if r.result_value is not None else (r.result_text or "")
                cells[key] = {
                    "value": value,
                    "is_pass": r.is_pass,
                    "unit": _TaskCore._unit_of(r.standard_text),
                }
            rows.append({
                "task_id": str(t.id),
                "product_name": t.product_name,
                "batch_number": t.batch_number,
                "production_date": t.production_date,
                "report_date": t.report_date,
                "status": t.status,
                "all_pass": all_pass,
                "cells": cells,
            })
        return {"columns": columns, "rows": rows}

    @staticmethod
    async def build_item_trend(
        db: AsyncSession,
        item_name: str,
        product_name: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """项目跨批次趋势：该检验项目最近 N 批的数值序列（时间升序）。"""
        stmt = (
            select(QualityTestResult, QualityTestTask)
            .join(QualityTestTask, QualityTestResult.task_id == QualityTestTask.id)
            .where(
                QualityTestResult.item_name == item_name,
                QualityTestResult.is_pass.isnot(None),
                QualityTestResult.is_deleted == False,  # noqa: E712
                QualityTestTask.is_deleted == False,  # noqa: E712
                QualityTestTask.status.in_(["completed", "pending_review"]),
            )
        )
        if product_name:
            stmt = stmt.where(QualityTestTask.product_name == product_name)
        stmt = stmt.order_by(
            QualityTestTask.production_date.desc().nulls_last(),
            QualityTestTask.created_at.desc(),
        ).limit(limit)
        pairs = list((await db.execute(stmt)).all())
        if not pairs:
            return {"item_name": item_name, "unit": "", "points": []}
        pairs.reverse()  # 时间升序展示

        first = pairs[-1][0]  # 最近一条作为限度参考（各批限度快照一致）
        return {
            "item_name": item_name,
            "unit": _TaskCore._unit_of(first.standard_text),
            "standard_text": first.standard_text,
            "operator": first.operator,
            "limit_min": first.limit_min,
            "limit_max": first.limit_max,
            "points": [
                {
                    "task_id": str(t.id),
                    "batch_number": t.batch_number,
                    "production_date": t.production_date,
                    "value": r.result_value if r.result_value is not None else None,
                    "text": r.result_text if r.result_value is None else None,
                    "is_pass": r.is_pass,
                    "status": t.status,
                }
                for r, t in pairs
                if r.result_value is not None  # 数值型项目才能画趋势
            ],
        }

    @staticmethod
    async def get_task_detail(db: AsyncSession, task_id: uuid.UUID) -> TestTaskDetail | None:
        task = await get_test_task(db, task_id)
        if not task:
            return None
        return _TaskCore._to_detail(task, await list_test_results(db, task_id))

    @staticmethod
    async def list_tasks(
        db: AsyncSession,
        product_name: str | None,
        status: str | None,
        page: int,
        page_size: int,
        report_date: str | None = None,
    ) -> tuple[list[TestTaskListItem], int]:
        items, total = await list_test_tasks(
            db, product_name, status, report_date=report_date, page=page, page_size=page_size,
        )
        out = []
        for t in items:
            rows = await list_test_results(db, t.id)
            out.append(TestTaskListItem(
                id=t.id,
                product_name=t.product_name,
                batch_number=t.batch_number,
                production_date=t.production_date,
                expiry_date=t.expiry_date,
                specification=t.specification,
                form_id=t.form_id,
                report_date=t.report_date,
                status=t.status,
                created_at=t.created_at,
                results_total=len(rows),
                results_filled=sum(1 for r in rows if r.is_pass is not None),
            ))
        return out, total

    # ── 按 SOP 汇总（以 SOP 为索引串联各板块）──

    @staticmethod
    async def summary_by_sop(
        db: AsyncSession, product_name: str | None = None
    ) -> dict[str, Any]:
        """按 (sop_no, item_name) 分组聚合各批次的一手判定结果。"""
        items, _ = await list_test_tasks(db, product_name=product_name, page=1, page_size=1000)
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for t in items:
            rows = await list_test_results(db, t.id)
            for r in rows:
                if r.is_pass is None:
                    continue
                key = (r.sop_no or "", r.item_name)
                if key not in groups:
                    groups[key] = {
                        "sop_no": r.sop_no,
                        "item_name": r.item_name,
                        "category": r.category,
                        "standard_text": r.standard_text,
                        "operator": r.operator,
                        "limit_min": r.limit_min,
                        "limit_max": r.limit_max,
                        "method_source": r.method_source,
                        "batches": [],
                    }
                groups[key]["batches"].append({
                    "task_id": str(t.id),
                    "batch_number": t.batch_number,
                    "production_date": t.production_date,
                    "expiry_date": t.expiry_date,
                    "result_value": r.result_value,
                    "result_text": r.result_text,
                    "is_pass": r.is_pass,
                    "source": r.source,
                    "filled_at": r.filled_at.isoformat() if r.filled_at else None,
                })
        out = list(groups.values())
        out.sort(key=lambda g: (g["sop_no"] or "", g["item_name"]))
        for g in out:
            g["batches"].sort(
                key=lambda b: (b["production_date"] or "", b["batch_number"]), reverse=True
            )
        return {"items": out, "total_items": len(out)}

    # ── 组装 ──
