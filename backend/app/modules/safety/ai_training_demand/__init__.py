"""AI 年度培训需求生成插件（链1）。

对外：TrainingDemandPlugin / TrainingDemandInput / TrainingDemandOutput /
TrainingDemandError。
"""

from app.modules.safety.ai_training_demand.plugin import (
    TrainingDemandError,
    TrainingDemandPlugin,
)
from app.modules.safety.ai_training_demand.schemas import (
    TrainingDemandInput,
    TrainingDemandItem,
    TrainingDemandOutput,
)

__all__ = [
    "TrainingDemandError",
    "TrainingDemandPlugin",
    "TrainingDemandInput",
    "TrainingDemandItem",
    "TrainingDemandOutput",
]
