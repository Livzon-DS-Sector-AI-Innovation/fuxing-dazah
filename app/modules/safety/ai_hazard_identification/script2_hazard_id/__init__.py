"""脚本2 HazardIdentifier — AI危险源辨识模块。"""

from app.modules.safety.ai_hazard_identification.script2_hazard_id.plugin import (
    HazardIdentifier,
)
from app.modules.safety.ai_hazard_identification.script2_hazard_id.prompts import (
    VALID_HAZARD_TYPES_6441,
    get_db_seed_config,
)
from app.modules.safety.ai_hazard_identification.script2_hazard_id.rules import (
    HazardIdRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script2_hazard_id.schemas import (
    HazardIdInput,
    HazardIdOutput,
)

__all__ = [
    "HazardIdentifier",
    "HazardIdInput",
    "HazardIdOutput",
    "HazardIdRuleEngine",
    "auto_correct",
    "VALID_HAZARD_TYPES_6441",
    "get_db_seed_config",
]
