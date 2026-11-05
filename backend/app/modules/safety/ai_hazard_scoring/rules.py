"""AI隐患评分 — 规则层（纯函数，总分/一致性/校验全部代码权威）。

与①轮「枚举校验丢弃」不同：评分无「部分可写」语义，四维档位必须齐全，
任一非法即抛 ScoringError（⑤轮语义=不写、下轮重试）。
"""

from __future__ import annotations

from app.modules.safety.ai_hazard_scoring.schemas import (
    ConsequenceTier,
    DifficultyTier,
    ExposureTier,
    HazardScoringOutput,
    LikelihoodTier,
    RiskBandEnum,
)


class ScoringError(Exception):
    """评分失败（AI 输出非法或缺失）。"""


# ═══════════════════════════════════════════════════════════════════════════
# 档位 ↔ 中文档位标签（制度 §10.3 原文）
# ═══════════════════════════════════════════════════════════════════════════

TIER_LABELS: dict[str, dict[str, str]] = {
    "likelihood": {
        LikelihoodTier.VERY_LIKELY: "非常可能",
        LikelihoodTier.LIKELY: "可能",
        LikelihoodTier.UNLIKELY: "可能性小",
    },
    "exposure": {
        ExposureTier.CONTINUOUS: "连续接触",
        ExposureTier.DAILY: "每天几次接触",
        ExposureTier.WEEKLY: "每周接触",
        ExposureTier.MONTHLY: "每月接触",
        ExposureTier.YEARLY: "每年接触",
        ExposureTier.RARE: "很少接触",
    },
    "consequence": {
        ConsequenceTier.CATASTROPHE: "灾难",
        ConsequenceTier.VERY_SEVERE: "非常严重",
        ConsequenceTier.SEVERE: "严重",
        ConsequenceTier.MODERATE: "一般",
        ConsequenceTier.MINOR: "轻微",
    },
    "difficulty": {
        DifficultyTier.HARD: "难",
        DifficultyTier.FAIRLY_HARD: "较难",
        DifficultyTier.NORMAL: "一般",
    },
}

LABEL_TO_TIER: dict[str, dict[str, str]] = {
    dim: {label: member.value for member, label in mapping.items()}
    for dim, mapping in TIER_LABELS.items()
}


def tier_label(dim: str, member: str) -> str:
    """枚举 value → 制度中文档位标签（供 note 拼装等展示侧使用）。"""
    for enum_member, label in TIER_LABELS[dim].items():
        if enum_member.value == member:
            return label
    raise ScoringError(f"{dim} 无此档位: {member!r}")

# band 中文别名（AI 可能输出 高/中/低）
_BAND_ALIAS: dict[str, RiskBandEnum] = {
    "H": RiskBandEnum.HIGH, "高": RiskBandEnum.HIGH, "高风险": RiskBandEnum.HIGH,
    "M": RiskBandEnum.MEDIUM, "中": RiskBandEnum.MEDIUM, "中风险": RiskBandEnum.MEDIUM,
    "L": RiskBandEnum.LOW, "低": RiskBandEnum.LOW, "低风险": RiskBandEnum.LOW,
}

# 一致性软校验阈值（无制度依据的硬换算，仅提示人工复核）
_CONSISTENCY_HIGH_MIN = 45.0   # D≥45 却报 L → 警示
_CONSISTENCY_LOW_MAX = 25.0    # D<25 却报 H → 警示


# ═══════════════════════════════════════════════════════════════════════════
# 总分
# ═══════════════════════════════════════════════════════════════════════════


def compute_total(out: HazardScoringOutput) -> float:
    """D = L×E×C×X，四舍五入 1 位小数（制度 §10.3）。"""
    total = (
        float(out.likelihood.value)
        * float(out.exposure.value)
        * float(out.consequence.value)
        * float(out.difficulty.value)
    )
    total = round(total, 1)
    # 理论区间断言：制度档位全组合 [14.7, 100]
    if not 14.7 <= total <= 100.0:
        raise ScoringError(f"总分超出制度理论区间 [14.7, 100]: {total}")
    return total


