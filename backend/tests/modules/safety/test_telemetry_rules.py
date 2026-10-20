"""facilities-p2 票 02：遥测规则引擎纯函数（无 DB/IO，now 可注入）。

照 facilities/engine.py 范式：判定口径单点定义，编排层（alerter/collector）
与单测共用。覆盖：上下限/连续点去抖/变化率/规则合并优先级/覆写非法回退。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.safety.telemetry.rules import (
    DEFAULT_RULES,
    RuleSpec,
    dedupe_key,
    effective_rules,
    evaluate,
    rule_for,
)

T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


def _points(*pairs: tuple[int, float]) -> list[tuple[datetime, float]]:
    """(分钟偏移, 值) 列表 → 升序点位。"""
    return [(T0 + timedelta(minutes=m), v) for m, v in pairs]


BOILER_PRESSURE = RuleSpec(metric="汽压", category="锅炉", min=0.2, max=1.0)


# ── 规则匹配：设备级 > 类别级 > 默认 ─────────────────────────────────


def test_rule_for_specificity_equipment_over_category_over_default():
    rules = (
        BOILER_PRESSURE,
        RuleSpec(metric="汽压", min=0.1, max=0.9),                     # 通配默认
        RuleSpec(metric="汽压", equipment_no="GL-01", min=0.3, max=1.2),  # 设备级
    )
    hit = rule_for(rules, equipment_no="GL-01", category="锅炉", metric="汽压")
    assert hit is not None and hit.max == 1.2
    # 设备不匹配 → 回落类别级
    hit2 = rule_for(rules, equipment_no="GL-99", category="锅炉", metric="汽压")
    assert hit2 is not None and hit2.max == 1.0
    # 类别也不匹配 → 通配
    rules_wc = (BOILER_PRESSURE, RuleSpec(metric="汽压", min=0.1, max=0.9))
    hit3 = rule_for(rules_wc, equipment_no="GL-99", category="压力容器", metric="汽压")
    assert hit3 is not None and hit3.max == 0.9
    # 无任何匹配 → None
    assert rule_for(rules, "GL-01", "锅炉", "水位") is None


# ── 上下限 + 连续点去抖 ──────────────────────────────────────────────


def test_evaluate_high_limit_needs_consecutive_points():
    rule = RuleSpec(metric="汽压", min=0.2, max=1.0, consecutive=2)
    # 单点超限：去抖不触发
    assert evaluate(_points((0, 0.8), (5, 1.2)), rule, now=T0) is None
    # 连续两点超限：触发
    v = evaluate(_points((0, 0.8), (5, 1.2), (10, 1.3)), rule, now=T0)
    assert v is not None
    assert v.kind == "limit_high"
    assert v.value == 1.3
    assert "超上限" in v.rule_desc


def test_evaluate_low_limit_and_single_point_rule():
    rule = RuleSpec(metric="水位", min=-50, max=50, consecutive=1)
    v = evaluate(_points((0, -30), (5, -60)), rule, now=T0)
    assert v is not None and v.kind == "limit_low" and v.value == -60

    # consecutive=1 单点即报（默认去抖关闭态）
    one = RuleSpec(metric="汽压", max=1.0, consecutive=1)
    assert evaluate(_points((0, 1.2)), one, now=T0) is not None


def test_evaluate_mixed_directions_do_not_count_as_streak():
    """一点超上限+一点低于下限=毛刺往返，不算连续同向异常。"""
    rule = RuleSpec(metric="汽压", min=0.2, max=1.0, consecutive=2)
    assert evaluate(_points((0, 1.3), (5, 0.1)), rule, now=T0) is None


def test_evaluate_no_rule_thresholds_no_violation():
    rule = RuleSpec(metric="炉膛温度", max=1200)  # 无 min/无 rate
    assert evaluate(_points((0, 100), (5, 1100)), rule, now=T0) is None


# ── 变化率 ──────────────────────────────────────────────────────────


def test_evaluate_rate_violation_two_points():
    rule = RuleSpec(metric="汽压", min=0.0, max=2.0, rate_per_min=0.05)
    v = evaluate(_points((0, 0.5), (5, 0.9)), rule, now=T0)  # 0.08/分
    assert v is not None and v.kind == "rate" and v.value == 0.9
    assert "变化率" in v.rule_desc
    # 0.04/分 在限内
    assert evaluate(_points((0, 0.5), (5, 0.7)), rule, now=T0) is None


def test_evaluate_rate_skipped_when_zero_elapsed():
    rule = RuleSpec(metric="汽压", rate_per_min=0.05)
    assert evaluate(_points((5, 0.5), (5, 0.9)), rule, now=T0) is None  # 同刻两点不除零


# ── 覆写合并与非法回退 ──────────────────────────────────────────────


def test_effective_rules_override_appends_and_picks_specific():
    override = '[{"metric":"汽压","equipment_no":"GL-01","max":1.6}]'
    rules = effective_rules(override)
    hit = rule_for(rules, "GL-01", "锅炉", "汽压")
    assert hit is not None and hit.max == 1.6 and hit.equipment_no == "GL-01"
    # 其他锅炉仍走默认
    hit2 = rule_for(rules, "GL-02", "锅炉", "汽压")
    assert hit2 is not None and hit2.equipment_no is None


def test_effective_rules_invalid_json_falls_back_to_default():
    assert effective_rules("不是json") == DEFAULT_RULES
    assert effective_rules('{"metric":"x"}') == DEFAULT_RULES       # 非 list
    assert effective_rules('[{"metric":123}]') == DEFAULT_RULES    # 字段类型错
    assert effective_rules("") == DEFAULT_RULES
    assert effective_rules(None) == DEFAULT_RULES


def test_effective_rules_rejects_negative_consecutive():
    assert effective_rules('[{"metric":"汽压","consecutive":0}]') == DEFAULT_RULES


def test_default_rules_cover_boiler_metrics():
    metrics = {r.metric for r in DEFAULT_RULES}
    assert {"汽压", "水位", "炉膛温度"} <= metrics
    pressure = rule_for(DEFAULT_RULES, "GL-01", "锅炉", "汽压")
    assert pressure is not None and pressure.consecutive == 2  # 默认连续 2 点


# ── dedupe_key 静默窗时间桶 ─────────────────────────────────────────


def test_dedupe_key_same_window_collapses_across_time():
    silence = 1800
    a = dedupe_key("GL-01", "汽压", "alarm", T0, silence)
    b = dedupe_key("GL-01", "汽压", "alarm", T0 + timedelta(minutes=29), silence)
    c = dedupe_key("GL-01", "汽压", "alarm", T0 + timedelta(minutes=31), silence)
    assert a == b          # 同 30 分钟窗 → 同 key（唯一键拦截）
    assert a != c          # 跨窗 → 新 key 放行新报警
    # 不同级别/设备/指标分键
    assert a != dedupe_key("GL-01", "汽压", "warning", T0, silence)
    assert a != dedupe_key("GL-02", "汽压", "alarm", T0, silence)
    assert a != dedupe_key("GL-01", "水位", "alarm", T0, silence)


def test_evaluate_insufficient_history_no_limit_violation():
    """去抖铁律：历史点数不足 consecutive（如全新设备首条）不触发上下限。"""
    rule = RuleSpec(metric="汽压", min=0.2, max=1.0, consecutive=2)
    assert evaluate(_points((0, 1.5)), rule, now=T0) is None  # 单点越界不报
    assert evaluate(_points((0, 0.1)), rule, now=T0) is None
