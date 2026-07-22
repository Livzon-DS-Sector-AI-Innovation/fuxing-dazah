"""脚本6 RecommendationGenerator — 建议措施生成模块。"""

from app.modules.safety.ai_hazard_identification.script6_recommendations.plugin import (
    RecommendationGenerator,
)
from app.modules.safety.ai_hazard_identification.script6_recommendations.prompts import (
    get_db_seed_config,
)
from app.modules.safety.ai_hazard_identification.script6_recommendations.rules import (
    RecommendationRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script6_recommendations.schemas import (
    RecommendationInput,
    RecommendationOutput,
)

__all__ = [
    "RecommendationGenerator",
    "RecommendationInput",
    "RecommendationOutput",
    "RecommendationRuleEngine",
    "auto_correct",
    "get_db_seed_config",
]
