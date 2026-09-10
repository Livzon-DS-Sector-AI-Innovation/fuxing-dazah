"""AI 演练评估表插件包 — 对外导出。

用法:
    from app.modules.safety.ai_drill_eval import DrillEvalPlugin

    plugin = DrillEvalPlugin(ai_service)
    output = await plugin.review(input_data)
"""

from app.modules.safety.ai_drill_eval.plugin import DrillEvalError, DrillEvalPlugin
from app.modules.safety.ai_drill_eval.schemas import (
    DrillEvalInput,
    DrillEvalItem,
    DrillEvalOutput,
)

__all__ = [
    "DrillEvalError",
    "DrillEvalInput",
    "DrillEvalItem",
    "DrillEvalOutput",
    "DrillEvalPlugin",
]
