"""消防报警分析 — 数据聚合（纯函数，无 DB 依赖）。

日报聚合（ticket 05）：统计分布 + 部门负责人映射。
周报聚合（ticket 06）：统计分布 + 部门负责人映射 + recurring_patterns 重复问题识别
（按楼栋/部位×报警类型聚合，count>=2 视为重复）。
get_natural_week_range 由 service.py 的私有辅助上移而来（避免重复实现）。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.modules.safety.models import FireAlarmRecord


@dataclass
class FireAlarmDailyAgg:
    """日报聚合结果。"""

    target_date: date
    records: list[FireAlarmRecord]
    total: int
    nature_distribution: dict[str, int]
    type_distribution: dict[str, int]
    department_distribution: dict[str, int]
    dept_leader_names: dict[str, str]  # department → leader_name（@提及用）
    dimension_distribution: dict[str, int] = field(default_factory=dict)  # AI 维度 → 数量


@dataclass
class FireAlarmWeeklyAgg:
    """周报聚合结果（ticket 06 使用，本期仅定义结构）。"""

    week_start: date
    week_end: date
    records: list[FireAlarmRecord]
    total: int
    nature_distribution: dict[str, int]
    type_distribution: dict[str, int]
    department_distribution: dict[str, int]
    dept_leader_names: dict[str, str]
    # 周级特有：重复/集中问题（按 location+alarm_type 聚合，count>=2 视为重复）
    recurring_patterns: list[dict[str, Any]] = field(
        default_factory=list
    )  # [{"pattern": "X楼栋-Y类型", "count": n, "departments": [...]}]
    dimension_distribution: dict[str, int] = field(default_factory=dict)  # AI 维度 → 数量


def aggregate_daily(
    records: list[FireAlarmRecord], target_date: date,
) -> FireAlarmDailyAgg:
    """聚合当日报警记录 → 统计分布 + 部门负责人映射。

    - 分布：报警性质 / 报警类型 / AI 维度 / 部门 → 数量（值为 None 的字段不计入）
    - dept_leader_names：department → department_leader_name（首个非空负责人，
      同名负责人多部门时以部门为准——@提及解析用姓名，跨部门同名场景由
      IdentityResolver department_hint 消歧）
    """
    nature: dict[str, int] = defaultdict(int)
    types: dict[str, int] = defaultdict(int)
    department: dict[str, int] = defaultdict(int)
    dept_leader: dict[str, str] = {}

    for r in records:
        if r.alarm_nature:
            nature[r.alarm_nature] += 1
        if r.alarm_type:
            types[r.alarm_type] += 1
        if r.department:
            department[r.department] += 1
            leader = r.department_leader_name
            if leader and r.department not in dept_leader:
                dept_leader[r.department] = leader

    return FireAlarmDailyAgg(
        target_date=target_date,
        records=list(records),
        total=len(records),
        nature_distribution=dict(nature),
        type_distribution=dict(types),
        department_distribution=dict(department),
        dept_leader_names=dept_leader,
    )


def aggregate_weekly(
    records: list[FireAlarmRecord], week_start: date, week_end: date,
) -> FireAlarmWeeklyAgg:
    """聚合自然周（周一~周日）报警记录 → 统计 + 重复/集中问题识别。

    - 分布与 dept_leader_names 口径同 aggregate_daily（值为 None 的字段不计入）
    - 重复/集中问题（backend-design.md §2.2.3）：按（楼栋/部位 × 报警类型）聚合，
      count >= 2 视为重复。alarm_type 为 None 的记录不参与识别（无类型无法构成
      「×类型」重复模式）。
      每项: {"pattern": "<楼栋/部位>-<报警类型>", "count": n, "departments": [...]}
      按 count 降序、pattern 升序排列，保证输出稳定（prompts/渲染可复现）。
    """
    nature: dict[str, int] = defaultdict(int)
    types: dict[str, int] = defaultdict(int)
    department: dict[str, int] = defaultdict(int)
    dept_leader: dict[str, str] = {}

    for r in records:
        if r.alarm_nature:
            nature[r.alarm_nature] += 1
        if r.alarm_type:
            types[r.alarm_type] += 1
        if r.department:
            department[r.department] += 1
            leader = r.department_leader_name
            if leader and r.department not in dept_leader:
                dept_leader[r.department] = leader

    return FireAlarmWeeklyAgg(
        week_start=week_start,
        week_end=week_end,
        records=list(records),
        total=len(records),
        nature_distribution=dict(nature),
        type_distribution=dict(types),
        department_distribution=dict(department),
        dept_leader_names=dept_leader,
        recurring_patterns=_find_recurring_patterns(records),
    )


def _find_recurring_patterns(records: list[FireAlarmRecord]) -> list[dict[str, Any]]:
    """重复/集中问题识别：按（楼栋/部位 × 报警类型）聚合，count>=2 视为重复。

    pattern 命名：部位优先取楼栋，其次部位，两者皆有时「楼栋/部位」，均无则
    「部位待确认」（如「1号装置/压缩机房-火灾报警」）；departments 为涉及的
    去重部门列表（升序）。
    """
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for r in records:
        alarm_type = r.alarm_type
        if not alarm_type:
            continue  # 无报警类型无法构成「×类型」重复模式
        place = _place_label(r.building, r.location)
        group = groups.setdefault(
            (place, alarm_type),
            {"pattern": f"{place}-{alarm_type}", "count": 0, "departments": set()},
        )
        group["count"] += 1
        if r.department:
            group["departments"].add(r.department)

    patterns = [
        {
            "pattern": g["pattern"],
            "count": g["count"],
            "departments": sorted(g["departments"]),
        }
        for g in groups.values()
        if g["count"] >= 2
    ]
    patterns.sort(key=lambda p: (-p["count"], p["pattern"]))
    return patterns


def _place_label(building: str | None, location: str | None) -> str:
    """楼栋/部位展示标签：楼栋优先，两者皆有时「楼栋/部位」，均无时「部位待确认」。"""
    if building and location:
        return f"{building}/{location}"
    if building:
        return building
    if location:
        return location
    return "部位待确认"


def get_natural_week_range(ref_date: date) -> tuple[date, date]:
    """返回 ref_date 所在自然周的周一与周日。

    原为 service.py 的 _get_natural_week_range 私有辅助，上移为本模块公开函数
    （service.get_stats / generate_weekly_report 共用，避免重复实现）。
    """
    monday = ref_date - timedelta(days=ref_date.weekday())  # weekday() 周一=0
    sunday = monday + timedelta(days=6)
    return monday, sunday
