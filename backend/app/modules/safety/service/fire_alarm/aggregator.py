"""消防报警分析 — 数据聚合（纯函数，无 DB 依赖）。

日报聚合（ticket 05）：统计分布 + 部门负责人映射。
月报聚合（原 ticket 06 周报，2026-09-22 改月报）：统计分布 + 部门负责人映射
+ recurring_patterns 重复问题识别（按楼栋/部位×报警类型聚合，count>=2 视为重复）。
get_natural_week_range（get_stats 本周 KPI 用）与 get_natural_month_range 并存。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
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
class FireAlarmMonthlyAgg:
    """月报聚合结果（自然月 1 日~月末）。"""

    month_start: date
    month_end: date
    records: list[FireAlarmRecord]
    total: int
    nature_distribution: dict[str, int]
    type_distribution: dict[str, int]
    department_distribution: dict[str, int]
    dept_leader_names: dict[str, str]
    # 月级特有：重复/集中问题（按 location+alarm_type 聚合，count>=2 视为重复）
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


def aggregate_monthly(
    records: list[FireAlarmRecord], month_start: date, month_end: date,
) -> FireAlarmMonthlyAgg:
    """聚合自然月（1 日~月末）报警记录 → 统计 + 重复/集中问题识别。

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

    return FireAlarmMonthlyAgg(
        month_start=month_start,
        month_end=month_end,
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

    部位名先归一化再分组，同一物理点位的变体写法合并为一条、次数相加
    （如「达巴雷帕4一38」「达巴雷帕4-38。」并入「达巴雷帕干燥间4-38」）；
    展示标签取簇内出现次数最多的原始写法（并列取先出现）。
    alarm_type 为 None 的记录不参与识别（无类型无法构成「×类型」重复模式）。
    每项: {"pattern": "<楼栋/部位>-<报警类型>", "count": n, "departments": [...]}
    按 count 降序、pattern 升序排列，保证输出稳定（prompts/渲染可复现）。
    """
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for r in records:
        alarm_type = r.alarm_type
        if not alarm_type:
            continue  # 无报警类型无法构成「×类型」重复模式
        place = _place_label(r.building, r.location)
        key = (_normalize_place(place), alarm_type)
        group = groups.setdefault(
            key,
            {"labels": Counter(), "count": 0, "departments": set()},
        )
        group["labels"][place] += 1
        group["count"] += 1
        if r.department:
            group["departments"].add(r.department)

    patterns = [
        {
            "pattern": f"{display}-{atype}",
            "count": g["count"],
            "departments": sorted(g["departments"]),
        }
        for (_norm, atype), g, display in _merge_variant_groups(groups)
        if g["count"] >= 2
    ]
    patterns.sort(key=lambda p: (-p["count"], p["pattern"]))
    return patterns


# 尾部标点/空白（归一化时剥掉；含全角句号、顿号等）
_TAIL_PUNCT = re.compile(r"[。．、，,；;：:！!？?~～\s]+$")
# 尾部点位编号（如「干燥间4-38」的 4-38）
_POINT_CODE = re.compile(r"(\d+-\d+)$")


def _normalize_place(place: str) -> str:
    """部位名归一化（重复问题分组键用，不用于展示）。

    NFKC 全角→半角（＃→#、４→4、－→-）；破折号族统一为 -；
    数字间的「一」视作连字符（4一38 → 4-38，不动「一层」这类量词）；
    去掉尾部标点与空白、压缩内部空白（A 栋 → A栋）。
    """
    s = unicodedata.normalize("NFKC", place or "")
    s = s.replace("—", "-").replace("–", "-").replace("―", "-").replace("‑", "-")
    s = re.sub(r"(?<=\d)一(?=\d)", "-", s)
    s = re.sub(r"\s+", "", s)
    return _TAIL_PUNCT.sub("", s)


def _split_place(place: str) -> tuple[str, str]:
    """「楼栋/部位」拆成 (楼栋, 部位)；无「/」时楼栋为空串。"""
    if "/" in place:
        building, _, loc = place.partition("/")
        return building, loc
    return "", place


def _same_point_variants(key_a: str, key_b: str) -> bool:
    """判断两个归一化部位名是否同一物理点位的变体写法（合并依据）。

    三条规则，均要求楼栋一致（跨楼栋绝不合并）：
    1. 归一化后完全一致；
    2. 短部位是长部位的子串且带点位编号（「洁净区4-1」⊂「1楼洁净区4-1」）；
    3. 尾部点位编号一致（如 4-38）且较短者去掉编号后的前缀被较长者包含
       （「达巴雷帕4-38」的「达巴雷帕」⊂「达巴雷帕干燥间」；纯编号
       「4-38」视作空前缀，并入同楼栋的完整写法）。
    """
    if key_a == key_b:
        return True
    building_a, loc_a = _split_place(key_a)
    building_b, loc_b = _split_place(key_b)
    if building_a != building_b:
        return False
    short, long = (loc_a, loc_b) if len(loc_a) <= len(loc_b) else (loc_b, loc_a)
    if len(short) >= 3 and _POINT_CODE.search(short) and short in long:
        return True
    code_a = _POINT_CODE.search(loc_a)
    code_b = _POINT_CODE.search(loc_b)
    if code_a and code_b and code_a.group(1) == code_b.group(1):
        prefix_a = loc_a[: code_a.start()]
        prefix_b = loc_b[: code_b.start()]
        short_prefix, long_prefix = sorted((prefix_a, prefix_b), key=len)
        if long_prefix and short_prefix in long_prefix:
            return True
    return False


def _merge_variant_groups(
    groups: dict[tuple[str, str], dict[str, Any]],
) -> list[tuple[tuple[str, str], dict[str, Any], str]]:
    """把互为变体写法的分组并成一簇（union-find），簇内次数相加。

    Returns:
        [(分组键, 合并后统计, 展示标签)]；展示标签取簇内出现次数最多的
        原始部位写法（Counter.most_common 并列时取先插入 = 先出现）。
    """
    items = list(groups.items())
    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            (place_i, type_i), _ = items[i]
            (place_j, type_j), _ = items[j]
            if type_i == type_j and _same_point_variants(place_i, place_j):
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    out: list[tuple[tuple[str, str], dict[str, Any], str]] = []
    for members in clusters.values():
        first_key = items[members[0]][0]
        labels: Counter = Counter()
        departments: set[str] = set()
        count = 0
        for m in members:
            g = items[m][1]
            labels.update(g["labels"])
            departments |= g["departments"]
            count += g["count"]
        # 展示标签：出现次数最多的原始写法；并列时优先「本身已是规范写法」
        # 的变体（如半角 14# 优先于全角 14＃），再按先出现；最终再过一遍
        # 归一化，去掉源表抄写噪音（尾部句号、全角字符等），不影响原始数据
        best_count = labels.most_common(1)[0][1]
        top = [lbl for lbl, c in labels.items() if c == best_count]
        display = next((lbl for lbl in top if _normalize_place(lbl) == lbl), top[0])
        out.append((
            first_key,
            {"count": count, "departments": departments},
            _normalize_place(display),
        ))
    return out


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
    （service.get_stats 共用，避免重复实现）。
    """
    monday = ref_date - timedelta(days=ref_date.weekday())  # weekday() 周一=0
    sunday = monday + timedelta(days=6)
    return monday, sunday


def get_natural_month_range(ref_date: date) -> tuple[date, date]:
    """返回 ref_date 所在自然月的 1 日与月末最后一天。"""
    month_start = ref_date.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    month_end = next_month - timedelta(days=1)
    return month_start, month_end
