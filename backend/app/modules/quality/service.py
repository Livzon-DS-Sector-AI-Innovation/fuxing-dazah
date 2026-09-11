"""Quality 业务逻辑编排。"""

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.quality import lc_template_parser
from app.modules.quality.excel_parser import LcReportData, parse_lc_excel
from app.modules.quality.models import (
    QualityStandardDocument,
    QualityTestResult,
    QualityTestTask,
)
from app.modules.quality.repository import (
    count_report_records_since,
    create_impurities,
    create_inspection_record,
    create_test_results,
    create_test_task,
    create_unqualified_event,
    delete_test_result,
    delete_test_task,
    get_impurities_by_record,
    get_inspection_by_batch,
    get_inspection_record,
    get_lc_template_by_table_no,
    get_standard_document,
    get_standard_document_by_file_no,
    get_standard_item_doc_map,
    get_test_task,
    get_test_task_by_batch,
    list_coa_bindings_by_docs,
    list_standard_documents_by_product,
    list_standard_items,
    list_task_standard_document_ids,
    list_test_results,
    list_test_tasks,
    update_test_results_fill,
    update_test_task,
    update_test_task_report_date,
)
from app.modules.quality.schemas import (
    CalculatedResultOut,
    ImpurityDetailOut,
    ImpurityPeakAreaOut,
    ImpurityResultOut,
    InspectionRecordDetail,
    LcReportOut,
    QualityStandardOut,
    TestResultCreate,
    TestResultOut,
    TestResultsUpdate,
    TestTaskCreate,
    TestTaskDetail,
    TestTaskListItem,
    TestTaskReportDateUpdate,
    TestTaskStatusUpdate,
    UploadLcResponse,
)

logger = logging.getLogger(__name__)


def _norm_date_str(s: str | None) -> str | None:
    """日期字符串分隔符归一化：2026.01.01 / 2026/01/01 → 2026-01-01。"""
    if not s:
        return None
    return s.strip().replace(".", "-").replace("/", "-")


@dataclass(frozen=True)
class ParserEntry:
    """解析器注册条目。"""

    name: str  # 产品名称（如"盐酸万古霉素"）
    description: str  # 简介


# 解析器注册表：后续新增产品在此注册
# 当前只有盐酸万古霉素，使用默认解析器
PARSER_REGISTRY: dict[str, ParserEntry] = {
    "盐酸万古霉素": ParserEntry(
        name="盐酸万古霉素",
        description="USP 标准（EX-HA-5246-001），支持 EP/CP 扩展",
    ),
}


