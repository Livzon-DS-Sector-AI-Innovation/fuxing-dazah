"""脚本3.5 FujianRiskAssessor — 福建固有风险评级模块。"""

from app.modules.safety.ai_hazard_identification.script3_5_fujian_risk.plugin import (
    FujianRiskAssessor,
)
from app.modules.safety.ai_hazard_identification.script3_5_fujian_risk.prompts import (
    EXPECTED_KEYS,
    OUTPUT_FORMAT,
    SYSTEM_ROLE,
    WORK_RULES,
    build_prompt,
    get_db_seed_config,
)
from app.modules.safety.ai_hazard_identification.script3_5_fujian_risk.rules import (
    FujianRiskRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script3_5_fujian_risk.schemas import (
    FUJIAN_DEFAULT_BLUE_FIELDS,
    FUJIAN_INDICATOR_FIELDS,
    FUJIAN_RISK_LABELS,
    FujianRiskInput,
    FujianRiskOutput,
)

__all__ = [
    "FujianRiskAssessor",
    "FujianRiskInput",
    "FujianRiskOutput",
    "FujianRiskRuleEngine",
    "auto_correct",
    "FUJIAN_RISK_LABELS",
    "FUJIAN_INDICATOR_FIELDS",
    "FUJIAN_DEFAULT_BLUE_FIELDS",
    "get_db_seed_config",
    "build_prompt",
    "SYSTEM_ROLE",
    "WORK_RULES",
    "OUTPUT_FORMAT",
    "EXPECTED_KEYS",
]
