"""中控报警数据聚合（ticket 03 统计复用 + ticket 05 日报聚合）。

纯函数，无 DB 依赖；用于自然周计算、日报统计分布与车间分组。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.modules.safety.models import CentralAlarmRecord


@dataclass
class CentralAlarmDailyAgg:
    """日报聚合结果。"""

    target_date: date
    records: list[CentralAlarmRecord] = field(default_factory=list)
    total: int = 0
    workshop_distribution: dict[str, int] = field(default_factory=dict)
    post_distribution: dict[str, int] = field(default_factory=dict)
    alarm_type_distribution: dict[str, int] = field(default_factory=dict)
    pattern_distribution: dict[str, int] = field(default_factory=dict)
    dimension_distribution: dict[str, int] = field(default_factory=dict)
    # 车间分组（报表按车间分节）
    workshop_groups: dict[str, list[CentralAlarmRecord]] = field(default_factory=dict)


def get_natural_week_range(ref_date: date) -> tuple[date, date]:
    """返回 ref_date 所在自然周的周一与周日（周一=0）。"""
    monday = ref_date - timedelta(days=ref_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def aggregate_daily(records: list[CentralAlarmRecord], target_date: date) -> CentralAlarmDailyAgg:
    """聚合当日报警记录 → 统计分布 + 按车间分组。

    分布统计基于记录上已有的 AI 分析字段（ai_alarm_type/ai_pattern/ai_dimension）与
    车间/岗位字段；值为 None 的不计入。车间分组按 workshop 键分组。
    """
    agg = CentralAlarmDailyAgg(target_date=target_date, records=list(records))
    agg.total = len(records)
    workshop_groups: dict[str, list[CentralAlarmRecord]] = {}
    for r in records:
        if r.workshop:
            workshop_groups.setdefault(r.workshop, []).append(r)
            agg.workshop_distribution[r.workshop] = agg.workshop_distribution.get(r.workshop, 0) + 1
        if r.post:
            agg.post_distribution[r.post] = agg.post_distribution.get(r.post, 0) + 1
        if r.ai_alarm_type:
            agg.alarm_type_distribution[r.ai_alarm_type] = agg.alarm_type_distribution.get(r.ai_alarm_type, 0) + 1
        if r.ai_pattern:
            agg.pattern_distribution[r.ai_pattern] = agg.pattern_distribution.get(r.ai_pattern, 0) + 1
        if r.ai_dimension:
            agg.dimension_distribution[r.ai_dimension] = agg.dimension_distribution.get(r.ai_dimension, 0) + 1
    agg.workshop_groups = workshop_groups
    return agg


def _count_by(records: list[CentralAlarmRecord], attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        v = getattr(r, attr)
        if v is None:
            continue
        out[v] = out.get(v, 0) + 1
    return out
