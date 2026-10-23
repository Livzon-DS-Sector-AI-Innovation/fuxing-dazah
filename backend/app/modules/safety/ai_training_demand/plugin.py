"""AI 年度培训需求生成插件 — 核心引擎（链1）。

用法:
    from app.modules.safety.ai_training_demand import TrainingDemandPlugin

    plugin = TrainingDemandPlugin(ai_service)  # create_ai_service("text")
    output = await plugin.generate(TrainingDemandInput(...))

场景键：training_demand_generation（ai_config/scenario_registry 注册）。
产物是草案：先落 PG 草案表供评审，采纳后才写 Bitable 培训表。
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.safety.ai_training_demand.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.modules.safety.ai_training_demand.schemas import (
    TrainingDemandInput,
    TrainingDemandItem,
    TrainingDemandOutput,
)

logger = logging.getLogger(__name__)

_EXPECTED_KEYS = ["summary", "demands", "statutory_notes"]


class TrainingDemandError(Exception):
    """需求草案生成失败（AI 调用或输出解析）。"""


class TrainingDemandPlugin:
    """五源汇报文本 → 年度培训需求清单草案。

    Args:
        ai_service: AuditedAIService 实例（create_ai_service("text") 返回）
    """

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def generate(
        self, input_data: TrainingDemandInput
    ) -> TrainingDemandOutput:
        prompt = build_user_prompt(
            hazard_id_digest=input_data.hazard_id_digest,
            hazard_stats=input_data.hazard_stats,
            violation_stats=input_data.violation_stats,
            regulation_list=input_data.regulation_list,
            last_year_summary=input_data.last_year_summary,
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = await self.ai_service.chat_parsed(
                messages=messages,
                expected_keys=_EXPECTED_KEYS,
                temperature=0.2,
            )
        except Exception as e:
            logger.error("年度培训需求生成 AI 调用失败: %s", e)
            raise TrainingDemandError(f"AI 调用失败: {e}") from e
        return self._parse_output(raw)

    @staticmethod
    def _parse_output(raw: Any) -> TrainingDemandOutput:
        if not isinstance(raw, dict):
            raise TrainingDemandError(f"AI 输出非 dict: {type(raw).__name__}")
        demands_raw = raw.get("demands") or []
        if not isinstance(demands_raw, list):
            raise TrainingDemandError("AI 输出 demands 非数组")
        items: list[TrainingDemandItem] = []
        for row in demands_raw:
            if not isinstance(row, dict):
                continue
            topic = str(row.get("topic") or "").strip()
            if not topic:
                continue  # 无主题行不可采纳，丢弃
            items.append(TrainingDemandItem(
                position=str(row.get("position") or "").strip(),
                topic=topic,
                suggested_hours=_coerce_hours(row.get("suggested_hours")),
                form=(str(row.get("form")).strip()
                      if row.get("form") is not None else None) or None,
                audience=str(row.get("audience") or "").strip(),
                basis=str(row.get("basis") or "").strip(),
                is_statutory_gap=_coerce_bool(row.get("is_statutory_gap")),
            ))
        if not items:
            raise TrainingDemandError("AI 输出无有效需求行")
        notes_raw = raw.get("statutory_notes") or []
        if isinstance(notes_raw, str):
            notes_raw = [notes_raw]
        return TrainingDemandOutput(
            summary=str(raw.get("summary") or "").strip(),
            demands=items,
            statutory_notes=[str(n).strip() for n in notes_raw if str(n).strip()],
        )


def _coerce_hours(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)
