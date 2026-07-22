"""脚本3 InherentRiskAssessor — LEC 固有风险评价 Plugin。

LEC 法评价「未考虑任何现有控制措施前」的固有风险。
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
from app.modules.safety.ai_hazard_identification.script3_inherent_risk.prompts import (
    EXPECTED_KEYS,
    SYSTEM_ROLE,
    build_prompt,
)
from app.modules.safety.ai_hazard_identification.script3_inherent_risk.rules import (
    InherentRiskRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script3_inherent_risk.schemas import (
    InherentRiskInput,
    InherentRiskOutput,
    LECOutput,
)

logger = logging.getLogger(__name__)


class InherentRiskAssessor(BasePlugin[InherentRiskInput, InherentRiskOutput]):
    """脚本3: LEC 固有风险评价 Plugin。

    评价「未考虑任何现有控制措施前」的固有风险：
    - L（可能性 0.1~10）
    - E（暴露频率 0.5~10）
    - C（严重性 1~100）
    - D = L×E×C → risk_level（1-4级）
    """

    def __init__(
        self,
        ai_service: Any,
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
    ):
        super().__init__(ai_service, config, knowledge_context)
        self.rule_engine = InherentRiskRuleEngine()

    def _get_system_role(self) -> str:
        return SYSTEM_ROLE

    def _build_prompt(
        self, input_data: InherentRiskInput, context_text: str,
    ) -> str:
        return build_prompt(context_text, self.knowledge_context)

    def _get_expected_keys(self) -> list[str]:
        return EXPECTED_KEYS

    def _parse_output(self, raw: dict) -> InherentRiskOutput:
        try:
            lec_raw = raw.get("lec", {})
            if not isinstance(lec_raw, dict):
                lec_raw = {}

            lec = LECOutput(
                l_value=lec_raw.get("l_value"),
                e_value=lec_raw.get("e_value"),
                c_value=lec_raw.get("c_value"),
                d_value=lec_raw.get("d_value"),
                risk_level=lec_raw.get("risk_level"),
                risk_label=lec_raw.get("risk_label"),
            )
            return InherentRiskOutput(lec=lec)
        except (PydanticValidationError, KeyError, TypeError) as e:
            raise PluginError(
                f"[InherentRiskAssessor] AI 输出解析失败: {e}"
            ) from e

    def _validate(
        self, input_data: InherentRiskInput, output: InherentRiskOutput,
    ) -> list[str]:
        return self.rule_engine.validate(input_data, output)

    def _auto_correct(self, output: InherentRiskOutput) -> InherentRiskOutput:
        return auto_correct(output)
