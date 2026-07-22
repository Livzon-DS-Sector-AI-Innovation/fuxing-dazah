"""脚本4 ControlMeasureExtractor — 现有控制措施识别 Plugin。

识别当前已存在的四维度控制措施（工程/管理/PPE/应急）。
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
from app.modules.safety.ai_hazard_identification.script4_controls.prompts import (
    EXPECTED_KEYS,
    SYSTEM_ROLE,
    build_prompt,
)
from app.modules.safety.ai_hazard_identification.script4_controls.rules import (
    ControlsRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script4_controls.schemas import (
    ControlsInput,
    ControlsOutput,
)

logger = logging.getLogger(__name__)


class ControlMeasureExtractor(BasePlugin[ControlsInput, ControlsOutput]):
    """脚本4: 现有控制措施识别 Plugin。

    识别四维度控制措施：
    - engineering_controls: 工程控制
    - management_controls: 管理控制
    - ppe: 个人防护
    - emergency_measures: 应急措施
    """

    def __init__(
        self,
        ai_service: Any,
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
    ):
        super().__init__(ai_service, config, knowledge_context)
        self.rule_engine = ControlsRuleEngine()

    def _get_system_role(self) -> str:
        return SYSTEM_ROLE

    def _build_prompt(
        self, input_data: ControlsInput, context_text: str,
    ) -> str:
        return build_prompt(context_text, self.knowledge_context)

    def _get_expected_keys(self) -> list[str]:
        return EXPECTED_KEYS

    def _parse_output(self, raw: dict) -> ControlsOutput:
        try:
            return ControlsOutput(
                engineering_controls=raw.get("engineering_controls", "待人工确认"),
                management_controls=raw.get("management_controls", "待人工确认"),
                ppe=raw.get("ppe", "待人工确认"),
                emergency_measures=raw.get("emergency_measures", "待人工确认"),
            )
        except (PydanticValidationError, KeyError, TypeError) as e:
            raise PluginError(
                f"[ControlMeasureExtractor] AI 输出解析失败: {e}"
            ) from e

    def _validate(
        self, input_data: ControlsInput, output: ControlsOutput,
    ) -> list[str]:
        return self.rule_engine.validate(input_data, output)

    def _auto_correct(self, output: ControlsOutput) -> ControlsOutput:
        return auto_correct(output)
