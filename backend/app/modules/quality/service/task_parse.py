"""Quality 业务逻辑编排。"""

import logging
import re
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
    get_inspection_record,
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
        sop_pattern: str | None = None,
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
            row = _TaskParse._match_task_row(rows, name, sop_no, doc_item_ids, sop_pattern)
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
                "pending_confirm": True,
            })
            filled_names.append(row.item_name)
        if updates:
            await update_test_results_fill(db, updates)
        # 解析超限直接提醒：暂存待确认 + 飞书群通知
        fails = [u for u in updates if u.get("is_pass") is False]
        if fails:
            from app.modules.quality.feishu.client import QUALITY_FEISHU_CHAT_IDS
            from app.modules.quality.feishu.message import send_chat_text
            from app.modules.quality.service.helpers import spawn_background

            lines = "\n".join(
                f"- {u.get('result_text')} {u.get('result_value')}"
                for u in fails
            )
            text = (
                f"液相解析超限提醒：任务 {task.batch_number} 有 {len(fails)} 项超限，"
                f"已暂存待人工确认，请进任务详情核对：\n{lines}"
            )

            async def _notify_fails() -> None:
                for chat_id in QUALITY_FEISHU_CHAT_IDS:
                    try:
                        await send_chat_text(chat_id, text)
                    except Exception:  # noqa: BLE001 — 单个群失败不阻断填入
                        logger.warning("超限提醒发送失败 chat=%s", chat_id)

            spawn_background(_notify_fails())
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
        """上传液相计算表解析并填入任务：优先模板配置驱动的通用解析（值准确 + 未匹配组分自动追加），
        无表号/无配置时回落旧万古霉素解析器。"""
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        if task.status != "in_progress":
            raise AppException(status_code=400, detail=f"任务状态为 {task.status}，不可解析填入")
        # 优先通用解析（与解析页 LcUploader 同链路，保证两边行为一致）
        try:
            get, max_row, max_col = lc_template_parser.open_sheet(file_bytes, filename)
        except ValueError:
            get = None
        table_no = lc_template_parser.detect_table_no(get, max_row, max_col) if get else None
        if table_no:
            cfg = await get_lc_template_by_table_no(db, table_no)
            if cfg:
                parsed = lc_template_parser.parse_with_config(file_bytes, filename, cfg.config, table_no)
                parsed.product_name = cfg.product_name or parsed.product_name
                record_id = await _TaskParse._persist_generic_record(db, parsed, filename, cfg.sop_no)
                filled, appended, remaining = await _TaskParse._fill_generic_into_task(
                    db, task, parsed, record_id, cfg.sop_no, filled_by=filled_by,
                    any_unknown_rule=(cfg.config or {}).get("any_unknown"),
                )
                detail = _TaskParse._to_detail(task, await list_test_results(db, task_id))
                return detail, filled + appended, remaining
            raise AppException(
                status_code=422,
                detail=f"表号 {table_no} 未配置计算规则，暂不支持解析（可联系管理员配置，或使用在线计算表）",
            )
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

    @staticmethod
    async def submit_calc_form(
        db: AsyncSession,
        task: QualityTestTask,
        table_no: str | None,
        record_date: str | None,
        values: list[tuple[str, float]],
        filled_by: uuid.UUID | None = None,
        inputs: dict[str, Any] | None = None,
        section: int = 0,
    ) -> tuple[list[str], list[str]]:
        """在线计算表提交：数值候选 + 表号合并规则计算 → 复用/创建检验记录留痕 → 判定填入任务。

        inputs 存在时按表号 calc 配置走色谱计算引擎（峰面积→百分比），
        否则 values 为直接填写的计算结果。返回 (filled_names, unmatched_names)。
        """
        if task.status != "in_progress":
            raise AppException(status_code=400, detail=f"任务状态为 {task.status}，不可填报计算表")
        candidates: list[tuple[str, float]] = list(values)
        computed: dict[str, Any] | None = None
        if inputs is not None and table_no:
            from app.modules.quality import calc_engine

            cfg = await get_lc_template_by_table_no(db, table_no)
            if cfg and (cfg.config or {}).get("calc_sections"):
                sections = cfg.config["calc_sections"]
                calc_cfg = sections[section]["calc"] if section < len(sections) else None
            else:
                calc_cfg = (cfg.config or {}).get("calc") if cfg else None
            if not calc_cfg:
                raise AppException(status_code=400, detail=f"表号 {table_no} 该节未配置计算规则，请用直接填值模式")
            mode = calc_cfg.get("mode")
            if mode == "external_std":
                computed = calc_engine.compute_external_std(calc_cfg, inputs)
            elif mode == "external_std_content":
                computed = calc_engine.compute_external_std_content(calc_cfg, inputs)
            elif mode == "external_std_content_multi":
                computed = calc_engine.compute_content_multi(calc_cfg, inputs)
            elif mode == "impurity_vs_std":
                computed = calc_engine.compute_impurity_vs_std(calc_cfg, inputs)
            elif mode == "impurity_std_ratio":
                computed = calc_engine.compute_impurity_std_ratio(calc_cfg, inputs)
            elif mode == "std_curve":
                computed = calc_engine.compute_std_curve(calc_cfg, inputs)
            elif mode == "group_rrf":
                computed = calc_engine.compute_group_rrf(calc_cfg, inputs)
            elif mode == "impurity_rrf_std":
                computed = calc_engine.compute_impurity_rrf_std(calc_cfg, inputs)
            else:
                computed = calc_engine.compute_normalization(calc_cfg, inputs)
            for item in computed["items"]:
                if item.get("value") is not None:
                    candidates.append((item["std_name"], float(item["value"])))
        # 表号合并规则：如 杂质B(B1+B2) = 杂质B1 + 杂质B2（配置 merge op=sum）
        if table_no:
            cfg = await get_lc_template_by_table_no(db, table_no)
            if cfg and isinstance(cfg.config, dict):
                value_map: dict[str, float] = {}
                for name, v in candidates:
                    value_map[_TaskParse._norm_name(name)] = v
                for rule in cfg.config.get("merge", []) or []:
                    if rule.get("op") == "sum":
                        parts = [
                            value_map.get(_TaskParse._norm_name(n))
                            for n in (rule.get("from") or [])
                        ]
                        if parts and all(v is not None for v in parts):
                            candidates.append((str(rule["into"]), sum(p for p in parts if p is not None)))
        # 检验记录：同批已有则复用（唯一索引），否则创建；raw_data 存表单快照留痕
        record = await get_inspection_by_batch(db, task.product_name, task.batch_number)
        if record is None:
            record = await create_inspection_record(
                db, task.product_name, task.batch_number, table_no, None,
                None, None, None, None, None, None, None, None, None, None,
                all_pass=True,
                raw_data={
                    "source": "calc_form", "table_no": table_no, "record_date": record_date,
                    "inputs": inputs,
                    "computed": computed,
                    "values": [{"item_name": n, "value": v} for n, v in candidates],
                },
                excel_filename=None,
            )
        filled, unmatched = await _TaskParse._fill_candidates(
            db, task, candidates, record.id, filled_by=filled_by
        )
        return filled, unmatched

    # ── 模板配置驱动的通用解析 ──

    @staticmethod
    async def _persist_generic_record(
        db: AsyncSession,
        parsed: "lc_template_parser.GenericLcParse",
        filename: str,
        sop_no: str | None,
    ) -> uuid.UUID:
        """通用解析结果持久化到检验记录（同批已有则更新 raw_data 留痕），返回 record_id。"""
        raw_data = {
            "generic": True,
            "table_no": parsed.form_id,
            "sop_no": sop_no,
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
            return existing.id
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
        return record.id

    @staticmethod
    async def _fill_generic_into_task(
        db: AsyncSession,
        task: QualityTestTask,
        parsed: "lc_template_parser.GenericLcParse",
        record_id: uuid.UUID,
        sop_no: str | None,
        filled_by: uuid.UUID | None = None,
        any_unknown_rule: dict[str, Any] | None = None,
    ) -> tuple[list[str], list[str], list[str]]:
        """通用解析填入任务：按项目名匹配 + 未匹配组分自动追加（限度取计算表限度列，如 RS1-7）。

        返回 (filled_names, appended_names, remaining_unmatched)。
        """
        candidates = [
            (c.name, c.report_value)
            for c in parsed.components
            if c.report_value is not None
        ]
        if any_unknown_rule:
            candidates = _TaskParse._apply_any_unknown_rule(candidates, any_unknown_rule)
        doc_item_ids: set[uuid.UUID] | None = None
        if sop_no:
            mapped_doc = await get_standard_document_by_file_no(db, sop_no)
            if mapped_doc:
                doc_item_ids = {it.id for it in await list_standard_items(db, mapped_doc.id)}
        pattern = None
        if parsed.form_id:
            m = re.search(r"EX-[A-Z]+-(\d+)-", parsed.form_id)
            pattern = m.group(1) if m else None
        filled, unmatched = await _TaskParse._fill_candidates(
            db, task, candidates, record_id, sop_no, doc_item_ids, pattern, filled_by=filled_by,
        )
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
                "pending_confirm": True,
            }])
            next_seq += 1
            existing_names.add(norm)
            appended.append(name)
            appended_orig.add(c.name)
        remaining = [u for u in unmatched if u not in appended_orig]
        # 「未检出」组分（report_value=None）既不在 filled 也不在 unmatched——追加到 unmatched 保证可追溯
        undetected = [
            f"{c.name}（未检出）" for c in parsed.components
            if c.report_value is None and c.name
        ]
        remaining.extend(undetected)
        return filled, appended, remaining

    @staticmethod
    async def parse_lc_generic(
        db: AsyncSession,
        file_bytes: bytes,
        filename: str,
        filled_by: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """通用解析：表号识别 → 模板配置取值 → 持久化检验记录 → 自动关联任务。

        无匹配模板配置返回 None（由旧解析器接管）。返回 {parse, record_id, task_link}。
        """
        get, max_row, max_col = lc_template_parser.open_sheet(file_bytes, filename)
        table_no = lc_template_parser.detect_table_no(get, max_row, max_col)
        if not table_no:
            logger.warning("液相计算表未识别到表号（EX-xx-xxxx-vvv），回落旧解析器")
            return None
        cfg = await get_lc_template_by_table_no(db, table_no)
        if not cfg:
            return None
        parsed = lc_template_parser.parse_with_config(file_bytes, filename, cfg.config, table_no)
        # 产品名以模板配置表为准（与标准库一致，任务按此关联）
        parsed.product_name = cfg.product_name or parsed.product_name
        record_id = await _TaskParse._persist_generic_record(db, parsed, filename, cfg.sop_no)
        rec = await get_inspection_record(db, record_id)
        task_link = None
        task = await get_test_task_by_batch(db, parsed.product_name, parsed.batch_number)
        if task and task.status == "in_progress":
            filled, appended, remaining = await _TaskParse._fill_generic_into_task(
                db, task, parsed, record_id, cfg.sop_no, filled_by=filled_by,
                any_unknown_rule=(cfg.config or {}).get("any_unknown"),
            )
            task_link = {
                "task_id": str(task.id),
                "filled": filled,
                "appended": appended,
                "unmatched": remaining,
            }
        # 判定结论回写 InspectionRecord.all_pass（此前恒 True，超限批次也被统计为合格）：
        # 任务行判定结果 ∪ 组分自带限度判定；两者皆无判定时不改写（保留默认 True）
        # 元素含 None：_judge_value 签名为 bool | None（此处 op/limit 均已判非空，
        # 实际必为 bool；标注按被调方签名放宽，与 all() 的运行时语义一致）
        verdicts: list[bool | None] = []
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
        if verdicts and rec is not None:
            rec.all_pass = all(verdicts)
            await db.flush()
        return {"parse": parsed, "record_id": record_id, "task_link": task_link}

    @staticmethod
    def _apply_any_unknown_rule(
        candidates: list[tuple[str, float]], rule: dict[str, Any],
    ) -> list[tuple[str, float]]:
        """任何未知杂质规则（仅解析路径）：除排除清单外的其余组分（含「任何未知杂质」字段自身）取最大值。

        rule = {"exclude": ["万古霉素B", "杂质A", ...]}；排除按归一化名精确或前缀匹配
        （「杂质B」前缀覆盖 杂质B1/B2/B(B1+B2)）。
        """
        exclude = {_TaskCore._norm_name(str(n)) for n in rule.get("exclude", [])}

        def excluded(norm: str) -> bool:
            return any(norm == e or norm.startswith(e) for e in exclude)

        pool = [v for name, v in candidates if not excluded(_TaskCore._norm_name(name))]
        if not pool:
            return candidates
        value = round(max(pool), 2)
        out = [(name, v) for name, v in candidates if _TaskCore._norm_name(name) != "任何未知杂质"]
        out.append(("任何未知杂质", value))
        return out

    # ── 追加行 ──
