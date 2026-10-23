"""AI 签到/成绩单解析插件 — 核心引擎（链3，vision）。

用法:
    from app.modules.safety.ai_training_record_parsing import (
        TrainingRecordParsingPlugin,
    )

    plugin = TrainingRecordParsingPlugin(ai_service)  # create_ai_service("vision")
    output = await plugin.generate(TrainingRecordParseInput(...))

场景键：training_record_parsing（ai_config/scenario_registry 注册）。
回填口径（§6.3）由编排层执行：high→回填数字列；medium/low→仅备注；
无法识别→仅备注。人终判：人工在表上直接改=覆盖。
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.safety.ai_training_record_parsing.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.modules.safety.ai_training_record_parsing.schemas import (
    CONFIDENCE_LEVELS,
    CONFIDENCE_LOW,
    DOC_TYPES,
    DOC_UNKNOWN,
    TrainingRecordParseInput,
    TrainingRecordParseOutput,
)

logger = logging.getLogger(__name__)

_EXPECTED_KEYS = [
    "doc_type", "attendance_count", "names", "passed_count",
    "scores", "confidence", "unrecognized", "notes",
]


class TrainingRecordParsingError(Exception):
    """签到/成绩单解析失败（vision 调用或输出解析）。"""


class TrainingRecordParsingPlugin:
    """签到表/成绩单图片 → 结构化转录。

    Args:
        ai_service: AuditedAIService 实例（create_ai_service("vision") 返回，
        需支持 chat_vision_parsed）
    """

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def generate(
        self, input_data: TrainingRecordParseInput
    ) -> TrainingRecordParseOutput:
        text_prompt = (
            SYSTEM_PROMPT
            + "\n\n"
            + build_user_prompt(
                training_name=input_data.training_name,
                expected_count=input_data.expected_count,
                assessment=input_data.assessment,
            )
        )
        try:
            raw = await self.ai_service.chat_vision_parsed(
                text_prompt=text_prompt,
                image_urls=[input_data.image_data_uri],
                expected_keys=_EXPECTED_KEYS,
                temperature=0.1,
            )
        except Exception as e:
            logger.error("签到成绩解析 vision 调用失败: %s", e)
            raise TrainingRecordParsingError(f"vision 调用失败: {e}") from e
        return self._parse_output(raw)

    @staticmethod
    def _parse_output(raw: Any) -> TrainingRecordParseOutput:
        if not isinstance(raw, dict):
            raise TrainingRecordParsingError(
                f"AI 输出非 dict: {type(raw).__name__}"
            )
        doc_type = str(raw.get("doc_type") or "").strip()
        if doc_type not in DOC_TYPES:
            doc_type = DOC_UNKNOWN
        confidence = str(raw.get("confidence") or "").strip().lower()
        if confidence not in CONFIDENCE_LEVELS:
            confidence = CONFIDENCE_LOW

        def _str_list(value: Any) -> list[str]:
            if isinstance(value, str):
                value = [value]
            return [str(v).strip() for v in (value or []) if str(v).strip()]

        scores: list[dict[str, Any]] = []
        for row in raw.get("scores") or []:
            if isinstance(row, dict) and str(row.get("name") or "").strip():
                scores.append({
                    "name": str(row["name"]).strip(),
                    "score": str(row.get("score") or "").strip(),
                })
        return TrainingRecordParseOutput(
            doc_type=doc_type,
            attendance_count=_coerce_count(raw.get("attendance_count")),
            names=_str_list(raw.get("names")),
            passed_count=_coerce_count(raw.get("passed_count")),
            scores=scores,
            confidence=confidence,
            unrecognized=_str_list(raw.get("unrecognized")),
            notes=str(raw.get("notes") or "").strip(),
        )


def _coerce_count(value: Any) -> int | None:
    """计数列宽松转换（数字/数字串→int；null/无效→None 不推算）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


__all__ = [
    "TrainingRecordParsingError",
    "TrainingRecordParsingPlugin",
]
