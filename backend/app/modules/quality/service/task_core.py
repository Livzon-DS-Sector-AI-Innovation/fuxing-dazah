"""Quality 业务逻辑编排。"""

import logging
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from app.modules.quality.models import (
    QualityStandardDocument,
    QualityTestResult,
    QualityTestTask,
)
from app.modules.quality.schemas import (
    TestResultOut,
    TestTaskDetail,
)

logger = logging.getLogger(__name__)

class _TaskCore:
    """检验任务核心助手：判定规则/名称归一化/效期计算/详情组装等纯逻辑。"""

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
    def _unit_of(standard_text: str | None) -> str:
        """从合格标准原文提取单位后缀（如 ≤5.0% → %、≤5000ppm → ppm、≥925μg/mg → μg/mg）。"""
        if not standard_text:
            return ""
        m = re.search(r"([μµ]?g/mg|IU/mg|EU/mg|cfu/g|个/g|ppm|%|％)", standard_text)
        return m.group(1) if m else ""

    # 计算表标签 → 标准库项目名的别名映射（万古霉素系列）
    _NAME_ALIASES = {
        "vancomycinb": "万古霉素b",
        "vancomycin b": "万古霉素b",
    }

    @staticmethod
    def _norm_name(s: str) -> str:
        """项目名归一化：去空白/括号内容/％%符号，转小写，套别名映射。"""
        n = re.sub(r"[（(][^）)]*[）)]", "", s)
        n = re.sub(r"[\s.％%]", "", n)
        n = n.lower()
        return _TaskCore._NAME_ALIASES.get(n, n)

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
        norm = _TaskCore._norm_name(name)
        exact = [r for r in pool if _TaskCore._norm_name(r.item_name) == norm]
        if len(exact) == 1:
            return exact[0]
        clean = norm.replace("杂质", "").strip()
        if clean != norm:
            exact2 = [r for r in pool if _TaskCore._norm_name(r.item_name) == clean]
            if len(exact2) == 1:
                return exact2[0]
        contains = [r for r in pool if norm in _TaskCore._norm_name(r.item_name) or _TaskCore._norm_name(r.item_name) in norm]
        if len(contains) == 1:
            return contains[0]
        if pool is not rows:
            return _TaskCore._match_task_row(rows, name, None, None)
        return None

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
            for key in _TaskCore._alias_keys(r.item_name):
                data[key] = value
                data[f"{key}_判定"] = verdict
        return data

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
            results=[_TaskCore._to_result_out(r) for r in results],
        )

