"""URS 智能审核编排器 — 桥接 Service 层与四步 Plugin。

用法::

    orch = URSReviewOrchestrator(ai_service)
    profile = await orch.assess_risk(RiskProfileInput(...))
    adapted = await orch.adapt_standards(StandardAdaptationInput(...))
    verdicts = await orch.review_items(ItemReviewInput(...))
    conclusion = await orch.generate_conclusion(ConclusionInput(...))
"""

import logging
from typing import Any

from app.modules.safety.ai_urs_review.plugin import (
    ConclusionGenerator,
    ItemReviewer,
    RiskProfileAssessor,
    StandardAdapter,
)
from app.modules.safety.ai_urs_review.schemas import (
    ConclusionInput,
    ConclusionOutput,
    ItemReviewInput,
    ItemReviewOutput,
    RiskProfileInput,
    RiskProfileOutput,
    StandardAdaptationInput,
    StandardAdaptationOutput,
)

logger = logging.getLogger(__name__)


class URSReviewOrchestrator:
    """四步 AI 流水线编排入口。"""

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def assess_risk(self, inp: RiskProfileInput) -> RiskProfileOutput:
        """Step1 — 五维风险画像。"""
        return await RiskProfileAssessor(self.ai_service).run(inp)

    async def adapt_standards(self, inp: StandardAdaptationInput) -> StandardAdaptationOutput:
        """Step2 — 标准适配（否决项代码强制）。"""
        return await StandardAdapter(self.ai_service).run(inp)

    async def review_items(self, inp: ItemReviewInput) -> ItemReviewOutput:
        """Step3 — 逐条审核（AI 预填）。"""
        return await ItemReviewer(self.ai_service).run(inp)

    async def generate_conclusion(self, inp: ConclusionInput) -> ConclusionOutput:
        """Step4 — 结论生成（评分/结论代码计算）。"""
        return await ConclusionGenerator(self.ai_service).run(inp)
