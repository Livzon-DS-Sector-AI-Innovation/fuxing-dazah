"""保险到期口径计算（纯函数，单测固化口径；不做任何 IO）。

口径（2026-10-14 与需求方确认）：

- 前提：申请状态=已通过 且 仍在厂（进厂结束时间 ≥ 今日；已离厂不预警，
  进厂结束时间缺失按在厂处理——宁可多提醒不可漏）；
- 🔴 已过期：保险有效期至 < 今日；
- 🟡 3天内到期：今日 ≤ 保险有效期至 ≤ 今日+3（含两端边界日）；
- ⚪ 数据缺失：保险有效期至为空且仍在厂（按单位聚合，倒逼补录）；
- 同一单位同批人员同窗口的重复申请单（审批重提产生）合并为一条，人数不重复计。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.modules.safety.service.visitor_insurance.reader import (
    STATUS_APPROVED,
    VisitorNoticeView,
)

# 临期阈值（天）：保险有效期至落在 [今日, 今日+N] 内算临期
SOON_DAYS = 3

# 姓名分隔符兼容：中文逗号/顿号/句号/分号/空白（原始数据里全出现过）
_NAME_SPLIT = re.compile(r"[，,、。;；\s]+")


def normalize_names(raw: str) -> str:
    """原始姓名串 → 「、」连接的规范串（去空项；分隔符混乱的源数据归一）。"""
    return "、".join(p for p in _NAME_SPLIT.split((raw or "").strip()) if p)


@dataclass
class ExpiringGroup:
    """一条命中 🔴/🟡 预警的报备（重复申请单已合并）。"""

    company: str
    names: str
    people: int
    work_content: str
    work_scope: str
    entry_end: date | None
    insurance_end: date
    days_left: int  # 负数=已过期天数；0..SOON_DAYS=剩余天数


@dataclass
class MissingGroup:
    """⚪ 在厂但未填保险有效期——按单位聚合的一组报备。"""

    company: str
    notices: int
    people: int
    latest_entry_end: date | None  # 最晚「在厂至」（该单位还需在厂多久）
    work_contents: list[str] = field(default_factory=list)


@dataclass
class WarningResult:
    """一次口径计算的完整结果。"""

    today: date
    expired: list[ExpiringGroup]  # 按过期天数倒序（最严重在前）
    soon: list[ExpiringGroup]  # 按到期日升序（最先到期在前）
    missing: list[MissingGroup]  # 按人数倒序
    total_notices: int = 0  # 参与扫描的报备总数（已通过口径）
    active_notices: int = 0  # 其中仍在厂的报备数
    # 在厂报备中最近的未来到期（含已临期；无临期时的空日文案用）
    next_expiry: date | None = None
    next_expiry_company: str = ""


def _merge_key(v: VisitorNoticeView) -> tuple:
    """重复申请单合并键：单位+人员+进厂窗口+作业内容完全一致视为同批。"""
    return (
        v.company,
        normalize_names(v.names),
        v.entry_start,
        v.entry_end,
        (v.work_content or "").strip(),
    )


def _group_people(v: VisitorNoticeView) -> int:
    """合并后人数：预计人数与姓名清单取大（两者缺一时互为兜底）。"""
    named = len([p for p in _NAME_SPLIT.split((v.names or "").strip()) if p])
    return max(v.people_count, named)


def classify(views: list[VisitorNoticeView], today: date) -> WarningResult:
    """全量视图 → 三类预警结果（纯函数；排序契约见 WarningResult 字段注释）。"""
    deadline = today + timedelta(days=SOON_DAYS)
    result = WarningResult(today=today, expired=[], soon=[], missing=[])

    # ① 已通过 + 在厂 + 重复申请单合并（首条为准）
    merged: dict[tuple, VisitorNoticeView] = {}
    for v in views:
        if v.status and v.status != STATUS_APPROVED:
            continue
        result.total_notices += 1
        if v.entry_end is not None and v.entry_end < today:
            continue  # 已离厂：保险过期与否都不再构成在厂风险
        result.active_notices += 1
        key = _merge_key(v)
        if key not in merged:
            merged[key] = v

    # ② 按保险有效期分流（顺带记录最近的未来到期，空日文案用）
    missing_by_company: dict[str, list[VisitorNoticeView]] = {}
    for v in merged.values():
        if v.insurance_end is None:
            missing_by_company.setdefault(v.company, []).append(v)
        elif v.insurance_end >= today and (
            result.next_expiry is None or v.insurance_end < result.next_expiry
        ):
            result.next_expiry = v.insurance_end
            result.next_expiry_company = v.company
        if v.insurance_end is not None and v.insurance_end < today:
            result.expired.append(ExpiringGroup(
                company=v.company,
                names=normalize_names(v.names),
                people=_group_people(v),
                work_content=(v.work_content or "").strip(),
                work_scope=(v.work_scope or "").strip(),
                entry_end=v.entry_end,
                insurance_end=v.insurance_end,
                days_left=(v.insurance_end - today).days,  # 负数
            ))
        elif v.insurance_end is not None and v.insurance_end <= deadline:
            result.soon.append(ExpiringGroup(
                company=v.company,
                names=normalize_names(v.names),
                people=_group_people(v),
                work_content=(v.work_content or "").strip(),
                work_scope=(v.work_scope or "").strip(),
                entry_end=v.entry_end,
                insurance_end=v.insurance_end,
                days_left=(v.insurance_end - today).days,
            ))

    result.expired.sort(key=lambda g: g.days_left)  # 负得越多越靠前
    result.soon.sort(key=lambda g: g.insurance_end)

    for company, items in missing_by_company.items():
        ends = [v.entry_end for v in items if v.entry_end is not None]
        contents: list[str] = []
        for v in items:
            content = (v.work_content or "").strip()
            if content and content not in contents:
                contents.append(content)
        result.missing.append(MissingGroup(
            company=company,
            notices=len(items),
            people=sum(_group_people(v) for v in items),
            latest_entry_end=max(ends) if ends else None,
            work_contents=contents,
        ))
    result.missing.sort(key=lambda g: (-g.people, g.company))

    return result
