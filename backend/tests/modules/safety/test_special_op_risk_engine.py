"""RiskAssessmentEngine V3.6 新增两条高风险规则的单测。

规则 15：动火作业凡涉及高风险区域（RTO/酸化池/SBR/CASS/事故池/水热矿化/氨水系统/
        提二苯结晶（含室外带滤罐）/储罐区/溶媒回收/乙醇配制罐区/危化品仓库）
        均判高风险。
规则 16：作业涉及硫酸、碱液等腐蚀性介质的管道/管线，不限作业类型判高风险。

用 ``SpecialOpView`` 直接构造记录（字段与 ORM 同名同义），
另用直读链路 ``to_view`` + ``assess_view`` 做一条端到端验证。
"""

from __future__ import annotations

import pytest

from app.modules.safety.service.special_op_direct.bitable_repo import (
    SpecialOpView,
    assess_view,
    to_view,
)
from app.modules.safety.service.special_op_direct.tests.factories import record
from app.modules.safety.service.special_operation_daily_report import (
    CORROSIVE_SUBSTANCES,
    HOT_WORK_HIGH_RISK_ZONE_KEYWORDS,
    ReportBuilder,
    RiskAssessmentEngine,
)


def _assess(**kw):
    return RiskAssessmentEngine.assess(SpecialOpView(**kw))


def _hit_reason(result, fragment: str) -> bool:
    return any(fragment in rule for rule in result.matched_rules)


# ── 规则 15：动火作业涉及高风险区域 ──────────────────────────


@pytest.mark.parametrize("keyword", HOT_WORK_HIGH_RISK_ZONE_KEYWORDS)
def test_hot_work_in_zone_keyword_is_high(keyword):
    result = _assess(operation_type="hot_work", location=f"车间{keyword}旁")
    assert result.risk_level == "high"
    assert _hit_reason(result, "动火作业涉及高风险区域")


def test_hot_work_zone_matched_in_description():
    result = _assess(
        operation_type="hot_work", location="污水站",
        work_description="对乙醇配制罐输送泵进行动火检修",
    )
    assert result.risk_level == "high"
    assert _hit_reason(result, "动火作业涉及高风险区域")


def test_hot_work_zone_case_insensitive():
    result = _assess(operation_type="hot_work", location="rto炉边")
    assert result.risk_level == "high"
    assert _hit_reason(result, "动火作业涉及高风险区域")


def test_non_hot_work_in_zone_not_high():
    result = _assess(operation_type="confined_space", location="事故池区域")
    assert result.risk_level != "high"
    assert not _hit_reason(result, "动火作业涉及高风险区域")


def test_zone_reason_lists_all_hit_keywords():
    result = _assess(
        operation_type="hot_work", location="溶媒回收车间储罐区",
    )
    assert _hit_reason(result, "储罐区、溶媒回收")


# ── 规则 16：腐蚀性介质管道 ──────────────────────────────────


@pytest.mark.parametrize("substance", CORROSIVE_SUBSTANCES)
def test_corrosive_pipeline_is_high_regardless_of_type(substance):
    result = _assess(
        operation_type="常规作业", location="车间",
        work_description=f"更换{substance}输送管线",
    )
    assert result.risk_level == "high"
    assert _hit_reason(result, "作业涉及腐蚀性管道")


def test_corrosive_pipeline_with_hot_work_is_high():
    result = _assess(
        operation_type="hot_work", location="车间",
        work_description="碱液管道旁动火",
    )
    assert result.risk_level == "high"
    assert _hit_reason(result, "作业涉及腐蚀性管道")


def test_corrosive_substance_without_pipeline_not_high():
    result = _assess(
        operation_type="temporary_electricity", location="仓库",
        work_description="硫酸桶搬运接电照明",
    )
    assert result.risk_level != "high"
    assert not _hit_reason(result, "作业涉及腐蚀性管道")


def test_pipeline_without_corrosive_substance_not_high():
    result = _assess(
        operation_type="hot_work", location="车间",
        work_description="消防水管道焊接",
    )
    assert result.risk_level == "low"
    assert not _hit_reason(result, "作业涉及腐蚀性管道")


# ── 管控措施回退 ────────────────────────────────────────────


def test_control_measure_for_zone_rule():
    view = SpecialOpView(daily_risk_reason="动火作业涉及高风险区域（RTO）")
    assert ReportBuilder._control_measure(view) == (
        "动火前对周边设备管线吹扫置换并做可燃气体检测，清理可燃物，专人监护并备齐消防器材"
    )


def test_control_measure_zone_takes_precedence_over_tank_zone():
    # 「储罐区」理由文本含「罐区」子串，须先命中新措施而非旧罐区措施
    view = SpecialOpView(daily_risk_reason="动火作业涉及高风险区域（储罐区）")
    assert ReportBuilder._control_measure(view).startswith("动火前对周边设备管线")


def test_control_measure_for_corrosive_rule():
    view = SpecialOpView(daily_risk_reason="作业涉及腐蚀性管道（硫酸）")
    assert ReportBuilder._control_measure(view) == (
        "作业前对腐蚀性管道泄压、排净、置换、清洗合格，穿戴防酸碱防护用品，现场设应急冲洗水源"
    )


# ── 直读链路端到端（映射 → 判定 → 写回视图） ─────────────────


def test_direct_read_path_end_to_end():
    item = record(
        "rec-zone",
        作业类型="动火作业", 作业地点="RTO 炉区", 作业内容="RTO 检修动火",
    )
    view = assess_view(to_view(item))
    assert view.daily_risk_level == "high"
    assert "动火作业涉及高风险区域" in (view.daily_risk_reason or "")

    item2 = record(
        "rec-corrosive",
        作业类型="动火作业", 作业地点="车间", 作业内容="更换硫酸管道",
    )
    view2 = assess_view(to_view(item2))
    assert view2.daily_risk_level == "high"
    assert "作业涉及腐蚀性管道" in (view2.daily_risk_reason or "")
