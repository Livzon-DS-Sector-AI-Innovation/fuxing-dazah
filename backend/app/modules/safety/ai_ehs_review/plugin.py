"""AI EHS 变更审核插件 — 核心引擎。

对变更申请按 4 个维度（申请变更原因/变更计划内容/预计效果/变更风险评估及建议措施）
生成「结论 + 审核报告」+ AI 预审意见，输出对应飞书 Bitable 审批表的 4 组 AI 审核列。

用法:
    from app.modules.safety.ai_ehs_review import EhsChangeReviewPlugin

    plugin = EhsChangeReviewPlugin(ai_service)
    output = await plugin.review(input_data, knowledge_md="...")
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any

from app.modules.safety.ai_ehs_review.prompts import SYSTEM_PROMPT, build_user_prompt
from app.modules.safety.ai_ehs_review.schemas import (
    EhsReviewInput,
    EhsReviewOutput,
)

logger = logging.getLogger(__name__)

_EXPECTED_KEYS = ["reason", "plan", "effect", "risk", "pre_review"]
_TRAILING_PUNCTUATION = "。，！？,.!?;；：:"


class EhsReviewError(Exception):
    """AI EHS 变更审核失败异常。"""


def _sanitize_conclusion(value: str | None) -> str:
    """清洗 AI 返回的结论字符串（去首尾空白/标点），并归一化到三值之一。

    未命中映射的未知结论（如「无法判定」「合格」等）不原样透传，
    一律兜底为「需补充完善」，由人工确认。
    """
    if not value:
        return "需补充完善"
    cleaned = value.strip().rstrip(_TRAILING_PUNCTUATION)
    mapping = {
        "审核通过": "审核通过",
        "通过": "审核通过",
        "需补充完善": "需补充完善",
        "需要补充完善": "需补充完善",
        "需补充": "需补充完善",
        "补充完善": "需补充完善",
        "审核不通过": "审核不通过",
        "不通过": "审核不通过",
        "未通过": "审核不通过",
    }
    return mapping.get(cleaned, "需补充完善")


class EhsChangeReviewPlugin:
    """EHS 变更 4 维度审核插件。

    Args:
        ai_service: AuditedAIService 实例（create_ai_service("text") 返回）
    """

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def review(
        self,
        input_data: EhsReviewInput,
        knowledge_md: str = "",
    ) -> EhsReviewOutput:
        """执行 4 维度审核。

        Args:
            input_data: 变更基本信息 + 4 维度文本
            knowledge_md: RAG 检索的法规片段（可选）

        Returns:
            4 维度审核结果 + AI 预审意见

        Raises:
            EhsReviewError: AI 调用失败或输出无法解析
        """
        prompt = build_user_prompt(
            change_no=input_data.change_no,
            title=input_data.title,
            reason_text=input_data.reason_text,
            plan_text=input_data.plan_text,
            effect_text=input_data.effect_text,
            risk_text=input_data.risk_text,
            change_type=input_data.change_type,
            change_grade=input_data.change_grade,
            department=input_data.department,
            knowledge_md=knowledge_md,
        )
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
            logger.error("AI EHS 变更审核调用失败: %s", e)
            raise EhsReviewError(f"AI 调用失败: {e}") from e

        return self._parse_output(raw)

    # ── 内部方法 ──

    @staticmethod
    def _parse_dim(raw: Any, key: str) -> tuple[str, str]:
        """解析单维度 dict（可能缺失 → 默认需补充完善）。"""
        if isinstance(raw, dict):
            conclusion = _sanitize_conclusion(str(raw.get("conclusion", "") or ""))
            report = str(raw.get("report", "") or "").strip()
        elif isinstance(raw, str):
            conclusion = _sanitize_conclusion(raw)
            report = ""
        else:
            conclusion = "需补充完善"
            report = ""
        return conclusion, report

    def _parse_output(self, raw: dict) -> EhsReviewOutput:
        try:
            reason_c, reason_r = self._parse_dim(raw.get("reason"), "reason")
            plan_c, plan_r = self._parse_dim(raw.get("plan"), "plan")
            effect_c, effect_r = self._parse_dim(raw.get("effect"), "effect")
            risk_c, risk_r = self._parse_dim(raw.get("risk"), "risk")
            return EhsReviewOutput(
                reason={"conclusion": reason_c, "report": reason_r},
                plan={"conclusion": plan_c, "report": plan_r},
                effect={"conclusion": effect_c, "report": effect_r},
                risk={"conclusion": risk_c, "report": risk_r},
                pre_review=str(raw.get("pre_review", "") or "").strip(),
            )
        except (ValueError, KeyError, TypeError) as e:
            raise EhsReviewError(
                f"AI 输出解析失败: {e}\n"
                f"原始输出: {_json.dumps(raw, ensure_ascii=False, default=str)[:500]}"
            ) from e
