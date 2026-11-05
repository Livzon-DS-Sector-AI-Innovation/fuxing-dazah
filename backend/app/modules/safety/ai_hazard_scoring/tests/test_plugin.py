"""AI隐患评分插件 — mock AIService 接缝测试。

运行: uv run pytest app/modules/safety/ai_hazard_scoring/tests/ -v
"""

from __future__ import annotations

import pytest

from app.modules.safety.ai_hazard_scoring.prompts import (
    build_context_text,
    build_full_prompt,
    get_expected_keys,
)
from app.modules.safety.ai_hazard_scoring.rules import ScoringError
from app.modules.safety.ai_hazard_scoring.schemas import (
    HazardScoringInput,
    PluginConfig,
)
from app.modules.safety.ai_hazard_scoring.plugin import AIHazardScorer

from .test_rules import VALID_RAW


class MockAIService:
    """模拟带 chat_parsed 的 AI 服务（同款接缝：chat_parsed(messages, expected_keys, temperature)。"""

    def __init__(self, return_dict: dict | None = None, should_fail: bool = False):
        self.return_dict = return_dict if return_dict is not None else dict(VALID_RAW)
        self.should_fail = should_fail
        self.calls: list[dict] = []

    async def chat_parsed(self, *, messages, expected_keys, temperature, **kwargs):
        self.calls.append(
            {
                "messages": messages,
                "expected_keys": expected_keys,
                "temperature": temperature,
            }
        )
        if self.should_fail:
            raise RuntimeError("AI 接口超时")
        return dict(self.return_dict)


def make_input() -> HazardScoringInput:
    return HazardScoringInput(
        hazard_no="HZ-20261105-001",
        description="3号罐区静电跨接断裂，卸车作业时存在静电放电风险",
        key_defect="罐区静电跨接装置断裂缺失",
        hazard_type="unsafe_condition",
        hazard_category="lightning_antistatic",
        hazard_level="general",
        major_hazard_basis="GB 12158 静电事故通用导则",
        department="储运部",
        inspection_category="周检",
    )


# ═══════════════════════════════════════════════════════════════════════════
# prompts
# ═══════════════════════════════════════════════════════════════════════════


class TestPrompts:
    def test_expected_keys_cover_contract(self):
        keys = get_expected_keys()
        assert keys == [
            "likelihood", "likelihood_reason",
            "exposure", "exposure_reason",
            "consequence", "consequence_reason",
            "difficulty", "difficulty_reason",
            "band", "band_basis",
            "major_hazard", "summary",
        ]

    def test_full_prompt_contains_tier_table_and_mapping(self):
        prompt = build_full_prompt(build_context_text(make_input()))
        # 制度 17 档全量锚定 + 13 类别对照 + 重大判定条目索引
        for anchor in ("非常可能", "很少接触", "灾难", "0.99", "附件一", "AQ 3067"):
            assert anchor in prompt
        # 输入上下文带入
        assert "HZ-20261105-001" in prompt
        assert "静电跨接断裂" in prompt

    def test_context_text_has_no_reporter_identity(self):
        ctx = build_context_text(make_input())
        # 评分主体=隐患本身：上下文不含上报人姓名/检查人员字样
        assert "检查人员" not in ctx
        assert "上报人" not in ctx

    def test_long_description_truncated(self):
        inp = make_input()
        inp.description = "超长描述" * 500  # 2000 字
        ctx = build_context_text(inp)
        assert len(ctx) < 4000
        assert "已截断" in ctx


# ═══════════════════════════════════════════════════════════════════════════
# plugin
# ═══════════════════════════════════════════════════════════════════════════


class TestAIHazardScorer:
    async def test_score_returns_typed_output(self):
        service = MockAIService()
        scorer = AIHazardScorer(service)
        out = await scorer.score(make_input())
        assert out.likelihood.value == "1.5"
        assert out.band.value == "H"
        assert out.major_hazard.hit is False

    async def test_score_passes_contract(self):
        service = MockAIService()
        scorer = AIHazardScorer(service, PluginConfig(temperature=0.05))
        await scorer.score(make_input())
        assert len(service.calls) == 1
        call = service.calls[0]
        assert call["temperature"] == 0.05
        assert call["expected_keys"] == get_expected_keys()
        assert len(call["messages"]) == 2
        assert call["messages"][0]["role"] == "system"
        assert call["messages"][1]["role"] == "user"

    async def test_invalid_output_raises_scoring_error(self):
        service = MockAIService(return_dict=dict(VALID_RAW, likelihood="极有可能"))
        scorer = AIHazardScorer(service)
        with pytest.raises(ScoringError):
            await scorer.score(make_input())

    async def test_ai_failure_wrapped_as_scoring_error(self):
        service = MockAIService(should_fail=True)
        scorer = AIHazardScorer(service)
        with pytest.raises(ScoringError):
            await scorer.score(make_input())
