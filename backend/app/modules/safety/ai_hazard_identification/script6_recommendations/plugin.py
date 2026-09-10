"""脚本6 RecommendationGenerator — 建议措施生成 Plugin。

按控制层级原则（Hierarchy of Controls）提出改进建议。
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
from app.modules.safety.ai_hazard_identification.script6_recommendations.prompts import (
    EXPECTED_KEYS,
    SYSTEM_ROLE,
    build_prompt,
)
from app.modules.safety.ai_hazard_identification.script6_recommendations.rules import (
    RecommendationRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script6_recommendations.schemas import (
    RecommendationInput,
    RecommendationOutput,
)

logger = logging.getLogger(__name__)


def _coerce_str(value: Any, default: str) -> str:
    """AI 返回值 → 字符串：list（多选）按「、」拼接，其余原样。

    Bitable「建议措施类型（AI）」为多选字段，AI 可能直接返回 list，
    此处统一拼成「、」连接的字符串，与规则引擎和回写逻辑对齐。
    """
    if isinstance(value, list):
        joined = "、".join(str(v) for v in value if str(v).strip())
        return joined if joined else default
    if value is None:
        return default
    return str(value)


class RecommendationGenerator(BasePlugin[RecommendationInput, RecommendationOutput]):
    """脚本6: 建议措施生成 Plugin。

    根据残余风险等级和控制层级原则：
    - needs_recommendation: 是否需要建议
    - recommendation_type: 措施类型
    - recommendation_content: 具体可执行措施
    - recommendation_priority: 优先级
    """

    def __init__(
        self,
        ai_service: Any,
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
    ):
        super().__init__(ai_service, config, knowledge_context)
        self.rule_engine = RecommendationRuleEngine()

    def _get_system_role(self) -> str:
        return SYSTEM_ROLE

    def _build_prompt(
        self, input_data: RecommendationInput, context_text: str,
    ) -> str:
        return build_prompt(context_text, self.knowledge_context)

    def _get_expected_keys(self) -> list[str]:
        return EXPECTED_KEYS

    def _parse_output(self, raw: dict) -> RecommendationOutput:
        try:
            return RecommendationOutput(
                needs_recommendation=_coerce_str(
                    raw.get("needs_recommendation"), "是"
                ),
                recommendation_type=_coerce_str(
                    raw.get("recommendation_type"), "综合"
                ),
                recommendation_content=_coerce_str(
                    raw.get("recommendation_content"), "待人工确认"
                ),
                recommendation_priority=_coerce_str(
                    raw.get("recommendation_priority"), "中"
                ),
            )
        except (PydanticValidationError, KeyError, TypeError) as e:
            raise PluginError(
                f"[RecommendationGenerator] AI 输出解析失败: {e}"
            ) from e

    def _validate(
        self, input_data: RecommendationInput, output: RecommendationOutput,
    ) -> list[str]:
        return self.rule_engine.validate(input_data, output)

    def _auto_correct(self, output: RecommendationOutput) -> RecommendationOutput:
        return auto_correct(output)
