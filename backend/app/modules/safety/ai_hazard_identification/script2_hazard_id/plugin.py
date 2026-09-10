"""脚本2 HazardIdentifier — AI 危险源辨识 Plugin。

对标 AIHazardIdentifier 的 4-phase pipeline，从人机料法环五维度辨识危险源。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from app.modules.safety.ai_hazard_identification._base import (
    BasePlugin,
    PluginError,
)
from app.modules.safety.ai_hazard_identification.schemas import PluginConfig
from app.modules.safety.ai_hazard_identification.script2_hazard_id.prompts import (
    EXPECTED_KEYS,
    SYSTEM_ROLE,
    build_prompt,
)
from app.modules.safety.ai_hazard_identification.script2_hazard_id.rules import (
    HazardIdRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script2_hazard_id.schemas import (
    HazardIdInput,
    HazardIdOutput,
)

logger = logging.getLogger(__name__)


def _coerce_str(value: Any, default: str) -> str:
    """AI 返回值 → 字符串：list（多选）按「、」拼接，其余原样。

    Bitable「危险类型（AI）」为多选字段，AI 可能直接返回 list，
    此处统一拼成「、」连接的字符串，与规则引擎和回写逻辑对齐。
    """
    if isinstance(value, list):
        joined = "、".join(str(v) for v in value if str(v).strip())
        return joined if joined else default
    if value is None:
        return default
    return str(value)


class HazardIdentifier(BasePlugin[HazardIdInput, HazardIdOutput]):
    """脚本2: AI 危险源辨识 Plugin。

    从人机料法环五维度系统辨识：
    - hazard_type: 危险类型（Bitable 预设 24 项多选，1~5 个）
    - possible_accident: 可能导致的最典型事故
    - unsafe_behavior: 人的不规范作业行为
    """

    def __init__(
        self,
        ai_service: Any,
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
    ):
        super().__init__(ai_service, config, knowledge_context)
        self.rule_engine = HazardIdRuleEngine()

    def _get_system_role(self) -> str:
        return SYSTEM_ROLE

    def _build_prompt(
        self, input_data: HazardIdInput, context_text: str,
    ) -> str:
        return build_prompt(context_text, self.knowledge_context)

    def _get_expected_keys(self) -> list[str]:
        return EXPECTED_KEYS

    def _parse_output(self, raw: dict) -> HazardIdOutput:
        try:
            return HazardIdOutput(
                hazard_type=_coerce_str(raw.get("hazard_type"), "待人工确认"),
                possible_accident=_coerce_str(
                    raw.get("possible_accident"), "待人工确认"
                ),
                unsafe_behavior=_coerce_str(
                    raw.get("unsafe_behavior"), "待人工确认"
                ),
            )
        except (PydanticValidationError, KeyError, TypeError) as e:
            raise PluginError(
                f"[HazardIdentifier] AI 输出解析失败: {e}"
            ) from e

    def _validate(
        self, input_data: HazardIdInput, output: HazardIdOutput,
    ) -> list[str]:
        return self.rule_engine.validate(input_data, output)

    def _auto_correct(self, output: HazardIdOutput) -> HazardIdOutput:
        return auto_correct(output)
