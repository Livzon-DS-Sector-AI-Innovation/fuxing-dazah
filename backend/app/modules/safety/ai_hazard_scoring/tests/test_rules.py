"""AI隐患评分 rules — 纯函数测试（制度 SOPAQ01015-03 §10.3 档位表唯一权威）。

不依赖数据库、飞书或 FastAPI。
运行: uv run pytest app/modules/safety/ai_hazard_scoring/tests/ -v
"""

from __future__ import annotations

import pytest

from app.modules.safety.ai_hazard_scoring import rules
from app.modules.safety.ai_hazard_scoring.schemas import (
    ConsequenceTier,
    DifficultyTier,
    ExposureTier,
    HazardScoringOutput,
    LikelihoodTier,
    RiskBandEnum,
)

# ═══════════════════════════════════════════════════════════════════════════
# 制度档位表（§10.3 原文）——期望值的独立真值源
# ═══════════════════════════════════════════════════════════════════════════

EXPECTED_TIERS = {
    "likelihood": {"非常可能": 2.0, "可能": 1.5, "可能性小": 1.0},
    "exposure": {
        "连续接触": 2.0, "每天几次接触": 1.8, "每周接触": 1.6,
        "每月接触": 1.4, "每年接触": 1.2, "很少接触": 1.0,
    },
    "consequence": {"灾难": 25, "非常严重": 22, "严重": 20, "一般": 18, "轻微": 15},
    "difficulty": {"难": 1.0, "较难": 0.99, "一般": 0.98},
}


def _labels(dim: str) -> dict[str, float]:
    """中文档位 → 制度分值（经 rules 的公开映射表，不复制实现）。"""
    mapping = rules.TIER_LABELS[dim]
    return {label: float(member.value) for member, label in mapping.items()}


# ═══════════════════════════════════════════════════════════════════════════
# 档位映射
# ═══════════════════════════════════════════════════════════════════════════


class TestTierMaps:
    def test_17_tiers_match_regulation(self):
        for dim, expected in EXPECTED_TIERS.items():
            got = _labels(dim)
            assert got == pytest.approx(expected), f"{dim} 档位表与制度不符: {got}"

    def test_total_tier_count(self):
        assert sum(len(rules.TIER_LABELS[d]) for d in EXPECTED_TIERS) == 17

    def test_reverse_maps_cover_all_labels(self):
        for dim, mapping in rules.TIER_LABELS.items():
            for label in mapping.values():
                assert rules.LABEL_TO_TIER[dim][label] in [
                    m.value for m in mapping
                ]


# ═══════════════════════════════════════════════════════════════════════════
# 总分计算 D = L×E×C×X
# ═══════════════════════════════════════════════════════════════════════════


def make_output(
    likelihood=LikelihoodTier.LIKELY,
    exposure=ExposureTier.DAILY,
    consequence=ConsequenceTier.SEVERE,
    difficulty=DifficultyTier.NORMAL,
    band=RiskBandEnum.HIGH,
    **overrides,
) -> HazardScoringOutput:
    data = {
        "likelihood": likelihood,
        "likelihood_reason": "罐区卸车频繁，静电点火源现实存在",
        "exposure": exposure,
        "exposure_reason": "岗位每天数次巡检经过",
        "consequence": consequence,
        "consequence_reason": "可燃溶剂泄漏遇火源致火灾",
        "difficulty": difficulty,
        "difficulty_reason": "跨接断裂目视可见，日常巡检易发现",
        "band": band,
        "band_basis": "附件五·安全操作·静电控制M",
        "major_hazard": {"hit": False, "clauses": []},
        "summary": "罐区静电跨接断裂，接触频繁后果严重，建议立即整改。",
        **overrides,
    }
    return HazardScoringOutput(**data)


class TestComputeTotal:
    def test_min_boundary(self):
        out = make_output(
            likelihood=LikelihoodTier.UNLIKELY,
            exposure=ExposureTier.RARE,
            consequence=ConsequenceTier.MINOR,
            difficulty=DifficultyTier.NORMAL,
        )
        assert rules.compute_total(out) == pytest.approx(14.7)

    def test_max_boundary(self):
        out = make_output(
            likelihood=LikelihoodTier.VERY_LIKELY,
            exposure=ExposureTier.CONTINUOUS,
            consequence=ConsequenceTier.CATASTROPHE,
            difficulty=DifficultyTier.HARD,
        )
        assert rules.compute_total(out) == pytest.approx(100.0)

    def test_worked_example_rounds_to_1_decimal(self):
        # 制度示例组合：可能1.5 × 每天几次1.8 × 严重20 × 一般0.98 = 52.92 → 52.9
        out = make_output()  # 默认即该组合
        assert rules.compute_total(out) == pytest.approx(52.9)


