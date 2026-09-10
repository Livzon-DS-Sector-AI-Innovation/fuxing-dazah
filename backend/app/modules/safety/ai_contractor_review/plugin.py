"""相关方准入 AI 审核插件 — 核心引擎。

当前仅审核「安全管理协议」维度（agreement），生成
「结论 + 审核报告（分类分节）+ 不符合项」，并汇总总体结论
（overall_conclusion / overall_report / defect_categories），
输出对应飞书 Bitable「相关方准入」表的 3 个回填字段。
企业营业执照 / 现场作业保险凭证维度预留待开发。

用法:
    from app.modules.safety.ai_contractor_review import ContractorAdmissionReviewPlugin

    plugin = ContractorAdmissionReviewPlugin(ai_service)
    output = await plugin.review(input_data, knowledge_md="...")
"""

from __future__ import annotations

import json as _json
import logging
import re
from typing import Any

from app.modules.safety.ai_contractor_review.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.modules.safety.ai_contractor_review.schemas import (
    AdmissionDimensionResult,
    AdmissionReviewInput,
    AdmissionReviewOutput,
    ReviewConclusion,
)

logger = logging.getLogger(__name__)

_EXPECTED_KEYS = [
    "agreement",
    "overall_conclusion",
    "overall_report",
    "defect_categories",
]
_TRAILING_PUNCTUATION = "。，！？,.!?;；：:"

# 4 类不符合原因 → Bitable 多选标准值（带「安全管理协议-」附件前缀）
_CATEGORY_PREFIX_MAP: dict[str, str] = {
    "A": "安全管理协议-A基础信息类",
    "B": "安全管理协议-B有效期类",
    "C": "安全管理协议-C签章类",
    "D": "安全管理协议-D骑缝章类",
}
_CATEGORY_KEYWORD_MAP: dict[str, str] = {
    "基础信息": "安全管理协议-A基础信息类",
    "有效期": "安全管理协议-B有效期类",
    "签章": "安全管理协议-C签章类",
    "骑缝章": "安全管理协议-D骑缝章类",
}


class ContractorAdmissionReviewError(Exception):
    """相关方准入 AI 审核失败异常。"""


def _sanitize_conclusion(value: str | None) -> str:
    """归一化 AI 返回的结论字符串到三标准值之一（审核通过/需补充完善/审核不通过）。

    「通过/审核合格/合格」等变体 → 审核通过；
    「补充/需补充/完善」等变体 → 需补充完善；
    「不通过/不合格/驳回」等变体 → 审核不通过。
    """
    if not value:
        return ReviewConclusion.NEEDS_SUPPLEMENT.value
    cleaned = value.strip().rstrip(_TRAILING_PUNCTUATION)
    if not cleaned:
        return ReviewConclusion.NEEDS_SUPPLEMENT.value
    # 「不通过」系含子串「通过」，必须先于通过判定
    if any(k in cleaned for k in ("不通过", "未通过", "不合格", "驳回", "拒绝")):
        return ReviewConclusion.REJECTED.value
    if any(k in cleaned for k in ("通过", "合格")):
        return ReviewConclusion.APPROVED.value
    if any(k in cleaned for k in ("补充", "完善", "补材", "待补")):
        return ReviewConclusion.NEEDS_SUPPLEMENT.value
    return ReviewConclusion.NEEDS_SUPPLEMENT.value


def _sanitize_defects(values: Any) -> list[str]:
    """归一化 defect_categories 到 4 类标准值（匹配 A/B/C/D 前缀或关键词），去重保序。"""
    if not values:
        return []
    result: list[str] = []
    for v in values:
        if not isinstance(v, str):
            continue
        cleaned = v.strip().rstrip(_TRAILING_PUNCTUATION)
        if not cleaned:
            continue
        canonical = _CATEGORY_PREFIX_MAP.get(cleaned[0].upper())
        if canonical is None:
            canonical = next(
                (cat for kw, cat in _CATEGORY_KEYWORD_MAP.items() if kw in cleaned),
                None,
            )
        if canonical is not None and canonical not in result:
            result.append(canonical)
    return result


def _clean_defect_list(values: Any) -> list[str]:
    """清洗单维度 defects 明细（去空白/去重/保序）。"""
    if not values:
        return []
    result: list[str] = []
    for v in values:
        if not isinstance(v, str):
            continue
        cleaned = v.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


# 报告应只保留分类分节的判定内容，截掉前后对话性内容（客套开头/补材指引/结尾致谢）
# 匹配「一、安全管理协议-A基础信息类」「1、安全管理协议-B有效期类」
# 「（一）安全管理协议-C签章类」「1. 安全管理协议-D骑缝章类」等节标题
_CN_NUM = r"(?:[一二三四五六七八九十]+|[0-9]+)"
_JUDGMENT_SECTION_RE = re.compile(
    rf"(?:{_CN_NUM}、|（{_CN_NUM}）|\({_CN_NUM}\)|{_CN_NUM}\.)"
    r"\s*安全管理协议-[ABCD](?:基础信息类|有效期类|签章类|骑缝章类)"
)
_TRAILING_CHAT_MARKERS = ("请补充", "请提供", "感谢", "谢谢", "补齐后", "再次提交", "重新提交", "期待", "配合")


