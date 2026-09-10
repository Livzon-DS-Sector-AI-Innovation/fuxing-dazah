"""脚本8 InspectionItemGenerator — 排查内容生成 Plugin。

根据 4 类现有控制措施（人工），生成 4 类现场排查检查项（AI）。
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
from app.modules.safety.ai_hazard_identification.script8_inspection_items.prompts import (
    EXPECTED_KEYS,
    SYSTEM_ROLE,
    build_prompt,
)
from app.modules.safety.ai_hazard_identification.script8_inspection_items.rules import (
    UNCONFIRMED,
    InspectionRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script8_inspection_items.schemas import (
    InspectionItemsInput,
    InspectionItemsOutput,
)

logger = logging.getLogger(__name__)


class InspectionItemGenerator(BasePlugin[InspectionItemsInput, InspectionItemsOutput]):
    """脚本8: 排查内容生成 Plugin。

    输入 4 类现有控制措施（人工）→ 输出 4 类现场排查检查项（AI）。
    空输入字段在自动修正阶段落为「无」，不调用 AI 兜底。
    """

    def __init__(
        self,
        ai_service: Any,
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
    ):
        super().__init__(ai_service, config, knowledge_context)
        self.rule_engine = InspectionRuleEngine()
        self._current_input: InspectionItemsInput | None = None

    async def _preprocess(self, input_data: InspectionItemsInput) -> None:
        # 记录输入，供 auto_correct 落实「空输入→无」规则
        self._current_input = input_data

    def _get_system_role(self) -> str:
        return SYSTEM_ROLE

    def _build_prompt(
        self, input_data: InspectionItemsInput, context_text: str,
    ) -> str:
        return build_prompt(context_text, self.knowledge_context)

    def _get_expected_keys(self) -> list[str]:
        return EXPECTED_KEYS

    def _parse_output(self, raw: dict) -> InspectionItemsOutput:
        try:
            return InspectionItemsOutput(
                engineering_items=raw.get("engineering_items", UNCONFIRMED),
                management_items=raw.get("management_items", UNCONFIRMED),
                ppe_items=raw.get("ppe_items", UNCONFIRMED),
                emergency_items=raw.get("emergency_items", UNCONFIRMED),
            )
        except (PydanticValidationError, KeyError, TypeError) as e:
            raise PluginError(
                f"[InspectionItemGenerator] AI 输出解析失败: {e}"
            ) from e

    def _validate(
        self, input_data: InspectionItemsInput, output: InspectionItemsOutput,
    ) -> list[str]:
        return self.rule_engine.validate(input_data, output)

    def _auto_correct(self, output: InspectionItemsOutput) -> InspectionItemsOutput:
        return auto_correct(output, self._current_input or _EMPTY_INPUT)


_EMPTY_INPUT = InspectionItemsInput(
    engineering_controls="", management_controls="", ppe="", emergency_measures="",
)