# ═══════════════════════════════════════════════════════════════════════════
# band 一致性软校验
# ═══════════════════════════════════════════════════════════════════════════


class TestBandConsistency:
    def test_high_score_low_band_warns(self):
        out = make_output(band=RiskBandEnum.LOW)  # D=52.9
        assert rules.band_consistency(out, 52.9) is not None

    def test_low_score_high_band_warns(self):
        out = make_output(band=RiskBandEnum.HIGH)
        assert rules.band_consistency(out, 24.0) is not None

    def test_consistent_returns_none(self):
        out = make_output(band=RiskBandEnum.HIGH)  # D=52.9 ↔ H 合理
        assert rules.band_consistency(out, 52.9) is None
        mid = make_output(band=RiskBandEnum.MEDIUM)
        assert rules.band_consistency(mid, 30.0) is None


# ═══════════════════════════════════════════════════════════════════════════
# 输出校验（中文档位 → 枚举）
# ═══════════════════════════════════════════════════════════════════════════


VALID_RAW = {
    "likelihood": "可能",
    "likelihood_reason": "作业频繁且点火源现实存在",
    "exposure": "每天几次接触",
    "exposure_reason": "巡检路线必经",
    "consequence": "严重",
    "consequence_reason": "泄漏遇火源可致火灾",
    "difficulty": "一般",
    "difficulty_reason": "目视可见",
    "band": "H",
    "band_basis": "附件五·安全操作·静电控制M",
    "major_hazard": {"hit": False, "clauses": []},
    "summary": "静电跨接断裂，建议立即整改。",
}


class TestValidateOutput:
    def test_valid_chinese_labels(self):
        out = rules.validate_output(dict(VALID_RAW))
        assert out.likelihood is LikelihoodTier.LIKELY
        assert out.exposure is ExposureTier.DAILY
        assert out.consequence is ConsequenceTier.SEVERE
        assert out.difficulty is DifficultyTier.NORMAL
        assert out.band is RiskBandEnum.HIGH

    def test_band_accepts_chinese_alias(self):
        raw = dict(VALID_RAW, band="高")
        assert rules.validate_output(raw).band is RiskBandEnum.HIGH

    def test_invalid_likelihood_raises(self):
        raw = dict(VALID_RAW, likelihood="极有可能")
        with pytest.raises(rules.ScoringError):
            rules.validate_output(raw)

    def test_invalid_exposure_raises(self):
        raw = dict(VALID_RAW, exposure="每小时接触")
        with pytest.raises(rules.ScoringError):
            rules.validate_output(raw)

    def test_invalid_consequence_raises(self):
        raw = dict(VALID_RAW, consequence="特别严重")
        with pytest.raises(rules.ScoringError):
            rules.validate_output(raw)

    def test_invalid_difficulty_raises(self):
        raw = dict(VALID_RAW, difficulty="简单")
        with pytest.raises(rules.ScoringError):
            rules.validate_output(raw)

    def test_missing_dimension_raises(self):
        raw = {k: v for k, v in VALID_RAW.items() if k != "difficulty"}
        with pytest.raises(rules.ScoringError):
            rules.validate_output(raw)

    def test_major_hazard_hit_with_clauses(self):
        raw = dict(
            VALID_RAW,
            major_hazard={"hit": True, "clauses": ["附件一·十二", "AQ3067·作业安全"]},
        )
        out = rules.validate_output(raw)
        assert out.major_hazard.hit is True
        assert out.major_hazard.clauses == ["附件一·十二", "AQ3067·作业安全"]

    def test_major_hazard_defaults_when_missing(self):
        raw = {k: v for k, v in VALID_RAW.items() if k != "major_hazard"}
        out = rules.validate_output(raw)
        assert out.major_hazard.hit is False
        assert out.major_hazard.clauses == []
