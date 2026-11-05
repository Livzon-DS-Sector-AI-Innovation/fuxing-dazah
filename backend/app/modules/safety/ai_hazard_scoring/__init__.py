"""AI隐患评分（D=L×E×C×X，制度 SOPAQ01015-03 §10.3）。

模块出口：AIHazardScorer（插件）/ HazardScoringInput / HazardScoringOutput /
PluginConfig / ScoringError / rules（compute_total 等）。
接入方：service/hazard_direct/hazard_scoring.py（⑤轮）。
"""

from app.modules.safety.ai_hazard_scoring.plugin import AIHazardScorer
from app.modules.safety.ai_hazard_scoring.rules import ScoringError, compute_total
from app.modules.safety.ai_hazard_scoring.schemas import (
    HazardScoringInput,
    HazardScoringOutput,
    PluginConfig,
)

__all__ = [
    "AIHazardScorer",
    "HazardScoringInput",
    "HazardScoringOutput",
    "PluginConfig",
    "ScoringError",
    "compute_total",
]
