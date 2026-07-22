"""脚本5 ResidualRiskAssessor — 残余风险LEC评价模块。"""

from app.modules.safety.ai_hazard_identification.script5_residual_risk.plugin import (
    ResidualRiskAssessor,
)
from app.modules.safety.ai_hazard_identification.script5_residual_risk.prompts import (
    get_db_seed_config,
)
from app.modules.safety.ai_hazard_identification.script5_residual_risk.rules import (
    ResidualRiskRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script5_residual_risk.schemas import (
    ResidualRiskInput,
    ResidualRiskOutput,
)

__all__ = [
    "ResidualRiskAssessor",
    "ResidualRiskInput",
    "ResidualRiskOutput",
    "ResidualRiskRuleEngine",
    "auto_correct",
    "get_db_seed_config",
]
