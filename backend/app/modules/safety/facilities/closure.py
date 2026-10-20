"""校验任务状态迁移（闭环/取消/重开）——事件通道、对账通道与管理员干预共用。

闭环铁律（DESIGN §4.1/§4.3）：closed 的前置条件是台账行锚点已前移
（engine.anchor_advanced 纯函数判定），任何通道都不允许绕过；manual 关闭/
取消必填原因并单独留痕。所有迁移写 facility_task_events（append-only），
迁移后经 notifier 钩子刷新所属批次卡（票 05 实装，默认空实现）。
事务边界归调用方。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.facilities.engine import anchor_advanced, anchor_field_of_task
from app.modules.safety.facilities.ledger import LedgerRowView
from app.modules.safety.models import (
    TRIGGER_EVENT,
    TRIGGER_MANUAL,
    TRIGGER_POLL,
    FacilityCheckTask,
    FacilityNoticeBatch,
    FacilityTaskEvent,
)

logger = logging.getLogger(__name__)


class ClosureNotifier(Protocol):
    """状态迁移通知钩子（票 05 实装滚动批次卡刷新；默认空实现）。"""

    async def on_tasks_changed(
        self, session: AsyncSession, departments: list[str]
    ) -> None: ...


class _NoopNotifier:
    async def on_tasks_changed(
        self, session: AsyncSession, departments: list[str]
    ) -> None:
        return None


def _now() -> datetime:
    return datetime.now(UTC)


async def open_tasks_for_row(
    session: AsyncSession, biz_type: str, ledger_key: str
) -> list[FacilityCheckTask]:
    """定位某台账行的全部 open（issued）任务。"""
    rows = await session.execute(
        select(FacilityCheckTask).where(
            FacilityCheckTask.biz_type == biz_type,
            FacilityCheckTask.ledger_key == ledger_key,
            FacilityCheckTask.status == "issued",
            FacilityCheckTask.is_deleted.is_(False),
        )
    )
    return list(rows.scalars().all())


async def close_task_if_advanced(
    session: AsyncSession,
    task: FacilityCheckTask,
    view: LedgerRowView,
    *,
    trigger: str,
    operator: str = "system",
) -> bool:
    """锚点前移判定命中才闭环（唯一闭环入口的共用实现）。

    只改无关列时 anchor_advanced 不命中 → 返回 False，任务保持 issued。
    """
    if task.status != "issued":
        return False
    anchor_field = anchor_field_of_task(task)
    current_anchor = view.anchor_value(anchor_field)
    if not anchor_advanced(
        due_date=task.due_date,
        issued_on=task.issued_on,
        current_anchor=current_anchor,
        current_last=view.last_date,
        # 规则2（上次日期≥派发日）仅主锚点任务适用：换药/报废更换任务只认
        # 自身到期列前移，不被「上次检查日期」更新连坐闭环
        count_last_rule=anchor_field == "next_date",
    ):
        return False
    task.status = "closed"
    task.closed_trigger = trigger
    task.closed_at = _now()
    session.add(
        FacilityTaskEvent(
            task_id=task.id,
            event_type="closed",
            operator=operator,
            closed_trigger=trigger,
            payload={
                "anchor_before": task.anchor_at_dispatch.isoformat(),
                "anchor_after": (
                    current_anchor.isoformat() if current_anchor else None
                ),
                "last_date": view.last_date.isoformat() if view.last_date else None,
            },
        )
    )
    logger.info(
        "设施校验任务自动闭环: task=%s biz=%s no=%s trigger=%s",
        task.id, task.biz_type, task.equipment_no, trigger,
    )
    return True


async def cancel_task(
    session: AsyncSession,
    task: FacilityCheckTask,
    *,
    trigger: str,
    reason: str,
    operator: str = "system",
) -> None:
    """取消任务（行删除/停用=trigger event|poll；管理员手动=manual 必填原因）。"""
    if task.status == "cancelled":
        return
    task.status = "cancelled"
    task.closed_trigger = trigger
    task.closed_reason = reason
    task.closed_at = _now()
    if trigger == TRIGGER_MANUAL:
        task.closed_by = operator
    session.add(
        FacilityTaskEvent(
            task_id=task.id,
            event_type="cancelled",
            operator=operator,
            closed_trigger=trigger,
            payload={"reason": reason},
        )
    )


async def reopen_task(
    session: AsyncSession,
    task: FacilityCheckTask,
    *,
    operator: str,
    reason: str | None = None,
) -> bool:
    """误关恢复（closed/cancelled → issued，事件留痕）。

    所属批次已归档时清空 batch_id（新周期派发/升级时重新并卡）。
    """
    if task.status == "issued":
        return False
    task.status = "issued"
    task.closed_trigger = None
    task.closed_reason = None
    task.closed_at = None
    task.closed_by = None
    if task.batch_id is not None:
        batch = await session.get(FacilityNoticeBatch, task.batch_id)
        if batch is None or batch.status != "open":
            task.batch_id = None  # 批次已归档：下次派发/升级重新并卡
    session.add(
        FacilityTaskEvent(
            task_id=task.id,
            event_type="reopened",
            operator=operator,
            payload={"reason": reason} if reason else None,
        )
    )
    return True


async def process_row_change(
    session: AsyncSession,
    biz_type: str,
    record_id: str,
    *,
    deleted: bool,
    view: LedgerRowView | None,
    trigger: str = TRIGGER_EVENT,
    notifier: ClosureNotifier | None = None,
    today: date | None = None,
) -> dict[str, int]:
    """单行变更处理（事件实时通道与测试共用）：

    - 行删除 / 行停用 → open 任务全量 cancelled；
    - 行在且在用 → 逐任务锚点前移判定，命中即 closed。
    返回 {"closed": n, "cancelled": n}；departments 变化经 notifier 上抛。
    """
    notifier = notifier or _NoopNotifier()
    tasks = await open_tasks_for_row(session, biz_type, record_id)
    closed = cancelled = 0
    departments: list[str] = []
    for task in tasks:
        inactive = deleted or view is None or not view.active
        if inactive:
            reason = (
                "台账行已删除" if deleted or view is None
                else f"台账状态停用：{view.status or '停用'}"
            )
            await cancel_task(session, task, trigger=trigger, reason=reason)
            cancelled += 1
        elif view is not None and await close_task_if_advanced(
            session, task, view, trigger=trigger
        ):
            closed += 1
        else:
            continue
        if task.department and task.department not in departments:
            departments.append(task.department)
    if departments:
        await notifier.on_tasks_changed(session, departments)
    return {"closed": closed, "cancelled": cancelled}


__all__ = [
    "TRIGGER_EVENT",
    "TRIGGER_MANUAL",
    "TRIGGER_POLL",
    "ClosureNotifier",
    "cancel_task",
    "close_task_if_advanced",
    "open_tasks_for_row",
    "process_row_change",
    "reopen_task",
]
