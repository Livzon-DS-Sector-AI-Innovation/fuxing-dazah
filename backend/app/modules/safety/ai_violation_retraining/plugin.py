"""AI 违章定向培训要点卡插件 — 核心引擎。

用法:
    from app.modules.safety.ai_violation_retraining import ViolationRetrainingPlugin

    plugin = ViolationRetrainingPlugin(ai_service)  # create_ai_service("text")
    output = await plugin.generate(ViolationRetrainingInput(...))

场景键：violation_retraining_generation（ai_config/scenario_registry 注册）。
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.safety.ai_violation_retraining.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.modules.safety.ai_violation_retraining.schemas import (
    ViolationRetrainingInput,
    ViolationRetrainingOutput,
)

logger = logging.getLogger(__name__)

_EXPECTED_KEYS = ["summary", "key_points"]


class ViolationRetrainingError(Exception):
    """要点卡生成失败（AI 调用或输出解析）。"""


class ViolationRetrainingPlugin:
    """违章 → 定向培训要点卡。

    Args:
        ai_service: AuditedAIService 实例（create_ai_service("text") 返回）
    """

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def generate(
        self, input_data: ViolationRetrainingInput
    ) -> ViolationRetrainingOutput:
        prompt = build_user_prompt(
            description=input_data.description,
            category=input_data.category,
            level=input_data.level,
            handling=input_data.handling,
            department=input_data.department,
            person_name=input_data.person_name,
            hazard_no=input_data.hazard_no,
            position_hints=input_data.position_hints,
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
            logger.error("违章定向培训要点卡 AI 调用失败: %s", e)
            raise ViolationRetrainingError(f"AI 调用失败: {e}") from e
        return self._parse_output(raw)

    @staticmethod
    def _parse_output(raw: Any) -> ViolationRetrainingOutput:
        if not isinstance(raw, dict):
            raise ViolationRetrainingError(f"AI 输出非 dict: {type(raw).__name__}")
        points_raw = raw.get("key_points") or []
        if isinstance(points_raw, str):
            points_raw = [points_raw]
        points = [str(p).strip() for p in points_raw if str(p).strip()]
        summary = str(raw.get("summary") or "").strip()
        if not summary or not points:
            raise ViolationRetrainingError("AI 输出缺 summary/key_points")
        return ViolationRetrainingOutput(summary=summary, key_points=points)
