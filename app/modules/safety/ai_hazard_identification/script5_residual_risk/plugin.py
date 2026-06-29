"""脚本5 ResidualRiskAssessor — 残余风险 LEC 评价 Plugin。

评价「现有控制措施全部纳入考虑后」的残余风险（保守原则为核心）。
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
from app.modules.safety.ai_hazard_identification.script3_inherent_risk.schemas import (
    LECOutput,
)
from app.modules.safety.ai_hazard_identification.script5_residual_risk.prompts import (
    EXPECTED_KEYS,
    SYSTEM_ROLE,
    build_prompt,
)
from app.modules.safety.ai_hazard_identification.script5_residual_risk.rules import (
    ResidualRiskRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script5_residual_risk.schemas import (
    ResidualRiskInput,
    ResidualRiskOutput,
)

logger = logging.getLogger(__name__)


class ResidualRiskAssessor(BasePlugin[ResidualRiskInput, ResidualRiskOutput]):
    """脚本5: 残余风险 LEC 评价 Plugin。

    评价现有控制措施全部纳入后的残余风险：
    - 保守原则：不得无依据降低风险
    - PPE 不替代工程控制和管理控制
    - 应急措施不能大幅降低 L
    """

    def __init__(
        self,
        ai_service: Any,
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
    ):
        super().__init__(ai_service, config, knowledge_context)
        self.rule_engine = ResidualRiskRuleEngine()

    def _get_system_role(self) -> str:
        return SYSTEM_ROLE

    def _build_prompt(
        self, input_data: ResidualRiskInput, context_text: str,
    ) -> str:
        return build_prompt(context_text, self.knowledge_context)

    def _get_expected_keys(self) -> list[str]:
        return EXPECTED_KEYS

    def _parse_output(self, raw: dict) -> ResidualRiskOutput:
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
            return ResidualRiskOutput(lec=lec)
        except (PydanticValidationError, KeyError, TypeError) as e:
            raise PluginError(
                f"[ResidualRiskAssessor] AI 输出解析失败: {e}"
            ) from e

    def _validate(
        self, input_data: ResidualRiskInput, output: ResidualRiskOutput,
    ) -> list[str]:
        return self.rule_engine.validate(input_data, output)

    def _auto_correct(self, output: ResidualRiskOutput) -> ResidualRiskOutput:
        return auto_correct(output)
