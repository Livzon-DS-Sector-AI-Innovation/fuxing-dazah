"""脚本7 PostMeasureAssessor — 措施后风险 LEC 评价 Plugin。

评价「现有措施 + 已采纳建议措施」共同作用后的最终风险。
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
from app.modules.safety.ai_hazard_identification.script7_post_risk.prompts import (
    EXPECTED_KEYS,
    SYSTEM_ROLE,
    build_prompt,
)
from app.modules.safety.ai_hazard_identification.script7_post_risk.rules import (
    PostRiskRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script7_post_risk.schemas import (
    PostRiskInput,
    PostRiskOutput,
)

logger = logging.getLogger(__name__)


class PostMeasureAssessor(BasePlugin[PostRiskInput, PostRiskOutput]):
    """脚本7: 措施后风险 LEC 评价 Plugin。

    评价建议措施全部落地后的最终风险：
    - 不得假设不可执行的措施已落地
    - 下降幅度与措施类型匹配
    - PPE 和应急不能替代工程/管理控制的核心作用
    """

    def __init__(
        self,
        ai_service: Any,
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
    ):
        super().__init__(ai_service, config, knowledge_context)
        self.rule_engine = PostRiskRuleEngine()

    def _get_system_role(self) -> str:
        return SYSTEM_ROLE

    def _build_prompt(
        self, input_data: PostRiskInput, context_text: str,
    ) -> str:
        return build_prompt(context_text, self.knowledge_context)

    def _get_expected_keys(self) -> list[str]:
        return EXPECTED_KEYS

    def _parse_output(self, raw: dict) -> PostRiskOutput:
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
            return PostRiskOutput(lec=lec)
        except (PydanticValidationError, KeyError, TypeError) as e:
            raise PluginError(
                f"[PostMeasureAssessor] AI 输出解析失败: {e}"
            ) from e

    def _validate(
        self, input_data: PostRiskInput, output: PostRiskOutput,
    ) -> list[str]:
        return self.rule_engine.validate(input_data, output)

    def _auto_correct(self, output: PostRiskOutput) -> PostRiskOutput:
        return auto_correct(output)
