"""AI 违章定向培训要点卡插件（链5）。

对外：ViolationRetrainingPlugin / ViolationRetrainingInput /
ViolationRetrainingOutput / ViolationRetrainingError。
"""

from app.modules.safety.ai_violation_retraining.plugin import (
    ViolationRetrainingError,
    ViolationRetrainingPlugin,
)
from app.modules.safety.ai_violation_retraining.schemas import (
    ViolationRetrainingInput,
    ViolationRetrainingOutput,
)

__all__ = [
    "ViolationRetrainingError",
    "ViolationRetrainingPlugin",
    "ViolationRetrainingInput",
    "ViolationRetrainingOutput",
]
