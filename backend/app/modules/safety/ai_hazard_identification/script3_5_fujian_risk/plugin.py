"""脚本3.5 FujianRiskAssessor — 福建固有风险评级 Plugin。

按福建省表5-1 七指标评价体系评估固有风险等级，
取七指标中最高等级为综合等级，输出中文等级名。
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
from app.modules.safety.ai_hazard_identification.script3_5_fujian_risk.prompts import (
    EXPECTED_KEYS,
    SYSTEM_ROLE,
    build_prompt,
)
from app.modules.safety.ai_hazard_identification.script3_5_fujian_risk.rules import (
    FujianRiskRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script3_5_fujian_risk.schemas import (
    FujianRiskInput,
    FujianRiskOutput,
)

logger = logging.getLogger(__name__)


class FujianRiskAssessor(BasePlugin[FujianRiskInput, FujianRiskOutput]):
    """脚本3.5: 福建固有风险评级 Plugin。

    按福建省表5-1 七指标评价体系评估固有风险：
    - 七指标：危险物质种类数量 G / 选址布局 / 周边环境 / 危险工艺与重点监管危化品 /
      操作压力 / 操作温度 / 班组人员密度
    - 综合等级 risk_label = 七指标非 null 项的最高等级（风险最大化原则）
    """

    def __init__(
        self,
        ai_service: Any,
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
    ):
        super().__init__(ai_service, config, knowledge_context)
        self.rule_engine = FujianRiskRuleEngine()

    def _get_system_role(self) -> str:
        return SYSTEM_ROLE

    def _build_prompt(
        self, input_data: FujianRiskInput, context_text: str,
    ) -> str:
        return build_prompt(context_text, self.knowledge_context)

    def _get_expected_keys(self) -> list[str]:
        return EXPECTED_KEYS

    def _parse_output(self, raw: dict) -> FujianRiskOutput:
        try:
            fj_raw = raw.get("fujian", {})
            if not isinstance(fj_raw, dict):
                fj_raw = {}

            return FujianRiskOutput(
                substance=fj_raw.get("substance"),
                layout=fj_raw.get("layout"),
                environment=fj_raw.get("environment"),
                process=fj_raw.get("process"),
                pressure=fj_raw.get("pressure"),
                temperature=fj_raw.get("temperature"),
                personnel_level=fj_raw.get("personnel_level"),
                risk_label=fj_raw.get("risk_label"),
                reasoning=fj_raw.get("reasoning"),
            )
        except (PydanticValidationError, KeyError, TypeError) as e:
            raise PluginError(
                f"[FujianRiskAssessor] AI 输出解析失败: {e}"
            ) from e

    def _validate(
        self, input_data: FujianRiskInput, output: FujianRiskOutput,
    ) -> list[str]:
        return self.rule_engine.validate(input_data, output)

    def _auto_correct(self, output: FujianRiskOutput) -> FujianRiskOutput:
        return auto_correct(output)