def band_consistency(out: HazardScoringOutput, total: float) -> str | None:
    """band 与总分一致性软校验；不一致返回警示文案，一致返回 None。"""
    if total >= _CONSISTENCY_HIGH_MIN and out.band is RiskBandEnum.LOW:
        return f"⚠分值{total}与风险等级L不一致，建议人工复核"
    if total < _CONSISTENCY_LOW_MAX and out.band is RiskBandEnum.HIGH:
        return f"⚠分值{total}与风险等级H不一致，建议人工复核"
    return None


# ═══════════════════════════════════════════════════════════════════════════
# 输出校验（AI 原始 dict → 强类型）
# ═══════════════════════════════════════════════════════════════════════════


def _tier_of(dim: str, raw: object) -> str:
    """中文档位/枚举值 → 枚举 value；非法抛 ScoringError。"""
    if not isinstance(raw, str) or not raw.strip():
        raise ScoringError(f"{dim} 档位缺失或非字符串: {raw!r}")
    key = raw.strip()
    table = LABEL_TO_TIER[dim]
    if key in table:
        return table[key]
    # 容错：AI 直接给枚举值（"2.0"）也接受
    valid_values = {member.value for member in TIER_LABELS[dim]}
    if key in valid_values:
        return key
    allowed = "、".join(table)
    raise ScoringError(f"{dim} 档位非法: {key!r}（允许: {allowed}）")


def _band_of(raw: object) -> RiskBandEnum:
    if not isinstance(raw, str) or not raw.strip():
        raise ScoringError(f"band 缺失或非字符串: {raw!r}")
    band = _BAND_ALIAS.get(raw.strip())
    if band is None:
        raise ScoringError(f"band 非法: {raw!r}（允许: H/M/L）")
    return band


def _reason(raw: object, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ScoringError(f"{field} 缺失或为空")
    return raw.strip()


def validate_output(raw: dict) -> HazardScoringOutput:
    """AI 原始输出 → HazardScoringOutput；任一档位/理由非法抛 ScoringError。"""
    if not isinstance(raw, dict):
        raise ScoringError(f"AI 输出非 dict: {type(raw).__name__}")
    try:
        return HazardScoringOutput(
            likelihood=LikelihoodTier(_tier_of("likelihood", raw.get("likelihood"))),
            likelihood_reason=_reason(raw.get("likelihood_reason"), "likelihood_reason"),
            exposure=ExposureTier(_tier_of("exposure", raw.get("exposure"))),
            exposure_reason=_reason(raw.get("exposure_reason"), "exposure_reason"),
            consequence=ConsequenceTier(_tier_of("consequence", raw.get("consequence"))),
            consequence_reason=_reason(raw.get("consequence_reason"), "consequence_reason"),
            difficulty=DifficultyTier(_tier_of("difficulty", raw.get("difficulty"))),
            difficulty_reason=_reason(raw.get("difficulty_reason"), "difficulty_reason"),
            band=_band_of(raw.get("band")),
            band_basis=_reason(raw.get("band_basis"), "band_basis"),
            major_hazard=_major_hazard_of(raw.get("major_hazard")),
            summary=_reason(raw.get("summary"), "summary"),
        )
    except ScoringError:
        raise
    except Exception as exc:  # pydantic 校验等
        raise ScoringError(f"AI 输出结构非法: {exc}") from exc


def _major_hazard_of(raw: object) -> dict:
    """major_hazard 容错解析：缺失 → 未命中；hit 假值 → 未命中。"""
    if not isinstance(raw, dict):
        return {"hit": False, "clauses": []}
    hit = raw.get("hit")
    clauses_raw = raw.get("clauses")
    clauses = [
        str(c).strip() for c in clauses_raw
        if isinstance(c, str) and c.strip()
    ] if isinstance(clauses_raw, list) else []
    return {"hit": bool(hit), "clauses": clauses}