def _extract_judgment_report(text: str) -> str:
    """从 AI 报告中提取纯判定内容：从第一个「一、安全管理协议-X类」节标题起，
    截掉开头的对话性内容；结尾若有补材指引/致谢等对话内容一并截掉。

    锚点未命中时兜底：从第一处「安全管理协议」起截断；仍不存在则全文保留（warning）。
    """
    if not text:
        return ""
    # 1) 截开头：定位第一个分类节标题；找不到则从第一处「安全管理协议」起截断
    m = _JUDGMENT_SECTION_RE.search(text)
    if m:
        start = m.start()
    else:
        idx = text.find("安全管理协议")
        if idx == -1:
            logger.warning("审核报告未找到「安全管理协议」截断锚点，全文保留")
            return text.strip()
        start = idx
    body = text[start:].strip()
    if not body:
        return ""
    # 2) 截结尾：找到最后一个节标题之后的对话内容起点。
    #    判定内容的节标题行（一、二、…）是结构锚点，节标题之后若出现
    #    「请补充/感谢/谢谢」等标记，则从此处截断（保留最后一个节标题及其编号条目）。
    #    先找所有节标题位置，从最后一个节标题起扫描后续文本中最早的对话标记。
    last_section = max(
        (m.start() for m in _JUDGMENT_SECTION_RE.finditer(body)), default=0
    )
    tail = body[last_section:]
    cut = len(body)
    for marker in _TRAILING_CHAT_MARKERS:
        idx = tail.find(marker)
        if idx != -1 and last_section + idx < cut:
            cut = last_section + idx
    # 3) 若截断后只剩节标题没有条目（如"四、…骑缝章类"后直接跟对话），
    #    说明该节无条目，把该节标题也去掉。
    cleaned = body[:cut].rstrip()
    # 去掉以节标题结尾的孤立行
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    while lines and _JUDGMENT_SECTION_RE.fullmatch(lines[-1].strip()):
        lines.pop()
    return "\n".join(lines).strip()


class ContractorAdmissionReviewPlugin:
    """相关方准入审核插件（当前仅协议维度）。

    Args:
        ai_service: AuditedAIService 实例（create_ai_service("text") 返回）
    """

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def review(
        self,
        input_data: AdmissionReviewInput,
        knowledge_md: str = "",
    ) -> AdmissionReviewOutput | None:
        """执行安全管理协议审核。

        Args:
            input_data: 相关方基本信息 + 协议文本/视觉描述
            knowledge_md: RAG 检索的法规片段（可选；非空时覆盖 input_data.knowledge_md）

        Returns:
            协议维度审核结果 + 总体结论；AI 未返回可解析结果时返回 None

        Raises:
            ContractorAdmissionReviewError: AI 调用失败或输出无法解析
        """
        if knowledge_md:
            input_data = input_data.model_copy(update={"knowledge_md": knowledge_md})
        prompt = build_user_prompt(input_data)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            raw = await self.ai_service.chat_parsed(
                messages=messages,
                expected_keys=_EXPECTED_KEYS,
                temperature=0.1,
            )
        except Exception as e:
            logger.error("相关方准入 AI 审核调用失败: %s", e)
            raise ContractorAdmissionReviewError(f"AI 调用失败: {e}") from e

        if raw is None:
            logger.warning("相关方准入 AI 审核返回空结果")
            return None
        return self._parse_output(raw)

    # ── 内部方法 ──

    @staticmethod
    def _parse_dim(raw: Any) -> AdmissionDimensionResult:
        """解析单维度结果（可能缺失/字符串 → 保守默认需补充完善）。"""
        if isinstance(raw, dict):
            conclusion = _sanitize_conclusion(str(raw.get("conclusion", "") or ""))
            report = str(raw.get("report", "") or "").strip()
            defects = _clean_defect_list(raw.get("defects"))
        elif isinstance(raw, str):
            conclusion = _sanitize_conclusion(raw)
            report = ""
            defects = []
        else:
            conclusion = ReviewConclusion.NEEDS_SUPPLEMENT.value
            report = ""
            defects = []
        return AdmissionDimensionResult(
            conclusion=conclusion,
            report=report,
            defects=defects,
        )

    def _parse_output(self, raw: dict[str, Any]) -> AdmissionReviewOutput:
        if not isinstance(raw, dict):
            raise ContractorAdmissionReviewError(
                f"AI 输出非 dict: {type(raw).__name__} "
                f"原始输出: {_json.dumps(raw, ensure_ascii=False, default=str)[:500]}"
            )
        try:
            agreement = self._parse_dim(raw.get("agreement"))
            # 只保留分类分节的判定内容，截掉前后对话性内容（客套/补材指引/致谢）
            agreement_report = _extract_judgment_report(agreement.report)
            overall_report = _extract_judgment_report(
                str(raw.get("overall_report", "") or "").strip()
            )
            # 兜底：overall_report 若为空（AI 只写了对话内容被全部截掉），
            # 用协议维度报告（保证与 AI不符合项 分类一一对应）
            if not overall_report:
                overall_report = agreement_report
            return AdmissionReviewOutput(
                agreement=AdmissionDimensionResult(
                    conclusion=agreement.conclusion,
                    report=agreement_report,
                    defects=agreement.defects,
                ),
                # license / insurance 预留维度：当前不审核，保持 None
                license=None,
                insurance=None,
                overall_conclusion=_sanitize_conclusion(
                    str(raw.get("overall_conclusion", "") or "")
                ),
                overall_report=overall_report,
                defect_categories=_sanitize_defects(raw.get("defect_categories")),
            )
        except (ValueError, KeyError, TypeError) as e:
            raise ContractorAdmissionReviewError(
                f"AI 输出解析失败: {e}\n"
                f"原始输出: {_json.dumps(raw, ensure_ascii=False, default=str)[:500]}"
            ) from e
