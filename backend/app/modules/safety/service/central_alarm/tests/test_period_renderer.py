"""周期报告渲染单测——ticket 01 RED。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.modules.safety.service.central_alarm.aggregator import aggregate_period
from app.modules.safety.service.central_alarm.reader import CentralAlarmView
from app.modules.safety.service.central_alarm.renderer import render_period_report

_BJ = timedelta(hours=8)


def _v(vid: str, bj: datetime, **kw) -> CentralAlarmView:
    v = CentralAlarmView(
        id=vid, alarm_date=bj - _BJ,
        workshop=kw.get("workshop", "酒精回收和旧罐区"),
        post=kw.get("post", "DCS 内操"),
        alarm_description="V0407 储罐 高高压报警",
    )
    v.ai_alarm_type = kw.get("alarm_type", "高高压")
    v.ai_pattern = kw.get("pattern", "false_alarm")
    v.ai_analyzed_at = datetime.now(UTC) if kw.get("analyzed", True) else None
    return v


def _agg_with_prev():
    records = [
        _v("r1", datetime(2026, 11, 2, 10)),
        _v("r2", datetime(2026, 11, 3, 10), pattern="repeated"),
        _v("r3", datetime(2026, 11, 4, 10), workshop="乙腈回收", post="外操"),
    ]
    prev = [_v("p1", datetime(2026, 10, 26, 10))]
    return aggregate_period(
        records, kind="weekly",
        period_start=date(2026, 11, 2), period_end=date(2026, 11, 8),
        prev_records=prev, prev_days=7,
    )


def test_render_contains_four_core_indicators_and_top10() -> None:
    md = render_period_report(_agg_with_prev())
    assert "周报" in md
    assert "2026-11-02" in md and "2026-11-08" in md
    assert "报警总数" in md
    assert "日均" in md          # 单位时间报警率
    assert "高频报警点" in md
    assert "无效报警" in md
    assert "环比" in md
    # Top10 榜：车间·岗位 出现在热点行
    assert "酒精回收和旧罐区" in md
    assert "DCS 内操" in md
    # 口径说明与数据源
    assert "高高" in md
    assert "中控报警统计" in md


def test_render_with_ai_blocks() -> None:
    md = render_period_report(
        _agg_with_prev(),
        {"summary": "本周态势平稳。", "key_issues": ["问题一"],
         "improvement_suggestions": ["建议一：校准 V0407 变送器"]},
    )
    assert "本周态势平稳" in md
    assert "问题一" in md
    assert "建议一：校准 V0407 变送器" in md
    assert "改进建议" in md


def test_render_ai_failure_degrades_to_data_only() -> None:
    md = render_period_report(_agg_with_prev(), None)
    assert "报警总数" in md        # 数据块仍在
    assert "改进建议" not in md    # AI 块省略


def test_render_empty_period() -> None:
    agg = aggregate_period(
        [], kind="monthly",
        period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
    )
    md = render_period_report(agg)
    assert "月报" in md
    assert "无报警" in md or "平稳" in md
    assert "报警总数" in md  # 指标仍展示（0）


def test_render_prev_ratio_dash_when_none() -> None:
    agg = aggregate_period(
        [], kind="weekly",
        period_start=date(2026, 11, 2), period_end=date(2026, 11, 8),
    )
    md = render_period_report(agg)
    assert "—" in md  # prev 缺失 → 环比显示占位符
