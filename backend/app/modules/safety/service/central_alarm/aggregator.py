"""中控报警数据聚合（ticket 03 统计复用 + ticket 05 日报聚合；周期报告聚合）。

纯函数，无 DB 依赖；用于自然周/月计算、日报统计分布与车间分组、周报/月报指标。
类型接缝（central-alarm-direct）：接受 ORM 记录或直读视图对象（字段同名）。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.safety.service.central_alarm.reader import (
        CentralAlarmRecordLike,
    )

# 周期报告口径（与 renderer._PATTERN_LABEL 同源；聚合层只认英文枚举）
FALSE_ALARM_PATTERN = "false_alarm"
# kind → 中文报告名（renderer/prompts/service 统一取用，防散布）
PERIOD_KIND_LABEL: dict[str, str] = {"weekly": "周报", "monthly": "月报"}


def period_kind_label(kind: str) -> str:
    """kind → 中文报告名（未知 kind 回退「周期报告」）。"""
    return PERIOD_KIND_LABEL.get(kind, "周期报告")


@dataclass
class CentralAlarmDailyAgg:
    """日报聚合结果。"""

    target_date: date
    records: list[CentralAlarmRecordLike] = field(default_factory=list)
    total: int = 0
    workshop_distribution: dict[str, int] = field(default_factory=dict)
    post_distribution: dict[str, int] = field(default_factory=dict)
    alarm_type_distribution: dict[str, int] = field(default_factory=dict)
    pattern_distribution: dict[str, int] = field(default_factory=dict)
    dimension_distribution: dict[str, int] = field(default_factory=dict)
    # 车间分组（报表按车间分节）
    workshop_groups: dict[str, list[CentralAlarmRecordLike]] = field(
        default_factory=dict
    )


@dataclass
class PrevPeriodStats:
    """上一周期环比统计（镜像模式含 AI 字段；直读模式 false_alarm_ratio 为 None）。"""

    total: int = 0
    days: int = 0
    daily_avg: float = 0.0
    analyzed_count: int = 0
    false_alarm_ratio: float | None = None


@dataclass
class CentralAlarmPeriodAgg:
    """周报/月报聚合结果（kind=weekly/monthly）。"""

    kind: str
    period_start: date
    period_end: date
    days: int = 0
    records: list[CentralAlarmRecordLike] = field(default_factory=list)
    total: int = 0
    daily_avg: float = 0.0
    daily_counts: dict[date, int] = field(default_factory=dict)
    workshop_distribution: dict[str, int] = field(default_factory=dict)
    post_distribution: dict[str, int] = field(default_factory=dict)
    alarm_type_distribution: dict[str, int] = field(default_factory=dict)
    pattern_distribution: dict[str, int] = field(default_factory=dict)
    dimension_distribution: dict[str, int] = field(default_factory=dict)
    # 高频报警点 Top10：(workshop, post, alarm_type, count) 按次数降序
    top_hotspots: list[tuple[str, str, str, int]] = field(default_factory=list)
    # 无效报警（AI 判定误报）口径：分母=已分析数（覆盖率见 analyzed_count/total）
    analyzed_count: int = 0
    false_alarm_count: int = 0
    false_alarm_ratio: float | None = None
    # 上一周期环比（未提供为 None → 渲染「—」）
    prev: PrevPeriodStats | None = None


def get_natural_week_range(ref_date: date) -> tuple[date, date]:
    """返回 ref_date 所在自然周的周一与周日（周一=0）。"""
    monday = ref_date - timedelta(days=ref_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def prev_natural_week_range(ref_date: date) -> tuple[date, date]:
    """ref_date 所在周的上一完整自然周（周一~周日）。"""
    return get_natural_week_range(ref_date - timedelta(days=7))


def get_natural_month_range(ref_date: date) -> tuple[date, date]:
    """返回 ref_date 所在自然月的 1 日与月末最后一天（跨年正确）。"""
    month_start = ref_date.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    return month_start, next_month - timedelta(days=1)


def prev_natural_month_range(ref_date: date) -> tuple[date, date]:
    """ref_date 所在月的上一完整自然月（1 日~月末，跨年正确）。"""
    prev_last_day = ref_date.replace(day=1) - timedelta(days=1)
    return get_natural_month_range(prev_last_day)


def _bj_date_of(record: CentralAlarmRecordLike) -> date | None:
    """记录报警时间的北京时间日期（alarm_date 为 UTC；空返回 None）。"""
    if record.alarm_date is None:
        return None
    return (record.alarm_date + timedelta(hours=8)).date()


def _ratio(numerator: int, denominator: int) -> float | None:
    """占比（分母 0 返回 None）；四舍五入 4 位。"""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def build_prev_stats(
    records: Sequence[CentralAlarmRecordLike], days: int,
) -> PrevPeriodStats:
    """由上一周期记录构建环比统计（无效比例依赖已落库/已回填的 AI 字段）。"""
    stats = PrevPeriodStats(days=days, total=len(records))
    analyzed = [r for r in records if r.ai_analyzed_at is not None]
    stats.analyzed_count = len(analyzed)
    stats.daily_avg = round(len(records) / days, 1) if days > 0 else 0.0
    false_n = sum(1 for r in analyzed if r.ai_pattern == FALSE_ALARM_PATTERN)
    stats.false_alarm_ratio = _ratio(false_n, len(analyzed))
    return stats


def aggregate_period(
    records: Sequence[CentralAlarmRecordLike], *,
    kind: str,
    period_start: date,
    period_end: date,
    prev_records: Sequence[CentralAlarmRecordLike] | None = None,
    prev_days: int | None = None,
) -> CentralAlarmPeriodAgg:
    """聚合一个完整周期（自然周/自然月）的报警记录 → 周期指标。

    - 日均报警率 = 总数 ÷ 周期天数（含起止日）
    - daily_counts 按北京时间日期聚合（值为 None 的 alarm_date 不计）
    - 高频报警点 = (workshop, post, ai_alarm_type) 计数降序 Top10（不限异常模式）
    - 无效报警比例 = ai_pattern=误报 ÷ 已分析数（已分析 0 → None）
    - prev_records 提供时构建上一周期环比块
    """
    agg = CentralAlarmPeriodAgg(
        kind=kind, period_start=period_start, period_end=period_end,
        records=list(records),
    )
    agg.days = (period_end - period_start).days + 1
    agg.total = len(records)
    agg.daily_avg = round(agg.total / agg.days, 1) if agg.days else 0.0

    hotspots: Counter[tuple[str, str, str]] = Counter()
    daily_counts: dict[date, int] = defaultdict(int)
    for r in records:
        bj_day = _bj_date_of(r)
        if bj_day is not None:
            daily_counts[bj_day] += 1
        if r.workshop:
            agg.workshop_distribution[r.workshop] = (
                agg.workshop_distribution.get(r.workshop, 0) + 1
            )
        if r.post:
            agg.post_distribution[r.post] = agg.post_distribution.get(r.post, 0) + 1
        if r.ai_alarm_type:
            agg.alarm_type_distribution[r.ai_alarm_type] = (
                agg.alarm_type_distribution.get(r.ai_alarm_type, 0) + 1
            )
        if r.ai_pattern:
            agg.pattern_distribution[r.ai_pattern] = (
                agg.pattern_distribution.get(r.ai_pattern, 0) + 1
            )
        if r.ai_dimension:
            agg.dimension_distribution[r.ai_dimension] = (
                agg.dimension_distribution.get(r.ai_dimension, 0) + 1
            )
        if r.ai_analyzed_at is not None:
            agg.analyzed_count += 1
            if r.ai_pattern == FALSE_ALARM_PATTERN:
                agg.false_alarm_count += 1
        hotspots[(
            r.workshop or "?", r.post or "?", r.ai_alarm_type or "其他",
        )] += 1

    agg.daily_counts = dict(daily_counts)
    agg.false_alarm_ratio = _ratio(agg.false_alarm_count, agg.analyzed_count)
    agg.top_hotspots = [
        (ws, post, atype, cnt)
        for (ws, post, atype), cnt in sorted(
            hotspots.items(), key=lambda kv: (-kv[1], kv[0]),
        )[:10]
    ]
    if prev_records is not None:
        days = prev_days if prev_days and prev_days > 0 else max(len(prev_records), 1)
        agg.prev = build_prev_stats(prev_records, days)
    return agg


def period_window_utc(period_start: date, period_end: date) -> tuple[datetime, datetime]:
    """周期窗口的 UTC 边界（北京时间 period_start 00:00 ~ period_end 次日 00:00，左闭右开）。"""
    utc_start = datetime.combine(period_start, time.min, tzinfo=UTC) - timedelta(hours=8)
    utc_end = (
        datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=UTC)
        - timedelta(hours=8)
    )
    return utc_start, utc_end


def aggregate_daily(
    records: Sequence[CentralAlarmRecordLike], target_date: date,
) -> CentralAlarmDailyAgg:
    """聚合当日报警记录 → 统计分布 + 按车间分组。

    分布统计基于记录上已有的 AI 分析字段（ai_alarm_type/ai_pattern/ai_dimension）与
    车间/岗位字段；值为 None 的不计入。车间分组按 workshop 键分组。
    """
    agg = CentralAlarmDailyAgg(target_date=target_date, records=list(records))
    agg.total = len(records)
    workshop_groups: dict[str, list[CentralAlarmRecordLike]] = {}
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


def _count_by(
    records: list[CentralAlarmRecordLike], attr: str,
) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        v = getattr(r, attr)
        if v is None:
            continue
        out[v] = out.get(v, 0) + 1
    return out
