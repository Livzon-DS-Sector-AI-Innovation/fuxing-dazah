"""R1 消防候选规则矩阵 —— 白名单∪故障∪闭环（§9.1 拍板口径，修正实测字段名）。

字段名全部用消防表实测原始列名（报警性质/报警原因分类），修复冒烟③
`fields.原因分类` 恒 None 的错位；closure_class 由扫描源翻译进
payload._derived（规则 DSL 只判结构化值，文本语义不进规则引擎）。
"""

from __future__ import annotations

from app.modules.safety.service.alarm_hazard_r1.rule import (
    R1_FIRE_SOURCE_NAME,
    r1_fire_rule,
)
from app.platform.superagent.policy import evaluate_rule


def _payload(
    nature: str = "误报",
    cause: str = "蒸汽引发",
    closure: str = "closed",
) -> dict:
    return {
        "fields": {"报警性质": nature, "报警原因分类": cause},
        "_derived": {"closure_class": closure},
    }


def _hit(nature: str, cause: str, closure: str = "closed") -> bool:
    hit, _ = evaluate_rule(r1_fire_rule(), _payload(nature, cause, closure))
    return hit


# ═══════════════════════════════════════════════════════════════
# 声明形态
# ═══════════════════════════════════════════════════════════════


def test_rule_declaration_shape() -> None:
    """rule_id/executor/source/enabled 与 R1 组件绑定一致。"""
    rule = r1_fire_rule()
    assert rule["rule_id"] == "fire_alarm_candidate"
    assert rule["enabled"] is True
    assert rule["source"] == R1_FIRE_SOURCE_NAME == "safety.fire_alarm.r1"
    assert rule["executor"] == "alarm_hazard_create"


# ═══════════════════════════════════════════════════════════════
# 子规则一：原因白名单（P1 拍板；矛盾标记留给人工——坑②口径）
# ═══════════════════════════════════════════════════════════════


def test_whitelist_causes_hit() -> None:
    for cause in ("现场着火", "硫化氢引发", "氨水引发", "甲烷引发"):
        assert _hit("泄漏报警", cause), cause
    # 白名单原因即使被人工标「误报」也进（矛盾标记留给确认门）
    assert _hit("误报", "氨水引发")


def test_excluded_natures_always_rejected() -> None:
    """性质 ∈ 排除集一律不进（即使原因在白名单、closure 未闭环）。"""
    for nature in ("测试报警", "测试性质", "演练引发"):
        assert not _hit(nature, "现场着火"), nature
        assert not _hit(nature, "蒸汽引发", closure="pending_handover"), nature


# ═══════════════════════════════════════════════════════════════
# 子规则二：故障（坑①——纯原因口径会漏真设施失效）
# ═══════════════════════════════════════════════════════════════


def test_fault_subrule() -> None:
    assert _hit("故障报警", "设备误报")      # 61 条真设施失效的归宿
    assert _hit("故障报警", "现场施工")      # 施工致设施故障 17 条并入
    assert not _hit("故障报警", "测试")       # 故障|测试 12 条计划内噪音不进
    assert not _hit("故障报警", "演练引发")


def test_fault_with_empty_cause_hits() -> None:
    """原因空 + 性质=故障 → 进（冒烟③同款边界行为；口径对齐报告另说明）。"""
    assert _hit("故障报警", "")


# ═══════════════════════════════════════════════════════════════
# 子规则三：闭环（§9.1 增量：移交无回执/明示待办/处理情况空）
# ═══════════════════════════════════════════════════════════════


def test_closure_subrule_hits() -> None:
    """未闭环三类命中（§1.2 C 类含误报 29/故障 4/泄漏 3——不设性质门槛）。"""
    assert _hit("误报", "蒸汽引发", closure="pending_handover")
    assert _hit("故障报警", "设备误报", closure="explicit_todo")
    assert _hit("泄漏报警", "氨水引发", closure="empty")


def test_closure_closed_or_other_rejected() -> None:
    """closed/other 不进闭环子规则（F 类不算未闭环）。"""
    assert not _hit("误报", "蒸汽引发", closure="closed")
    assert not _hit("误报", "设备误报", closure="other")


# ═══════════════════════════════════════════════════════════════
# 噪音排除（单条无追踪价值，聚合口径属二期）
# ═══════════════════════════════════════════════════════════════


def test_noise_rejected() -> None:
    assert not _hit("误报", "蒸汽引发")
    assert not _hit("误报", "设备误报")
    assert not _hit("误报", "氧气变化")
    assert not _hit("误报", "投粉收粉扬尘")


def test_union_semantics() -> None:
    """三子规则并集：任一命中即进（含白名单+闭环同时命中不重复）。"""
    assert _hit("泄漏报警", "氨水引发", closure="pending_handover")