class LcReportService:
    """液相报告单解析、判定与持久化服务。"""

    @staticmethod
    async def parse_and_validate(
        file_bytes: bytes,
        filename: str,
        db: AsyncSession | None = None,
    ) -> UploadLcResponse:
        """解析液相计算表，可选持久化到数据库。"""
        raw: LcReportData = parse_lc_excel(file_bytes, filename)
        report = LcReportService._build_report(raw)
        record_id: uuid.UUID | None = None

        if db:
            record_id = await LcReportService._save_inspection(db, raw, report, filename)

        return UploadLcResponse(filename=filename, report=report, record_id=record_id)

    @staticmethod
    async def get_record_detail(
        db: AsyncSession, record_id: uuid.UUID
    ) -> InspectionRecordDetail | None:
        """获取检验记录详情（含杂质明细）。"""
        record = await get_inspection_record(db, record_id)
        if not record:
            return None

        impurities = await get_impurities_by_record(db, record_id)

        # 从 raw_data 重建 LcReportOut
        report = None
        if record.raw_data:
            report = LcReportOut.model_validate(record.raw_data)

        return InspectionRecordDetail(
            id=record.id,
            product_name=record.product_name,
            batch_number=record.batch_number,
            form_id=record.form_id,
            standard_type=record.standard_type,
            all_pass=record.all_pass,

            excel_filename=record.excel_filename,
            created_at=record.created_at,
            report=report or LcReportOut(),
            impurities=[
                ImpurityDetailOut(
                    id=imp.id,
                    name=imp.name,
                    first_percent=imp.first_percent,
                    second_percent=imp.second_percent,
                    limit_value=imp.limit_value,
                    is_pass=imp.is_pass,
                )
                for imp in impurities
            ],
        )

    @staticmethod
    async def _save_inspection(
        db: AsyncSession,
        raw: LcReportData,
        report: LcReportOut,
        filename: str,
    ) -> uuid.UUID:
        """将解析结果持久化到数据库。"""
        # 检查是否已有同产品+批号的记录，有则更新
        existing = await get_inspection_by_batch(db, raw.product_name, raw.batch_number)
        if existing:
            existing.form_id = raw.form_id or None
            existing.standard_type = raw.standard_type or None
            existing.total_peak_area_a_first = raw.total_peak_area_a_first or None
            existing.total_peak_area_a_second = raw.total_peak_area_a_second or None
            existing.main_peak_area_a_first = raw.main_peak_area_a_first or None
            existing.main_peak_area_a_second = raw.main_peak_area_a_second or None
            existing.total_impurity_area_first = raw.total_impurity_area_first or None
            existing.total_impurity_area_second = raw.total_impurity_area_second or None
            existing.any_unknown_impurity_first = raw.any_unknown_impurity_first or None
            existing.any_unknown_impurity_second = raw.any_unknown_impurity_second or None
            existing.main_peak_area_b_first = raw.main_peak_area_b_first or None
            existing.main_peak_area_b_second = raw.main_peak_area_b_second or None
            existing.all_pass = report.all_pass
            existing.raw_data = report.model_dump(mode="json")
            existing.excel_filename = filename
            await db.flush()
            # 软删除旧杂质 + 写入新杂质
            old_impurities = await get_impurities_by_record(db, existing.id)
            for imp in old_impurities:
                imp.is_deleted = True
            await db.flush()
            record_id = existing.id
            # 保存新杂质明细（用已判定的 report.impurity_results，含 is_pass）
            impurity_data = []
            for imp in report.impurity_results:
                impurity_data.append({
                    "name": imp.name,
                    "first_percent": imp.first_percent,
                    "second_percent": imp.second_percent,
                    "limit": imp.limit,
                    "is_pass": imp.is_pass,
                })
            if impurity_data:
                await create_impurities(db, record_id, impurity_data)
            return record_id

        record = await create_inspection_record(
            db=db,
            product_name=raw.product_name,
            batch_number=raw.batch_number,
            form_id=raw.form_id or None,
            standard_type=raw.standard_type or None,
            total_peak_area_a_first=raw.total_peak_area_a_first or None,
            total_peak_area_a_second=raw.total_peak_area_a_second or None,
            main_peak_area_a_first=raw.main_peak_area_a_first or None,
            main_peak_area_a_second=raw.main_peak_area_a_second or None,
            total_impurity_area_first=raw.total_impurity_area_first or None,
            total_impurity_area_second=raw.total_impurity_area_second or None,
            any_unknown_impurity_first=raw.any_unknown_impurity_first or None,
            any_unknown_impurity_second=raw.any_unknown_impurity_second or None,
            main_peak_area_b_first=raw.main_peak_area_b_first or None,
            main_peak_area_b_second=raw.main_peak_area_b_second or None,
            all_pass=report.all_pass,

            raw_data=report.model_dump(mode="json"),
            excel_filename=filename,
        )

        # 保存杂质明细（用已判定的 report.impurity_results，含 is_pass）
        impurity_data = []
        for imp in report.impurity_results:
            impurity_data.append({
                "name": imp.name,
                "first_percent": imp.first_percent,
                "second_percent": imp.second_percent,
                "limit": imp.limit,
                "is_pass": imp.is_pass,
            })
        if impurity_data:
            await create_impurities(db, record.id, impurity_data)

        return record.id

    @staticmethod
    def _build_report(raw: LcReportData) -> LcReportOut:
        all_pass = True
        standards = [
            QualityStandardOut(
                name=s.name,
                limit=s.limit,
                operator=s.operator,
            )
            for s in raw.standards
        ]
        peaks = [
            ImpurityPeakAreaOut(name=p.name, first=p.first, second=p.second)
            for p in raw.impurity_peaks
        ]

        def judge(val, op, limit):
            ok = True
            if limit and limit > 0:
                ok = val >= limit if op == "≥" else val <= limit
            return ok

        vb = None
        if raw.vancomycin_b:
            v = raw.vancomycin_b
            vb_ok = judge(v.rounded_first, "≥", v.limit)
            if not vb_ok:
                all_pass = False
            vb = CalculatedResultOut(
                name=v.name,
                first_percent=v.first_percent,
                second_percent=v.second_percent,
                rounded_first=v.rounded_first,
                rounded_second=v.rounded_second,
                limit=v.limit,
                is_pass=vb_ok,
            )

        ti = None
        if raw.total_impurities:
            t = raw.total_impurities
            ti_ok = judge(t.rounded_first, "≤", t.limit)
            if not ti_ok:
                all_pass = False
            ti = CalculatedResultOut(
                name=t.name,
                first_percent=t.first_percent,
                second_percent=t.second_percent,
                rounded_first=t.rounded_first,
                rounded_second=t.rounded_second,
                limit=t.limit,
                is_pass=ti_ok,
            )

        imps = []
        for imp in raw.impurity_results:
            ok = judge(imp.second_percent or imp.first_percent, "≤", imp.limit)
            if not ok:
                all_pass = False
            imps.append(
                ImpurityResultOut(
                    name=imp.name,
                    first_percent=imp.first_percent,
                    second_percent=imp.second_percent,
                    limit=imp.limit,
                    is_pass=ok,
                )
            )

        return LcReportOut(
            product_name=raw.product_name,
            batch_number=raw.batch_number,
            form_id=raw.form_id,
            standard_type=raw.standard_type,
            total_peak_area_a_first=raw.total_peak_area_a_first,
            total_peak_area_a_second=raw.total_peak_area_a_second,
            main_peak_area_a_first=raw.main_peak_area_a_first,
            main_peak_area_a_second=raw.main_peak_area_a_second,
            total_impurity_area_first=raw.total_impurity_area_first,
            total_impurity_area_second=raw.total_impurity_area_second,
            any_unknown_impurity_first=raw.any_unknown_impurity_first,
            any_unknown_impurity_second=raw.any_unknown_impurity_second,
            main_peak_area_b_first=raw.main_peak_area_b_first,
            main_peak_area_b_second=raw.main_peak_area_b_second,
            impurity_peaks=peaks,
            vancomycin_b=vb,
            total_impurities=ti,
            impurity_results=imps,
            standards=standards,
            all_pass=all_pass,
        )

    @staticmethod
    def build_report_data(report: LcReportOut) -> dict:
        """将 LcReportOut 转为模板填充所需的字段字典。

        字段名与模板占位符对应，数值转换为显示格式（百分比等）。
        """
        data: dict = {
            "产品名称": report.product_name,
            "批号": report.batch_number,
            "标准类型": report.standard_type,
            "表号": report.form_id,
            "判定结果": "合格" if report.all_pass else "不合格",
        }

        # 万古霉素B
        if report.vancomycin_b:
            vb = report.vancomycin_b
            # 百分比显示（模板占位符通常期望百分比字符串）
            data["万古霉素B"] = f"{vb.rounded_first * 100:.1f}%"
            data["万古霉素B_判定"] = "合格" if vb.is_pass else "不合格"

        # 总杂质
        if report.total_impurities:
            ti = report.total_impurities
            data["总杂质"] = f"{ti.rounded_first * 100:.1f}%"
            data["总杂质_判定"] = "合格" if ti.is_pass else "不合格"

        # 各杂质
        for imp in report.impurity_results:
            suffix = imp.name.replace("杂质", "").strip()
            pct = (imp.second_percent or imp.first_percent) * 100
            data[f"杂质{suffix}"] = f"{pct:.3f}%"
            data[f"杂质{suffix}_判定"] = "合格" if imp.is_pass else "不合格"

        return data


