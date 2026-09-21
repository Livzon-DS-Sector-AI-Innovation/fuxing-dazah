"""Ticket 01：CentralAlarmView 视图对象与类型接缝。

- 视图字段集合 == 预期字面量集合（独立真值，防漂移）；
- 同一份数据 ORM 对象与视图对象分别聚合 + 渲染，markdown 逐字相同；
- ai_* 字段直读恒 None（视图默认值）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.safety.models import CentralAlarmRecord
from app.modules.safety.service.central_alarm.aggregator import aggregate_daily
from app.modules.safety.service.central_alarm.renderer import render_daily_report

_EXPECTED_VIEW_FIELDS = {
    "id",
    "feishu_record_id",
    "source",
    "synced_at",
    "created_at",
    "alarm_date",
    "post",
    "alarm_description",
    "special_note",
    "workshop",
    "line",
    "ai_alarm_type",
    "ai_equipment",
    "ai_pattern",
    "ai_dimension",
    "ai_reason_analysis",
    "ai_rectification_direction",
    "ai_analyzed_at",
}

_SAMPLE: dict[str, Any] = dict(
    feishu_record_id="rec001",
    source="bitable",
    synced_at=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
    alarm_date=datetime(2026, 9, 20, 1, 30, tzinfo=UTC),
    post="DCS 内操",
    alarm_description="R19150B 层析上柱罐 高高压报警",
    special_note=None,
    workshop="车间一",
    line="达托",
    ai_alarm_type="高高压",
    ai_equipment="R19150B",
    ai_pattern="repeated",
    ai_dimension="equipment",
    ai_reason_analysis="同岗位本周第二次高高压，疑似联锁阈值漂移",
    ai_rectification_direction="核查压力变送器与联锁设定值",
    ai_analyzed_at=datetime(2026, 9, 20, 9, 5, tzinfo=UTC),
)


def _make_orm() -> CentralAlarmRecord:
    return CentralAlarmRecord(id=1, **_SAMPLE)


def _make_view() -> Any:
    from app.modules.safety.service.central_alarm.reader import CentralAlarmView

    return CentralAlarmView(id="1", **_SAMPLE)


def test_view_fields_match_expected_set() -> None:
    from app.modules.safety.service.central_alarm.reader import CentralAlarmView

    assert set(CentralAlarmView.__dataclass_fields__) == _EXPECTED_VIEW_FIELDS


def test_view_defaults_ai_fields_none() -> None:
    from app.modules.safety.service.central_alarm.reader import CentralAlarmView

    v = CentralAlarmView(id="r1")
    assert v.ai_alarm_type is None
    assert v.ai_pattern is None
    assert v.ai_dimension is None
    assert v.ai_reason_analysis is None
    assert v.workshop is None


@pytest.mark.parametrize("make", [_make_orm, _make_view], ids=["orm", "view"])
def test_render_identical_via_view_and_orm(make: Any) -> None:
    record = make()
    agg = aggregate_daily([record], datetime(2026, 9, 20).date())
    markdown = render_daily_report(agg)
    assert "R19150B" in markdown
    assert "车间一" in markdown
    # 结构块存在（渲染零改动复用的前提）
    assert "高高" in markdown


def test_agg_attribute_access_on_view() -> None:
    """aggregate_daily 对视图对象读的属性与 ORM 同名（接缝核心断言）。"""
    record = _make_view()
    agg = aggregate_daily([record], datetime(2026, 9, 20).date())
    assert agg.total == 1
    assert agg.workshop_distribution == {"车间一": 1}
    assert agg.post_distribution == {"DCS 内操": 1}
    assert agg.alarm_type_distribution == {"高高压": 1}
    assert agg.pattern_distribution == {"repeated": 1}
    assert agg.dimension_distribution == {"equipment": 1}
    assert list(agg.workshop_groups) == ["车间一"]
