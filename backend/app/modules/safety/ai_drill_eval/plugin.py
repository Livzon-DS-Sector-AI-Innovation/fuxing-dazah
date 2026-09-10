"""AI 演练评估表插件 — 核心引擎。

基于演练记录表全文与主表字段，生成评估表结构化内容（DrillEvalOutput），
供渲染层产出与人工样例同格式的评估表 docx。

用法:
    from app.modules.safety.ai_drill_eval import DrillEvalPlugin

    plugin = DrillEvalPlugin(ai_service)
    output = await plugin.review(input_data)
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.safety.ai_drill_eval.prompts import SYSTEM_PROMPT, build_user_prompt
from app.modules.safety.ai_drill_eval.schemas import (
    VALID_DRILL_TYPES,
    VALID_GRADES,
    DrillEvalInput,
    DrillEvalItem,
    DrillEvalOutput,
)

logger = logging.getLogger(__name__)

_EXPECTED_KEYS = [
    "drill_name", "drill_time", "drill_place", "org_department",
    "commander", "recorder", "participants_desc", "participant_count_desc",
    "drill_type_check", "overall_comment", "grade", "issues",
    "evaluator", "eval_date",
]

_TEXT_FIELDS = [
    "drill_name", "drill_time", "drill_place", "org_department",
    "commander", "recorder", "participants_desc", "participant_count_desc",
    "drill_type_check", "overall_comment", "eval_date",
]


class DrillEvalError(Exception):
    """AI 演练评估表生成失败异常。"""


def _clean_person_name(value: Any) -> str:
    """清洗人名：去空白与「AI」标识，截断到 32 字。

    AI 无姓名依据时可能输出「AI」「AI 评估」等占位，一律清空。
    """
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if not cleaned or "AI" in cleaned.upper():
        return ""
    return cleaned[:32]


class DrillEvalPlugin:
    """演练评估表生成插件。

    Args:
        ai_service: AuditedAIService 实例（create_ai_service("text") 返回）
    """

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def review(self, input_data: DrillEvalInput) -> DrillEvalOutput:
        """生成评估表内容。

        Raises:
            DrillEvalError: AI 调用失败或输出无法解析
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(input_data)},
        ]
        try:
            raw = await self.ai_service.chat_parsed(
                messages=messages,
                expected_keys=_EXPECTED_KEYS,
                temperature=0.1,
            )
        except Exception as e:
            logger.error("AI 演练评估表生成调用失败: %s", e)
            raise DrillEvalError(f"AI 调用失败: {e}") from e
        return self._parse_output(raw)

    def _parse_output(self, raw: Any) -> DrillEvalOutput:
        """容错解析：缺键默认空、枚举非法置空、人名清洗，不抛字段级异常。"""
        if not isinstance(raw, dict):
            raise DrillEvalError(f"AI 输出不是 JSON 对象: {str(raw)[:200]}")

        data: dict[str, Any] = {}
        for key in _TEXT_FIELDS:
            value = raw.get(key)
            data[key] = value.strip() if isinstance(value, str) else ""
        # 枚举字段先取原值，再做合法性校验
        for key in ("grade", "drill_type_check"):
            value = raw.get(key)
            data[key] = value.strip() if isinstance(value, str) else ""

        # 枚举字段：非法值置空（渲染层全 □ 兜底），不抛
        for key, valid in (("grade", VALID_GRADES), ("drill_type_check", VALID_DRILL_TYPES)):
            if data.get(key) not in valid:
                if data.get(key):
                    logger.warning("AI 评估表 %s 非法值已置空: %r", key, data[key])
                data[key] = ""

        data["commander"] = _clean_person_name(raw.get("commander"))
        data["recorder"] = _clean_person_name(raw.get("recorder"))
        data["evaluator"] = _clean_person_name(raw.get("evaluator"))

        issues_raw = raw.get("issues")
        issues: list[DrillEvalItem] = []
        if isinstance(issues_raw, list):
            for item in issues_raw:
                if not isinstance(item, dict):
                    continue
                issues.append(
                    DrillEvalItem(
                        issue=str(item.get("issue", "") or "").strip(),
                        action=str(item.get("action", "") or "").strip(),
                        deadline=str(item.get("deadline", "") or "").strip(),
                        done_status=str(item.get("done_status", "") or "").strip(),
                        rectifier=_clean_person_name(item.get("rectifier")),
                        confirmer=_clean_person_name(item.get("confirmer")),
                    )
                )
        data["issues"] = issues

        return DrillEvalOutput.model_validate(data)
