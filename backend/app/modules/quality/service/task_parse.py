"""Quality 业务逻辑编排。"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.quality import lc_template_parser
from app.modules.quality.models import (
    QualityTestTask,
)
from app.modules.quality.repository import (
    create_inspection_record,
    create_test_results,
    get_inspection_by_batch,
    get_lc_template_by_table_no,
    get_standard_document_by_file_no,
    get_test_task,
    get_test_task_by_batch,
    list_standard_items,
    list_test_results,
    update_test_results_fill,
)
from app.modules.quality.schemas import (
    LcReportOut,
    TestTaskDetail,
)
from app.modules.quality.service.lc_service import lc_report_service
from app.modules.quality.service.task_core import _TaskCore
from app.modules.quality.service.task_lifecycle import _TaskLifecycle

logger = logging.getLogger(__name__)


class _TaskParse(_TaskCore):
    """液相解析填入任务：候选映射/通用模板解析/自动关联。"""
    @staticmethod
    async def fill_task_from_report(
        db: AsyncSession,
        task: QualityTestTask,
        report: LcReportOut,
        record_id: uuid.UUID,
        filled_by: uuid.UUID | None = None,
    ) -> tuple[list[str], list[str]]:
        """把液相解析结果按项目名映射填入任务结果行（以 SOP 匹配键定位，判定按任务行标准快照）。

        返回 (filled_names, unmatched_names)。仅匹配数值型（auto）行。
        """
        # 汇总待映射项：(名称, 百分比值)——解析结果为小数（0.956=95.6%），标准库限度为百分数
        candidates: list[tuple[str, float]] = []
        if report.vancomycin_b:
            v = report.vancomycin_b
            candidates.append(("万古霉素B", (v.rounded_first or v.first_percent) * 100))
        if report.total_impurities:
            t = report.total_impurities
            candidates.append(("总杂质", (t.rounded_first or t.first_percent) * 100))
        for imp in report.impurity_results:
            candidates.append((imp.name, (imp.second_percent or imp.first_percent) * 100))
        return await _TaskParse._fill_candidates(db, task, candidates, record_id, filled_by=filled_by)

    @staticmethod
    async def _fill_candidates(
        db: AsyncSession,
        task: QualityTestTask,
        candidates: list[tuple[str, float]],
        record_id: uuid.UUID,
        sop_no: str | None = None,
        doc_item_ids: set[uuid.UUID] | None = None,
        filled_by: uuid.UUID | None = None,
    ) -> tuple[list[str], list[str]]:
        """候选结果按项目名匹配填入任务行（SOP 匹配键；判定以任务行标准快照为准）。

        sop_no 为表号↔检测 SOP 映射值；doc_item_ids 为映射标准文档的项目行集合
        （表号 → 标准文档 file_no 时提供），匹配优先限定在对应标准行内。
        """
        rows = await list_test_results(db, task.id)
        now = datetime.now(UTC)
        updates: list[dict[str, Any]] = []
        filled_names: list[str] = []
        unmatched: list[str] = []
        for name, value in candidates:
            row = _TaskParse._match_task_row(rows, name, sop_no, doc_item_ids)
            if row is None or row.judge_mode != "auto":
                unmatched.append(name)
                continue
            verdict = _TaskParse._judge_value(row.operator, row.limit_min, row.limit_max, value)
            if verdict is None:
                # 标准限度结构不足，保留原值不覆盖（提示人工判定）
                unmatched.append(name)
                continue
            updates.append({
                "result_id": row.id,
                "result_text": str(value),
                "result_value": value,
                "is_pass": verdict,
                "source": "parse",
                "inspection_record_id": record_id,
                "filled_by": filled_by,
                "filled_at": now,
            })
            filled_names.append(row.item_name)
        if updates:
            await update_test_results_fill(db, updates)
        # 全部判定完成后自动进入待复核
        await _TaskLifecycle.auto_advance_pending_review(db, task.id)
        return filled_names, unmatched

    @staticmethod
    async def parse_lc_into_task(
        db: AsyncSession,
        task_id: uuid.UUID,
        file_bytes: bytes,
        filename: str,
        filled_by: uuid.UUID | None = None,
    ) -> tuple[TestTaskDetail, list[str], list[str]]:
        """上传液相计算表：解析并持久化检验记录，按项目名映射填入任务结果行。"""
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        if task.status != "in_progress":
            raise AppException(status_code=400, detail=f"任务状态为 {task.status}，不可解析填入")
        try:
            uploaded = await lc_report_service.parse_and_validate(file_bytes, filename, db=db)
        except ValueError as e:
            raise AppException(status_code=422, detail=f"无法解析：{e}") from e
        if not uploaded.record_id:
            raise AppException(status_code=500, detail="解析成功但检验记录未持久化")
        filled, unmatched = await _TaskParse.fill_task_from_report(
            db, task, uploaded.report, uploaded.record_id, filled_by=filled_by
        )
        detail = _TaskParse._to_detail(task, await list_test_results(db, task_id))
        return detail, filled, unmatched

    # ── 模板配置驱动的通用解析 ──

    @staticmethod
    async def parse_lc_generic(
        db: AsyncSession,
        file_bytes: bytes,
        filename: str,
        filled_by: uuid.UUID | None = None,
    ) -> dict | None:
        """通用解析：表号识别 → 模板配置取值 → 持久化检验记录 → 自动关联任务。

        无匹配模板配置返回 None（由旧解析器接管）。返回 {parse, record_id, task_link}。
        """
        get, max_row, max_col = lc_template_parser.open_sheet(file_bytes, filename)
        table_no = lc_template_parser.detect_table_no(get, max_row, max_col)
        if not table_no:
            return None
        cfg = await get_lc_template_by_table_no(db, table_no)
        if not cfg:
            return None
        parsed = lc_template_parser.parse_with_config(file_bytes, filename, cfg.config, table_no)
        # 产品名以模板配置表为准（与标准库一致，任务按此关联）
        parsed.product_name = cfg.product_name or parsed.product_name
        raw_data = {
            "generic": True,
            "table_no": table_no,
            "sop_no": cfg.sop_no,
            "product_name": parsed.product_name,
            "batch_number": parsed.batch_number,
            "form_id": parsed.form_id,
            "components": [
                {"name": c.name, "first": c.first, "second": c.second, "report_value": c.report_value}
                for c in parsed.components
            ],
        }
        existing = await get_inspection_by_batch(db, parsed.product_name, parsed.batch_number)
        if existing:
            existing.form_id = parsed.form_id or None
            existing.raw_data = raw_data
            existing.excel_filename = filename
            await db.flush()
            record_id = existing.id
            rec = existing
        else:
            record = await create_inspection_record(
                db=db,
                product_name=parsed.product_name,
                batch_number=parsed.batch_number,
                form_id=parsed.form_id or None,
                standard_type=None,
                total_peak_area_a_first=None,
                total_peak_area_a_second=None,
                main_peak_area_a_first=None,
                main_peak_area_a_second=None,
                total_impurity_area_first=None,
                total_impurity_area_second=None,
                any_unknown_impurity_first=None,
                any_unknown_impurity_second=None,
                main_peak_area_b_first=None,
                main_peak_area_b_second=None,
                all_pass=True,
                raw_data=raw_data,
                excel_filename=filename,
            )
            record_id = record.id
            rec = record
        task_link = None
        task = await get_test_task_by_batch(db, parsed.product_name, parsed.batch_number)
        if task and task.status == "in_progress":
            candidates = [
                (c.name, c.report_value)
                for c in parsed.components
                if c.report_value is not None
            ]
            # 表号↔标准文档映射：sop_no 为文档 file_no 时，解析出该文档项目行集合用于行池限定
            doc_item_ids: set[uuid.UUID] | None = None
            if cfg.sop_no:
                mapped_doc = await get_standard_document_by_file_no(db, cfg.sop_no)
                if mapped_doc:
                    doc_item_ids = {it.id for it in await list_standard_items(db, mapped_doc.id)}
            filled, unmatched = await _TaskParse._fill_candidates(
                db, task, candidates, record_id, cfg.sop_no, doc_item_ids, filled_by=filled_by
            )
            # 未匹配组分自动追加为任务行（限度取计算表自带限度列，如 RS1-7）
            appended: list[str] = []
            appended_orig: set[str] = set()
            rows = await list_test_results(db, task.id)
            existing_names = {_TaskParse._norm_name(r.item_name) for r in rows}
            next_seq = max((r.seq or 0 for r in rows), default=0) + 1
            for c in parsed.components:
                if c.report_value is None or c.limit is None or c.name in set(filled):
                    continue
                name = c.name.rstrip("％%").strip()
                norm = _TaskParse._norm_name(name)
                if norm in existing_names:
                    continue
                op = "≥" if ("万古霉素" in name or "vancomycin" in name.lower()) else "≤"
                verdict = _TaskParse._judge_value(
                    op, c.limit if op == "≥" else None, None if op == "≥" else c.limit, c.report_value
                )
                await create_test_results(db, task.id, [{
                    "standard_item_id": None,
                    "seq": next_seq,
                    "category": None,
                    "item_name": name,
                    "sop_no": None,
                    "standard_text": f"{op}{c.limit}%",
                    "operator": op,
                    "limit_min": c.limit if op == "≥" else None,
                    "limit_max": None if op == "≥" else c.limit,
                    "method_source": None,
                    "remark": None,
                    "judge_mode": "auto",
                    "source": "parse",
                    "result_text": str(c.report_value),
                    "result_value": c.report_value,
                    "is_pass": verdict,
                    "inspection_record_id": record_id,
                    "filled_at": datetime.now(UTC),
                }])
                next_seq += 1
                existing_names.add(norm)
                appended.append(name)
                appended_orig.add(c.name)
            remaining = [u for u in unmatched if u not in appended_orig]
            task_link = {
                "task_id": str(task.id),
                "filled": filled,
                "appended": appended,
                "unmatched": remaining,
            }
        # 判定结论回写 InspectionRecord.all_pass（此前恒 True，超限批次也被统计为合格）：
        # 任务行判定结果 ∪ 组分自带限度判定；两者皆无判定时不改写（保留默认 True）
        verdicts: list[bool] = []
        if task:
            for r in await list_test_results(db, task.id):
                if r.is_pass is not None:
                    verdicts.append(r.is_pass)
        for c in parsed.components:
            if c.report_value is not None and c.limit is not None:
                op = "≥" if ("万古霉素" in c.name or "vancomycin" in c.name.lower()) else "≤"
                verdicts.append(_TaskParse._judge_value(
                    op, c.limit if op == "≥" else None,
                    None if op == "≥" else c.limit, c.report_value,
                ))
        if verdicts:
            rec.all_pass = all(verdicts)
            await db.flush()
        return {"parse": parsed, "record_id": record_id, "task_link": task_link}

    # ── 追加行 ──