lc_report_service = LcReportService()


class TestTaskService:
    """检验任务编排：建任务快照、批量填报判定、状态流转。"""

    # 默认判定规则：项目名归一化 → 默认结果文本（文字呈现项目与默认未检出项目）
    _DEFAULT_FILL_RULES = {
        "细菌内毒素": "符合规定",
        "edta": "未检出",
    }

    # ─── 判定规则 ───

    @staticmethod
    def _judge_value(
        operator: str | None,
        limit_min: float | None,
        limit_max: float | None,
        value: float,
    ) -> bool | None:
        """数值自动判定。返回 None 表示限度结构不足，需人工判定。

        ≤: value <= limit_max；<: value < limit_max
        ≥: value >= limit_min；>: value > limit_min
        范围: limit_min <= value <= limit_max（含边界）
        不引入浮点容差（P1 可加 tolerance 参数）。
        """
        if operator in ("≤", "<"):
            if limit_max is None:
                return None
            return value <= limit_max if operator == "≤" else value < limit_max
        if operator in ("≥", ">"):
            if limit_min is None:
                return None
            return value >= limit_min if operator == "≥" else value > limit_min
        if operator == "范围":
            if limit_min is None or limit_max is None:
                return None
            return limit_min <= value <= limit_max
        return None

    @staticmethod
    def _infer_judge_mode(
        operator: str | None, limit_min: float | None, limit_max: float | None
    ) -> str:
        return "auto" if operator is not None and (limit_min is not None or limit_max is not None) else "manual"

    @staticmethod
    def _calc_expiry(production_date: str | None, valid_years_text: str | None) -> str | None:
        """效期 = 生产日期 + x 年 - 1 天。valid_years_text 如「36个月」/「3年」。

        解析不出整年数（或日期非法）返回 None，由人工填写。
        """
        if not production_date or not valid_years_text:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)\s*(个月|月|年)", valid_years_text)
        if not m:
            return None
        n = float(m.group(1))
        years = n / 12 if "月" in m.group(2) else n
        if not years.is_integer():
            return None
        try:
            d = datetime.strptime(production_date, "%Y-%m-%d").date()
        except ValueError:
            return None
        y, month, day = d.year + int(years), d.month, d.day
        while True:
            try:
                expiry = date(y, month, day) - timedelta(days=1)
                break
            except ValueError:
                day -= 1  # 2/29 → 2/28
        return expiry.strftime("%Y-%m-%d")

    # ─── 建任务 ───

    @staticmethod
    def _match_docs_by_batch_code(
        docs: list[QualityStandardDocument], batch_number: str
    ) -> tuple[str | None, list[QualityStandardDocument]]:
        """批号必然含产品代号（如 HAF2608001B → HAF）：按批号开头做最长前缀匹配。

        返回 (识别出的代号, 该代号下的标准文档)；未识别返回 (None, [])。
        """
        codes = sorted(
            {(d.product_code or "").strip().upper() for d in docs if (d.product_code or "").strip()},
            key=len,
            reverse=True,
        )
        batch_upper = batch_number.strip().upper()
        for code in codes:
            if batch_upper.startswith(code):
                return code, [d for d in docs if (d.product_code or "").strip().upper() == code]
        return None, []

    @staticmethod
    async def create_task(db: AsyncSession, payload: TestTaskCreate) -> TestTaskDetail:
        existing = await get_test_task_by_batch(db, payload.product_name, payload.batch_number)
        if existing:
            raise AppException(
                status_code=409,
                detail=f"该产品+批号已存在检验任务（任务ID: {existing.id}），请直接进入该任务继续填报",
            )
        # 批号必然含产品代号：先按批号开头收敛到该代号的标准文档，再快照项目行
        product_docs = await list_standard_documents_by_product(db, payload.product_name)
        if not product_docs:
            raise AppException(
                status_code=400,
                detail=f"未找到产品「{payload.product_name}」的质量标准文档，请先在产品标准中导入",
            )
        code, docs = TestTaskService._match_docs_by_batch_code(product_docs, payload.batch_number)
        if not docs:
            known = "、".join(
                sorted({(d.product_code or "").strip() for d in product_docs if (d.product_code or "").strip()})
            ) or "未配置"
            raise AppException(
                status_code=400,
                detail=f"批号「{payload.batch_number}」开头未匹配到产品「{payload.product_name}」的产品代号"
                f"（标准库代号：{known}），请核对批号",
            )
        # 标准文件可多选（一个批号可开多份报告单）；全部必须属于批号识别的代号
        requested_ids: list[uuid.UUID] = list(payload.standard_document_ids or [])
        if not requested_ids and payload.standard_document_id:
            requested_ids = [payload.standard_document_id]
        if requested_ids:
            valid_ids = {d.id for d in docs}
            if any(rid not in valid_ids for rid in requested_ids):
                raise AppException(
                    status_code=400,
                    detail=f"选中的标准文件与批号代号「{code}」不匹配，请勿混用其他代号的标准",
                )
            docs = [d for d in docs if d.id in requested_ids]
        std_items = []
        for d in docs:
            std_items.extend(await list_standard_items(db, d.id))
        if not std_items:
            raise AppException(status_code=400, detail="该产品标准文档没有项目行，无法创建任务")
        # 指定了选中项目时只快照选中的（检阅当日要用的具体 SOP）
        if payload.standard_item_ids:
            wanted = set(payload.standard_item_ids)
            valid_ids = {it.id for it in std_items}
            missing = wanted - valid_ids
            if missing:
                raise AppException(
                    status_code=400,
                    detail=f"有 {len(missing)} 个标准行不属于产品「{payload.product_name}」代号「{code}」的标准，请重新勾选",
                )
            std_items = [it for it in std_items if it.id in wanted]
            if not std_items:
                raise AppException(status_code=400, detail="未选中任何检验项目")

        # 日期分隔符归一化：支持 2026.01.01 / 2026/01/01 等写法
        production_date = _norm_date_str(payload.production_date)
        report_date = _norm_date_str(payload.report_date)
        # 效期：未显式指定时按主标准文档有效期自动计算（生产日期+x年-1天）
        expiry_date = _norm_date_str(payload.expiry_date) or TestTaskService._calc_expiry(
            production_date, docs[0].valid_years
        )
        task = await create_test_task(
            db,
            product_name=payload.product_name,
            batch_number=payload.batch_number,
            production_date=production_date,
            expiry_date=expiry_date,
            specification=payload.specification,
            form_id=payload.form_id,
            standard_document_id=docs[0].id,
            report_date=report_date,
        )
        # 按 (sop_no, item_name) 去重（多个子项目可共用同一 SOP 号；防跨文档重复）
        seen_keys: set[tuple[str, str]] = set()
        snapshot = []
        for it in std_items:
            key = (it.sop_no or "", it.item_name)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            snapshot.append({
                "standard_item_id": it.id,
                "seq": it.seq,
                "category": it.category,
                "item_name": it.item_name,
                "sop_no": it.sop_no,
                "standard_text": it.standard_text,
                "operator": it.operator,
                "limit_min": it.limit_min,
                "limit_max": it.limit_max,
                "method_source": it.method_source,
                "remark": it.remark,
                "judge_mode": TestTaskService._infer_judge_mode(it.operator, it.limit_min, it.limit_max),
                "source": "manual",
            })
        rows = await create_test_results(db, task.id, snapshot)
        # 默认判定规则：文字呈现项目（细菌内毒素→符合规定）与默认未检出（EDTA→未检出）自动填好
        for r in rows:
            default_text = TestTaskService._DEFAULT_FILL_RULES.get(
                TestTaskService._norm_name(r.item_name)
            )
            if default_text and r.is_pass is None:
                r.result_text = default_text
                r.is_pass = True
                r.source = "manual"
                r.filled_at = datetime.now(UTC)
        if rows:
            await db.flush()
        # 飞书推送：仅当出报日期为今天时推送提醒+填报卡片（门控在 notify_task_created 内）
        try:
            from app.modules.quality.feishu.fill_service import notify_task_created

            asyncio.create_task(notify_task_created(str(task.id)))
        except Exception:
            logger.exception("飞书任务推送失败")
        return TestTaskService._to_detail(task, rows)

    # ─── 批量填报 ───

    @staticmethod
    async def update_results(
        db: AsyncSession, task_id: uuid.UUID, payload: TestResultsUpdate
    ) -> TestTaskDetail:
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        if task.status != "in_progress":
            raise AppException(status_code=400, detail=f"任务状态为 {task.status}，不可填报")

        rows = await list_test_results(db, task_id)
        by_id = {r.id: r for r in rows}
        now = datetime.now(UTC)
        updates: list[dict[str, Any]] = []
        for fill in payload.results:
            row = by_id.get(fill.result_id)
            if row is None:
                raise AppException(status_code=400, detail=f"结果行不存在或不属于该任务：{fill.result_id}")
            if row.judge_mode == "auto":
                if fill.result_value is None:
                    raise AppException(status_code=400, detail=f"项目「{row.item_name}」为数值型，请填写结果值")
                verdict = TestTaskService._judge_value(
                    row.operator, row.limit_min, row.limit_max, fill.result_value
                )
                if verdict is None:
                    if fill.is_pass is None:
                        raise AppException(
                            status_code=400,
                            detail=f"项目「{row.item_name}」标准限度缺失，无法自动判定，请人工判定 is_pass",
                        )
                    verdict = fill.is_pass
                updates.append({
                    "result_id": row.id,
                    "result_text": fill.result_text,
                    "result_value": fill.result_value,
                    "is_pass": verdict,
                    "filled_by": None,
                    "filled_at": now,
                })
            else:  # manual：文字型人工判定
                if fill.is_pass is None:
                    raise AppException(status_code=400, detail=f"项目「{row.item_name}」为文字型，请人工判定（is_pass）")
                updates.append({
                    "result_id": row.id,
                    "result_text": fill.result_text,
                    "result_value": fill.result_value,
                    "is_pass": fill.is_pass,
                    "filled_by": None,
                    "filled_at": now,
                })
        await update_test_results_fill(db, updates)
        # 全部判定完成后自动进入待复核
        await TestTaskService.auto_advance_pending_review(db, task_id)
        return TestTaskService._to_detail(task, await list_test_results(db, task_id))

    # ── 待复核自动流转 ──

    @staticmethod
    async def auto_advance_pending_review(db: AsyncSession, task_id: uuid.UUID) -> bool:
        """填报中的任务全部结果行已判定时，自动流转为待复核（专员审核）。"""
        task = await get_test_task(db, task_id)
        if not task or task.status != "in_progress":
            return False
        rows = await list_test_results(db, task_id)
        # 默认判定规则先自动补填（细菌内毒素→符合规定、EDTA→未检出）
        changed = False
        for r in rows:
            default_text = TestTaskService._DEFAULT_FILL_RULES.get(
                TestTaskService._norm_name(r.item_name)
            )
            if default_text and r.is_pass is None:
                r.result_text = default_text
                r.is_pass = True
                r.source = "manual"
                r.filled_at = datetime.now(UTC)
                changed = True
        if changed:
            await db.flush()
            rows = await list_test_results(db, task_id)
        if not rows or any(r.is_pass is None for r in rows):
            return False
        await update_test_task(db, task_id, status="pending_review")
        try:
            from app.modules.quality.feishu.fill_service import notify_pending_review

            asyncio.create_task(notify_pending_review(str(task_id)))
        except Exception:
            logger.exception("待复核提醒推送失败")
        return True

    # ── 不合格事件台账 ──

    @staticmethod
    async def record_unqualified_event(
        db: AsyncSession,
        task: QualityTestTask,
        row: QualityTestResult,
        value: float,
        source: str,
        notify: bool,
        origin_chat_id: str = "",
    ) -> None:
        """不合格事件台账（不写结果行）；notify=True 时触发飞书群提醒（fire-and-forget）。"""
        unit = TestTaskService._unit_of(row.standard_text)
        limit_text = (
            f"{row.operator or ''} {row.limit_min if row.limit_min is not None else ''}"
            f"{row.limit_max if row.limit_max is not None else ''}{unit}"
        ).strip()
        await create_unqualified_event(db, {
            "task_id": task.id,
            "product_name": task.product_name,
            "batch_number": task.batch_number,
            "item_name": row.item_name,
            "sop_no": row.sop_no,
            "result_value": value,
            "standard_text": row.standard_text,
            "limit_text": limit_text,
            "source": source,
        })
        if notify:
            try:
                from app.modules.quality.feishu.fill_service import notify_unqualified

                asyncio.create_task(notify_unqualified(
                    task.product_name, task.batch_number, row.item_name,
                    f"{value}{unit}", limit_text, origin_chat_id=origin_chat_id,
                ))
            except Exception:
                logger.exception("不合格飞书提醒推送失败")

    # ── P1 液相解析映射 ──

    # 计算表标签 → 标准库项目名的别名映射（万古霉素系列）
    _NAME_ALIASES = {
        "vancomycinb": "万古霉素b",
        "vancomycin b": "万古霉素b",
    }

    @staticmethod
    def _unit_of(standard_text: str | None) -> str:
        """从合格标准原文提取单位后缀（如 ≤5.0% → %、≤5000ppm → ppm、≥925μg/mg → μg/mg）。"""
        if not standard_text:
            return ""
        m = re.search(r"([μµ]?g/mg|IU/mg|EU/mg|cfu/g|个/g|ppm|%|％)", standard_text)
        return m.group(1) if m else ""

    @staticmethod
    def _norm_name(s: str) -> str:
        """项目名归一化：去空白/括号内容/％%符号，转小写，套别名映射。"""
        n = re.sub(r"[（(][^）)]*[）)]", "", s)
        n = re.sub(r"[\s.％%]", "", n)
        n = n.lower()
        return TestTaskService._NAME_ALIASES.get(n, n)

    @staticmethod
    def _match_task_row(
        rows: list[QualityTestResult],
        name: str,
        sop_no: str | None = None,
        doc_item_ids: set[uuid.UUID] | None = None,
    ) -> QualityTestResult | None:
        """按项目名匹配结果行：归一化精确 → 去「杂质」前缀精确 → 包含（唯一才返回）。

        doc_item_ids（表号→标准文档的项目行集合）提供时优先在该集合限定的行池内匹配，
        其次 sop_no 行池，均未命中再回落全量名匹配。
        """
        if doc_item_ids:
            pool = [r for r in rows if r.standard_item_id in doc_item_ids]
            if not pool:
                pool = rows
        elif sop_no:
            pool = [r for r in rows if r.sop_no == sop_no]
            if not pool:
                pool = rows
        else:
            pool = rows
        norm = TestTaskService._norm_name(name)
        exact = [r for r in pool if TestTaskService._norm_name(r.item_name) == norm]
        if len(exact) == 1:
            return exact[0]
        clean = norm.replace("杂质", "").strip()
        if clean != norm:
            exact2 = [r for r in pool if TestTaskService._norm_name(r.item_name) == clean]
            if len(exact2) == 1:
                return exact2[0]
        contains = [r for r in pool if norm in TestTaskService._norm_name(r.item_name) or TestTaskService._norm_name(r.item_name) in norm]
        if len(contains) == 1:
            return contains[0]
        if pool is not rows:
            return TestTaskService._match_task_row(rows, name, None, None)
        return None

    @staticmethod
    async def fill_task_from_report(
        db: AsyncSession,
        task: QualityTestTask,
        report: LcReportOut,
        record_id: uuid.UUID,
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
        return await TestTaskService._fill_candidates(db, task, candidates, record_id)

    @staticmethod
    async def _fill_candidates(
        db: AsyncSession,
        task: QualityTestTask,
        candidates: list[tuple[str, float]],
        record_id: uuid.UUID,
        sop_no: str | None = None,
        doc_item_ids: set[uuid.UUID] | None = None,
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
            row = TestTaskService._match_task_row(rows, name, sop_no, doc_item_ids)
            if row is None or row.judge_mode != "auto":
                unmatched.append(name)
                continue
            verdict = TestTaskService._judge_value(row.operator, row.limit_min, row.limit_max, value)
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
                "filled_by": None,
                "filled_at": now,
            })
            filled_names.append(row.item_name)
        if updates:
            await update_test_results_fill(db, updates)
        # 全部判定完成后自动进入待复核
        await TestTaskService.auto_advance_pending_review(db, task.id)
        return filled_names, unmatched

    @staticmethod
    async def parse_lc_into_task(
        db: AsyncSession, task_id: uuid.UUID, file_bytes: bytes, filename: str
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
        filled, unmatched = await TestTaskService.fill_task_from_report(
            db, task, uploaded.report, uploaded.record_id
        )
        detail = TestTaskService._to_detail(task, await list_test_results(db, task_id))
        return detail, filled, unmatched

    # ── 模板配置驱动的通用解析 ──

    @staticmethod
    async def parse_lc_generic(
        db: AsyncSession, file_bytes: bytes, filename: str
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
            filled, unmatched = await TestTaskService._fill_candidates(
                db, task, candidates, record_id, cfg.sop_no, doc_item_ids
            )
            # 未匹配组分自动追加为任务行（限度取计算表自带限度列，如 RS1-7）
            appended: list[str] = []
            appended_orig: set[str] = set()
            rows = await list_test_results(db, task.id)
            existing_names = {TestTaskService._norm_name(r.item_name) for r in rows}
            next_seq = max((r.seq or 0 for r in rows), default=0) + 1
            for c in parsed.components:
                if c.report_value is None or c.limit is None or c.name in set(filled):
                    continue
                name = c.name.rstrip("％%").strip()
                norm = TestTaskService._norm_name(name)
                if norm in existing_names:
                    continue
                op = "≥" if ("万古霉素" in name or "vancomycin" in name.lower()) else "≤"
                verdict = TestTaskService._judge_value(
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
        return {"parse": parsed, "record_id": record_id, "task_link": task_link}

    # ── 追加行 ──

    @staticmethod
    async def add_result(
        db: AsyncSession, task_id: uuid.UUID, payload: TestResultCreate
    ) -> TestResultOut:
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        if task.status != "in_progress":
            raise AppException(status_code=400, detail=f"任务状态为 {task.status}，不可追加项目")
        rows = await list_test_results(db, task_id)
        if payload.sop_no and any(
            r.sop_no == payload.sop_no and r.item_name == payload.item_name for r in rows
        ):
            raise AppException(
                status_code=400,
                detail=f"该任务已存在同 SOP 号同名称的项目行（{payload.sop_no} {payload.item_name}）",
            )
        next_seq = max((r.seq or 0 for r in rows), default=0) + 1
        created = await create_test_results(db, task_id, [{
            "standard_item_id": None,
            "seq": next_seq,
            "category": payload.category,
            "item_name": payload.item_name,
            "sop_no": payload.sop_no,
            "standard_text": payload.standard_text,
            "operator": payload.operator,
            "limit_min": payload.limit_min,
            "limit_max": payload.limit_max,
            "method_source": payload.method_source,
            "remark": payload.remark,
            "judge_mode": TestTaskService._infer_judge_mode(payload.operator, payload.limit_min, payload.limit_max),
            "source": "manual",
        }])
        return TestTaskService._to_result_out(created[0])

    # ── 状态流转 ──

    @staticmethod
    async def update_status(
        db: AsyncSession, task_id: uuid.UUID, payload: TestTaskStatusUpdate
    ) -> TestTaskDetail:
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        target = payload.status
        if task.status == "void":
            raise AppException(status_code=400, detail="任务已作废，不可变更状态")
        if target == "void":
            pass  # 任何非 void 状态可作废
        elif task.status == target:
            raise AppException(status_code=400, detail=f"任务已处于 {target} 状态")
        elif task.status == "in_progress" and target == "pending_review":
            # 手动转待复核：必须全部判定完成（正常路径为填报后自动流转）
            rows = await list_test_results(db, task_id)
            unfilled = [r.item_name for r in rows if r.is_pass is None]
            if unfilled:
                raise AppException(
                    status_code=400,
                    detail=f"存在 {len(unfilled)} 项未判定，无法进入待复核：{'、'.join(unfilled[:5])}",
                )
        elif task.status == "pending_review" and target == "completed":
            pass  # 专员审核通过
        elif task.status == "pending_review" and target == "in_progress":
            pass  # 专员驳回重填
        elif task.status == "completed" and target == "in_progress":
            pass  # completed → in_progress 重新打开
        else:
            raise AppException(status_code=400, detail=f"非法状态流转：{task.status} → {target}")
        updated = await update_test_task(db, task_id, status=target)
        if not updated:
            raise AppException(status_code=404, detail="检验任务不存在")
        return TestTaskService._to_detail(updated, await list_test_results(db, task_id))

    # ── 出报日期补录（关联当日机器人任务推送）──

    @staticmethod
    async def update_report_date(
        db: AsyncSession, task_id: uuid.UUID, payload: TestTaskReportDateUpdate
    ) -> TestTaskDetail:
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        report_date = _norm_date_str(payload.report_date)
        updated = await update_test_task_report_date(db, task_id, report_date)
        if not updated:
            raise AppException(status_code=404, detail="检验任务不存在")
        # 补录出报日期为「今天」→ 即刻触发机器人推送（门控在 notify_task_created 内）
        if payload.report_date:
            try:
                from app.modules.quality.feishu.fill_service import notify_task_created

                asyncio.create_task(notify_task_created(str(task_id)))
            except Exception:
                logger.exception("出报日期补录推送失败")
        return TestTaskService._to_detail(updated, await list_test_results(db, task_id))

    # ── 删除 ──

    @staticmethod
    async def delete_task(db: AsyncSession, task_id: uuid.UUID) -> QualityTestTask | None:
        return await delete_test_task(db, task_id)

    @staticmethod
    async def delete_result(
        db: AsyncSession, task_id: uuid.UUID, result_id: uuid.UUID
    ) -> QualityTestResult | None:
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        if task.status != "in_progress":
            raise AppException(status_code=400, detail=f"任务状态为 {task.status}，不可删除项目")
        row = await delete_test_result(db, result_id)
        if row is None or row.task_id != task_id:
            raise AppException(status_code=404, detail="结果行不存在")
        return row

    # ── P2 任务驱动 COA ──

    @staticmethod
    def _alias_keys(name: str) -> list[str]:
        """项目名别名键：原名 / 去符号归一化 / 小写。

        简写类占位符（ph、单去氯、吸光度450nm）由模板填充期的
        resolve_data 双向前缀解析兜底，避免前缀键相互覆盖（如 杂质B1 覆盖 杂质B）。
        """
        keys = {name}
        norm = re.sub(r"[（()）\s.%％%]", "", name)
        keys.add(norm)
        keys.add(norm.lower())
        return list(keys)

    @staticmethod
    def _build_report_data(
        task: QualityTestTask,
        doc: QualityStandardDocument | None,
        rows: list[QualityTestResult],
        serial_no: str,
    ) -> dict[str, Any]:
        """结果行 → 模板填充字典（按指定标准文件规格与给定流水号）。

        以模板占位符名为驱动：每个项目生成一组别名键（原名/归一化/前缀），
        数值保留 float 由 format_value 按占位符格式渲染。表头字段按 3205
        真实报告单补齐：流水号/规格/生产日期/批量/有效期。
        """
        all_pass = all(r.is_pass for r in rows)
        spec_text = task.specification or (doc.specification if doc else "") or ""

        def dot_date(s: str | None) -> str:
            return (s or "").replace("-", ".").replace("/", ".")

        data: dict[str, Any] = {
            "产品名称": task.product_name,
            "批号": task.batch_number,
            "表号": task.form_id or "",
            "流水号": serial_no,
            "规格": spec_text,
            "生产日期": dot_date(task.production_date),
            "有效期_年": dot_date(task.expiry_date),
            "效期": dot_date(task.expiry_date),
            "有效期": dot_date(task.expiry_date),
            "批量_kg": "-",
            "判定结果": "合格" if all_pass else "不合格",
        }
        for r in rows:
            value: Any = r.result_value if r.result_value is not None else (r.result_text or "")
            verdict = "合格" if r.is_pass else "不合格"
            for key in TestTaskService._alias_keys(r.item_name):
                data[key] = value
                data[f"{key}_判定"] = verdict
        return data

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
        for did in doc_ids:
            d = await get_standard_document(db, did)
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
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        base_seq = await count_report_records_since(db, today_start)
        splits: list[dict[str, Any]] = []
        ordered_docs = sorted(docs.values(), key=lambda d: d.file_no)
        for i, d in enumerate(ordered_docs):
            template = next(
                (b.template_path for b in bindings if b.standard_document_id == d.id), None
            ) or d.template_path or ""
            if not template:
                raise AppException(
                    status_code=400,
                    detail=f"标准文件 {d.file_no} 未绑定 COA 模板，无法逐份生成",
                )
            serial_no = f"{datetime.now(UTC):%y%m%d}{base_seq + i + 1:02d}"
            splits.append({
                "doc": d,
                "template": template,
                "rows": rows_by_doc[d.id],
                "fill_data": TestTaskService._build_report_data(
                    task, d, rows_by_doc[d.id], serial_no
                ),
                "product_name": task.product_name,
                "batch_number": task.batch_number,
            })
        return splits

    # ── 查询 ──

    @staticmethod
    async def get_task_detail(db: AsyncSession, task_id: uuid.UUID) -> TestTaskDetail | None:
        task = await get_test_task(db, task_id)
        if not task:
            return None
        return TestTaskService._to_detail(task, await list_test_results(db, task_id))

    @staticmethod
    async def list_tasks(
        db: AsyncSession,
        product_name: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[TestTaskListItem], int]:
        items, total = await list_test_tasks(db, product_name, status, page, page_size)
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

    @staticmethod
    def _to_result_out(r: QualityTestResult) -> TestResultOut:
        return TestResultOut(
            id=r.id,
            seq=r.seq,
            category=r.category,
            item_name=r.item_name,
            sop_no=r.sop_no,
            standard_text=r.standard_text,
            operator=r.operator,
            limit_min=r.limit_min,
            limit_max=r.limit_max,
            method_source=r.method_source,
            remark=r.remark,
            result_text=r.result_text,
            result_value=r.result_value,
            is_pass=r.is_pass,
            judge_mode=r.judge_mode,
            source=r.source,
            filled_at=r.filled_at,
        )

    @staticmethod
    def _to_detail(task: QualityTestTask, results: list[QualityTestResult]) -> TestTaskDetail:
        return TestTaskDetail(
            id=task.id,
            product_name=task.product_name,
            batch_number=task.batch_number,
            production_date=task.production_date,
            expiry_date=task.expiry_date,
            specification=task.specification,
            form_id=task.form_id,
            report_date=task.report_date,
            standard_document_id=task.standard_document_id,
            status=task.status,
            created_at=task.created_at,
            results=[TestTaskService._to_result_out(r) for r in results],
        )


test_task_service = TestTaskService()
