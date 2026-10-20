"""校验任务查询与聚合（任务中心 API 数据层）。

SQL 只做基础过滤（status/department/biz_type/group_key），剩余天数/逾期在
Python 层按今日派生（today 可注入）；summary 分桶单点计算，与批次卡口径
一致（closed/total 分组进度）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.facilities.ledger import BIZ_LABELS
from app.modules.safety.models import FacilityCheckTask, FacilityTaskEvent


def _bj_today() -> date:
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def task_dict(t: FacilityCheckTask, *, today: date) -> dict[str, Any]:
    remaining = (t.due_date - today).days if t.status == "issued" else None
    return {
        "id": str(t.id),
        "biz_type": t.biz_type,
        "biz_label": BIZ_LABELS.get(t.biz_type, t.biz_type),
        "ledger_key": t.ledger_key,
        "equipment_no": t.equipment_no,
        "equipment_name": t.equipment_name,
        "department": t.department,
        "location": t.location,
        "task_kind": t.task_kind,
        "task_subtype": t.task_subtype,
        "group_key": t.group_key,
        "due_date": t.due_date.isoformat(),
        "lead_days": t.lead_days,
        "status": t.status,
        "assignee_name": t.assignee_name,
        "batch_id": str(t.batch_id) if t.batch_id else None,
        "anchor_at_dispatch": t.anchor_at_dispatch.isoformat(),
        "issued_on": t.issued_on.isoformat(),
        "closed_trigger": t.closed_trigger,
        "closed_reason": t.closed_reason,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        "remind_count": t.remind_count,
        "remaining_days": remaining,
        "overdue": remaining is not None and remaining < 0,
    }


def event_dict(e: FacilityTaskEvent) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "task_id": str(e.task_id),
        "event_type": e.event_type,
        "operator": e.operator,
        "closed_trigger": e.closed_trigger,
        "payload": e.payload,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


async def list_tasks(
    session: AsyncSession,
    *,
    status: str | None = None,
    department: str | None = None,
    biz_type: str | None = None,
    group_key: str | None = None,
    overdue: bool | None = None,
    page: int = 1,
    page_size: int = 20,
    today: date | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """任务列表（SQL 过滤 + Python 派生字段过滤 overdue + 内存分页）。"""
    today = today or _bj_today()
    stmt = select(FacilityCheckTask).where(FacilityCheckTask.is_deleted.is_(False))
    if status:
        stmt = stmt.where(FacilityCheckTask.status == status)
    if department:
        stmt = stmt.where(FacilityCheckTask.department == department)
    if biz_type:
        stmt = stmt.where(FacilityCheckTask.biz_type == biz_type)
    if group_key:
        stmt = stmt.where(FacilityCheckTask.group_key == group_key)
    rows = list((await session.execute(stmt)).scalars().all())
    rows.sort(key=lambda t: (t.status != "issued", t.due_date))
    items = [task_dict(t, today=today) for t in rows]
    if overdue:
        items = [i for i in items if i["overdue"]]
    total = len(items)
    start = max(1, int(page)) - 1
    size = min(max(1, int(page_size)), 100)
    return items[start : start + size], total


async def task_summary(
    session: AsyncSession, *, today: date | None = None
) -> dict[str, Any]:
    """分桶统计：全局计数 + 按部门/分组聚合（分组进度=已闭环/总数）。"""
    today = today or _bj_today()
    rows = list(
        (
            await session.execute(
                select(FacilityCheckTask).where(FacilityCheckTask.is_deleted.is_(False))
            )
        ).scalars().all()
    )
    counts = {"issued": 0, "closed": 0, "cancelled": 0}
    overdue = 0
    by_department: dict[str, dict[str, Any]] = {}
    for t in rows:
        counts[t.status] = counts.get(t.status, 0) + 1
        if t.status == "issued" and t.due_date < today:
            overdue += 1
        if t.status == "cancelled":
            continue  # 取消任务不进部门/分组进度（closed/total 才能满绿）
        dept = t.department or "未填写部门"
        bucket = by_department.setdefault(
            dept,
            {"department": dept, "total": 0, "closed": 0, "open": 0, "groups": {}},
        )
        bucket["total"] += 1
        if t.status == "closed":
            bucket["closed"] += 1
        elif t.status == "issued":
            bucket["open"] += 1
        group = bucket["groups"].setdefault(
            t.group_key, {"group_key": t.group_key, "total": 0, "closed": 0}
        )
        group["total"] += 1
        if t.status == "closed":
            group["closed"] += 1
    for bucket in by_department.values():
        bucket["groups"] = sorted(bucket["groups"].values(), key=lambda g: -g["total"])
    return {
        "total": len(rows),
        "open": counts["issued"],
        "closed": counts["closed"],
        "cancelled": counts["cancelled"],
        "overdue": overdue,
        "by_department": sorted(
            by_department.values(), key=lambda b: (-b["open"], b["department"])
        ),
    }


async def task_detail(
    session: AsyncSession, task_id: uuid.UUID, *, today: date | None = None
) -> dict[str, Any] | None:
    """单任务详情 + 事件流时间线（时间正序）。"""
    today = today or _bj_today()
    task = await session.get(FacilityCheckTask, task_id)
    if task is None or task.is_deleted:
        return None
    events = list(
        (
            await session.execute(
                select(FacilityTaskEvent)
                .where(FacilityTaskEvent.task_id == task_id)
                .order_by(FacilityTaskEvent.created_at.asc(), FacilityTaskEvent.id.asc())
            )
        ).scalars().all()
    )
    return {
        "task": task_dict(task, today=today),
        "events": [event_dict(e) for e in events],
    }
