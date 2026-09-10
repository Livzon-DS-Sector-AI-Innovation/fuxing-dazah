"""URS 智能审核 — 规则引擎与硬编码规则。

铁律（代码强制，不依赖 AI 自觉）：
- 否决项保留：is_veto 无条件强制 mandatory（D3/D7）
- 维度门控：适配等级按五维风险等级硬性确定（high→强制 / medium→建议 / low→不适用），
  防止 AI 将高风险设备全部判为强制适用（适配口径 A）
- 置信度阈值：<0.8 触发人工复核（复核兜底，D4）
- 评分口径：A≥90 / B≥75 / C≥60 / D<60；仅否决项任一 failed → rejected（一票否决，D7）
  非否决强制项 failed 只降低评分并列入整改，不直接否决
"""

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# 置信度人工复核阈值
CONFIDENCE_REVIEW_THRESHOLD = 0.8

# 等级阈值
GRADE_THRESHOLDS: list[tuple[float, str]] = [(90.0, "A"), (75.0, "B"), (60.0, "C"), (0.0, "D")]


def sanitize_enum(value: Any, enum_cls: type[Enum], default: Any) -> Any:
    """清洗 AI 枚举值：去首尾标点后尝试构造枚举，失败回退默认。"""
    if value is None:
        return default
    v = str(value).strip().strip("。，,.、;；")
    try:
        return enum_cls(v)
    except (ValueError, TypeError):
        logger.warning("URS 枚举值非法 %s=%r，回退默认 %s", enum_cls.__name__, value, default)
        return default


def grade_for_score(score: float) -> str:
    """按 D7 口径映射百分制分数 → 等级。"""
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "D"


def compute_overall_risk(dim_levels: dict[str, str]) -> str:
    """综合风险等级：任一 high→high；任一 medium→medium；否则 low。"""
    levels = {v for v in dim_levels.values() if v}
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    return "low"


def apply_veto_override(items: list[dict], veto_nos: set[str]) -> list[dict]:
    """否决项强制 mandatory（适配后代码兜底，防止 AI 将否决项标为 not_applicable）。"""
    for it in items:
        if it.get("item_no") in veto_nos:
            it["applicability"] = "mandatory"
    return items


# 维度风险等级 → 适配等级（适配口径 A）
_DIM_GATE_BY_LEVEL: dict[str, str] = {
    "high": "mandatory",        # 高风险维度 → 强制适用（纳入一票否决约束面）
    "medium": "recommended",    # 中风险维度 → 建议适用（不再一票否决）
    "low": "not_applicable",    # 低风险维度 → 不适用（自动剔除，不计分）
}


def apply_dimension_gate(
    items: list[dict],
    dim_levels: dict[str, str],
    overall_level: str,
) -> list[dict]:
    """五维风险维度门控（代码强制，覆盖 AI 适配输出）。

    按条目的 ``risk_dimension`` 对应维度风险等级硬性确定适配等级：
      - 否决项 → mandatory（无条件保留）
      - 维度 high → mandatory
      - 维度 medium → recommended
      - 维度 low → not_applicable（设备不涉及该维度，自动剔除）
      - ``risk_dimension`` 非五维（none/空，通用项）→ 按综合风险：
        综合 high → mandatory，medium/low → recommended

    目的：避免"高风险设备全部维度≥medium → 30 条全适用、0 条不适用、25 条强制"的
    过度严格局面；中/低风险维度的条款不再各自触发一票否决。
    """
    for it in items:
        if it.get("is_veto"):
            it["applicability"] = "mandatory"
            continue
        dim = it.get("risk_dimension")
        level = dim_levels.get(dim) if isinstance(dim, str) and dim in dim_levels else None
        if level in _DIM_GATE_BY_LEVEL:
            it["applicability"] = _DIM_GATE_BY_LEVEL[level]
        else:
            it["applicability"] = "mandatory" if overall_level == "high" else "recommended"
    return items


def conclude(items: list[dict]) -> tuple[str, bool]:
    """计算最终结论 (conclusion, veto_break)。

    D7 结论口径（v2 放宽版）：仅否决项（is_veto）任一 failed → rejected（一票否决）。
    非否决强制项 failed 只降低评分并列入整改要求，不直接否决——配合维度门控适配
    （高风险维度条款被判 mandatory），避免高风险设备因任一强制项缺失而必然被否。
    """
    for it in items:
        if it.get("is_veto") and it.get("review_status") == "failed":
            return "rejected", True
    return "approved", False


def compute_score(items: list[dict]) -> float:
    """百分制评分 = 通过项 / 适用项 × 100（D7）。"""
    applicable = [
        it for it in items
        if it.get("applicability") in ("mandatory", "recommended")
    ]
    if not applicable:
        return 100.0
    passed = sum(1 for it in applicable if it.get("review_status") == "passed")
    return round(passed / len(applicable) * 100, 1)
