"""脚本3 InherentRiskAssessor — LEC固有风险评价模块。"""

from app.modules.safety.ai_hazard_identification.script3_inherent_risk.plugin import (
    InherentRiskAssessor,
)
from app.modules.safety.ai_hazard_identification.script3_inherent_risk.prompts import (
    get_db_seed_config,
)
from app.modules.safety.ai_hazard_identification.script3_inherent_risk.rules import (
    InherentRiskRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script3_inherent_risk.schemas import (
    LEC_SCORING_GUIDE,
    RISK_LEVEL_TABLE,
    VALID_C_VALUES,
    VALID_E_VALUES,
    VALID_L_VALUES,
    InherentRiskInput,
    InherentRiskOutput,
    LECOutput,
)

__all__ = [
    "InherentRiskAssessor",
    "LECOutput",
    "InherentRiskInput",
    "InherentRiskOutput",
    "InherentRiskRuleEngine",
    "auto_correct",
    "LEC_SCORING_GUIDE",
    "RISK_LEVEL_TABLE",
    "VALID_L_VALUES",
    "VALID_E_VALUES",
    "VALID_C_VALUES",
    "get_db_seed_config",
]
