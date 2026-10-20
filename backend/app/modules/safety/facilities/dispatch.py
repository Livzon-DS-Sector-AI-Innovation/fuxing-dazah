"""设施校验任务派发编排（每日 08:10）+ 对账兜底。

链路（DESIGN §4.2/§4.3 兜底通道）：
strict 直读三台账 → 到期筛选（engine.select_due）→ 幂等建任务（唯一键
ON CONFLICT 语义 + issued 跳过；冗余快照 + anchor_at_dispatch + issued_on）
→ 责任人解析链（owner → responsible_mapping 归口 → IdentityResolver →
部门负责人兜底；失败告警不丢任务）→ 对账（行删/停用 → cancelled(poll)；
锚点前移 → closed(poll)）→ 通知钩子（票 05 接批次卡）+ 速递格子（票 05）。

无连接语义：三台账全部未配置 → no_source=True（调度器如实留痕，不假成功）；
部分已配置但读取失败 → 聚合上抛（调度器标 failed 走补发窗口重试）。
事务边界归调用方（调度器 commit / 测试回滚）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.facilities.engine import (
    DueCandidate,
    anchor_advanced,
    anchor_field_of_task,
    select_due,
)
from app.modules.safety.facilities.ledger import (
    BIZ_ACCESSORY,
    BIZ_FIRE,
    BIZ_SPECIAL,
    LEAD_DAYS,
    LedgerRowView,
)
from app.modules.safety.facilities.reader import FacilitiesLedgerReader
from app.modules.safety.models import (
    TRIGGER_POLL,
    FacilityCheckTask,
    FacilityTaskEvent,
)
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.responsible_mapping import effective_responsible_person

logger = logging.getLogger(__name__)

BIZ_TYPES: tuple[str, ...] = (BIZ_ACCESSORY, BIZ_FIRE, BIZ_SPECIAL)


def _bj_today() -> date:
    """北京时间今天（与 daily_digest/domain_pages 同口径）。"""
    return (datetime.now(UTC) + timedelta(hours=8)).date()


class OwnerResolver(Protocol):
    """责任人解析协议（真实实现=IdentityResolver；测试注入替身）。"""

    async def resolve_by_name(
        self, name: str, department_hint: str | None = None
    ) -> Any | None: ...

    async def resolve_department_leader(
        self, department_name: str
    ) -> Any | None: ...


class DispatchNotifier(Protocol):
    """派发结果通知钩子（票 05 实装滚动批次卡；默认空实现）。"""

    async def on_dispatched(
        self, session: AsyncSession, departments: list[str], *, today: date
    ) -> None: ...


class _NoopNotifier:
    async def on_dispatched(
        self, session: AsyncSession, departments: list[str], *, today: date
    ) -> None:
        return None


@dataclass
class DispatchResult:
    """单次派发运行统计（日志/留痕/测试断言共用）。"""

    fetched_rows: dict[str, int] = field(default_factory=dict)  # biz -> 行数
    created: int = 0
    skipped_existing: int = 0
    reconciled_closed: int = 0
    reconciled_cancelled: int = 0
    unresolved_owner: int = 0
    incomplete_rows: int = 0
    digest_pushed: bool | None = None
    no_source: bool = False
    departments: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"rows={self.fetched_rows} created={self.created} "
            f"skipped={self.skipped_existing} closed={self.reconciled_closed} "
            f"cancelled={self.reconciled_cancelled} "
            f"unresolved_owner={self.unresolved_owner} "
            f"incomplete={self.incomplete_rows} digest={self.digest_pushed} "
            f"no_source={self.no_source}"
        )


async def _resolve_assignee(
    resolver: OwnerResolver | None, view: LedgerRowView
) -> tuple[str | None, str | None]:
    """责任人解析链：owner（含部门归口覆盖）→ 部门负责人兜底。

    返回 (open_id, name)；全链失败返回 (None, None)——任务照建不丢，
    由 unresolved_owner 计数曝光（速递格子/日志告警）。
    """
    if resolver is None:
        return None, None
    owner_name = effective_responsible_person(view.department, view.owner)
    if owner_name:
        person = await resolver.resolve_by_name(owner_name, department_hint=view.department)
        if person is not None and getattr(person, "open_id", ""):
            return person.open_id, getattr(person, "name", None) or owner_name
    if view.department:
        leader = await resolver.resolve_department_leader(view.department)
        if leader is not None and getattr(leader, "open_id", ""):
            return leader.open_id, getattr(leader, "name", None)
    return None, None


def _task_values(cand: DueCandidate, today: date) -> dict[str, Any]:
    view = cand.view
    return {
        "biz_type": view.biz_type,
        "ledger_key": view.record_id,
        "equipment_no": view.equipment_no,
        "equipment_name": view.name,
        "department": view.department,
        "location": view.location,
        "task_kind": cand.task_kind,
        "due_date": cand.due_date,
        "lead_days": LEAD_DAYS[view.biz_type],
        "group_key": cand.group_key,
        "task_subtype": cand.task_subtype,
        "anchor_at_dispatch": cand.due_date,
        "issued_on": today,
    }


async def _issue_tasks(
    session: AsyncSession,
    candidates: list[DueCandidate],
    resolver: OwnerResolver | None,
    today: date,
    result: DispatchResult,
) -> list[FacilityCheckTask]:
    """幂等建任务（DESIGN §4.2：已有同键且 status=issued 的跳过）。

    与唯一索引（partial: is_deleted=false and status='issued'）同口径：
    cancelled（行失效）/closed（锚点已前移）不阻塞同物同周期重派。
    SELECT-then-INSERT 在调度器 per-job 锁的单进程语义下无并发窗口；
    唯一索引兜底极端并发（冲突即 IntegrityError 上抛标 failed 走补发）。
    """
    existing_pairs: set[tuple[str, str, date]] = set()
    if candidates:
        keys = {c.view.record_id for c in candidates}
        rows = await session.execute(
            select(FacilityCheckTask).where(
                FacilityCheckTask.is_deleted.is_(False),
                FacilityCheckTask.status == "issued",
                FacilityCheckTask.ledger_key.in_(keys),
            )
        )
        for t in rows.scalars():
            existing_pairs.add((t.biz_type, t.ledger_key, t.due_date))

    created: list[FacilityCheckTask] = []
    for cand in candidates:
        pair = (cand.view.biz_type, cand.view.record_id, cand.due_date)
        if pair in existing_pairs:
            result.skipped_existing += 1
            continue
        task = FacilityCheckTask(**_task_values(cand, today))
        open_id, name = await _resolve_assignee(resolver, cand.view)
        if open_id is None:
            result.unresolved_owner += 1
            logger.warning(
                "设施校验任务责任人解析失败（任务照建）: biz=%s no=%s dept=%s",
                cand.view.biz_type, cand.view.equipment_no, cand.view.department,
            )
        task.assignee_open_id = open_id
        task.assignee_name = name
        session.add(task)
        await session.flush()
        session.add(
            FacilityTaskEvent(
                task_id=task.id,
                event_type="issued",
                operator="system",
                payload={
                    "anchor_field": cand.anchor_field,
                    "due_date": cand.due_date.isoformat(),
                    "assignee": name,
                },
            )
        )
        existing_pairs.add(pair)
        created.append(task)
        result.created += 1
    return created


async def _reconcile_open_tasks(
    session: AsyncSession,
    views_by_biz: dict[str, list[LedgerRowView]],
    result: DispatchResult,
    *,
    skip_task_ids: set[Any] | None = None,
) -> list[str]:
    """对账兜底（仅覆盖本轮成功拉取的台账）：

    - 行已删 / 状态停用 → cancelled（trigger=poll）；
    - 锚点前移（engine.anchor_advanced）→ closed（trigger=poll）；
    - 跳过本轮新建任务（skip_task_ids）：刚派发就按当前行判定会把
      「当日已校准、下次日期仍在窗内」的短周期设备在派发当分钟误闭环。
    返回发生变化的部门列表（供通知刷新）。
    """
    skip_ids = skip_task_ids or set()
    by_key: dict[tuple[str, str], LedgerRowView] = {}
    for biz, views in views_by_biz.items():
        for v in views:
            by_key[(biz, v.record_id)] = v

    rows = await session.execute(
        select(FacilityCheckTask).where(
            FacilityCheckTask.status == "issued",
            FacilityCheckTask.is_deleted.is_(False),
        )
    )
    touched_departments: list[str] = []
    for task in rows.scalars():
        if task.id in skip_ids:
            continue  # 本轮新建：闭环判定从下轮对账开始
        if task.biz_type not in views_by_biz:
            continue  # 该台账本轮未拉取（未配置），不据其对账
        view = by_key.get((task.biz_type, task.ledger_key))
        now = datetime.now(UTC)
        if view is None or not view.active:
            task.status = "cancelled"
            task.closed_trigger = TRIGGER_POLL
            task.closed_reason = (
                "台账行已删除" if view is None else f"台账状态停用：{view.status or '停用'}"
            )
            task.closed_at = now
            session.add(
                FacilityTaskEvent(
                    task_id=task.id,
                    event_type="cancelled",
                    operator="system",
                    closed_trigger=TRIGGER_POLL,
                    payload={"reason": task.closed_reason},
                )
            )
            result.reconciled_cancelled += 1
            if task.department and task.department not in touched_departments:
                touched_departments.append(task.department)
            continue

        anchor_field = anchor_field_of_task(task)
        current_anchor = view.anchor_value(anchor_field)
        advanced = anchor_advanced(
            due_date=task.due_date,
            issued_on=task.issued_on,
            current_anchor=current_anchor,
            current_last=view.last_date,
            # 规则2（上次日期≥派发日）仅主锚点任务适用：换药/报废更换的
            # 闭环铁律是其自身到期列前移，不被「上次检查日期」连坐闭环
            count_last_rule=anchor_field == "next_date",
        )
        if advanced:
            task.status = "closed"
            task.closed_trigger = TRIGGER_POLL
            task.closed_at = now
            session.add(
                FacilityTaskEvent(
                    task_id=task.id,
                    event_type="closed",
                    operator="system",
                    closed_trigger=TRIGGER_POLL,
                    payload={
                        "anchor_before": task.anchor_at_dispatch.isoformat(),
                        "anchor_after": (
                            current_anchor.isoformat() if current_anchor else None
                        ),
                        "last_date": (
                            view.last_date.isoformat() if view.last_date else None
                        ),
                    },
                )
            )
            result.reconciled_closed += 1
            if task.department and task.department not in touched_departments:
                touched_departments.append(task.department)
    return touched_departments


async def run_dispatch(
    session: AsyncSession,
    *,
    reader: FacilitiesLedgerReader | None = None,
    resolver: OwnerResolver | None = None,
    notifier: DispatchNotifier | None = None,
    today: date | None = None,
    digest_pusher: Any = None,
) -> DispatchResult:
    """每日派发编排入口（事务边界归调用方）。

    reader/resolver/notifier/digest_pusher 均可注入（测试替身）；notifier 与
    digest_pusher 缺省走真实通知（批次卡 + 速递格子，票 05 实装），测试注入
    NoopNotifier 关闭网络副作用。resolver 缺省时用 IdentityResolver(session)。
    """
    today = today or _bj_today()
    reader = reader if reader is not None else FacilitiesLedgerReader()
    if resolver is None:
        from app.modules.safety.feishu import IdentityResolver

        resolver = IdentityResolver(session)
    if notifier is None:
        from app.modules.safety.facilities.notify import FacilitiesNotifier

        notifier = FacilitiesNotifier()

    result = DispatchResult()
    views_by_biz: dict[str, list[LedgerRowView]] = {}
    for biz in BIZ_TYPES:
        try:
            views_by_biz[biz] = await reader.fetch_ledger(biz, strict=True)
            result.fetched_rows[biz] = len(views_by_biz[biz])
        except BitableConfigError:
            continue  # 未配置：跳过（三表全未配置 → no_source）

    if not views_by_biz:
        result.no_source = True
        return result

    candidates: list[DueCandidate] = []
    for biz, views in views_by_biz.items():
        candidates.extend(select_due(views, today, LEAD_DAYS[biz]))
        result.incomplete_rows += sum(1 for v in views if v.incomplete_reason)

    created = await _issue_tasks(session, candidates, resolver, today, result)
    touched = await _reconcile_open_tasks(
        session, views_by_biz, result, skip_task_ids={t.id for t in created}
    )

    departments = sorted(
        {t.department for t in created if t.department}
        | {d for d in touched if d}
    )
    result.departments = departments
    # 通知/速递发送发生在调用方 commit 之前：若后续步骤抛错回滚会留下
    # 「群里已发、库里无痕」的鬼卡（下次运行重发）。接受该口径——通知本身
    # fail-open（只告警不抛），回滚仅剩速递写入失败一种路径，代价是一张
    # 重复卡而非漏督办，与保险预警/日报「宁重复不错过」的既有取舍一致。
    await notifier.on_dispatched(session, departments, today=today)

    # 速递格子 facility_check（全厂口径；fail-open 不影响派发）
    if digest_pusher is None:
        from app.modules.safety.facilities.notify import push_digest_cell

        digest_pusher = push_digest_cell
    result.digest_pushed = await _push_digest(
        session, views_by_biz, result, today=today, pusher=digest_pusher,
    )
    return result


async def _push_digest(
    session: AsyncSession,
    views_by_biz: dict[str, list[LedgerRowView]],
    result: DispatchResult,
    *,
    today: date,
    pusher: Any,
) -> bool | None:
    """组装 facility_check 格子并投递（无命中也照发，抄保险预警口径）。"""
    from app.modules.safety.facilities.notify import build_digest_cell_payload

    overdue = due30 = 0
    for views in views_by_biz.values():
        for v in views:
            if not v.active or v.anchor is None:
                continue
            if v.anchor < today:
                overdue += 1
            elif (v.anchor - today).days <= 30:
                due30 += 1
    open_rows = (
        await session.execute(
            select(FacilityCheckTask).where(
                FacilityCheckTask.status == "issued",
                FacilityCheckTask.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    top_overdue = sorted(
        (
            {
                "department": t.department or "未填写部门",
                "equipment_no": t.equipment_no or t.ledger_key[:8],
                "group_key": t.group_key,
                "over_days": (today - t.due_date).days,
            }
            for t in open_rows
            if t.due_date < today
        ),
        key=lambda x: -x["over_days"],
    )
    cell = build_digest_cell_payload(
        open_total=len(open_rows),
        overdue=overdue,
        due_30d=due30,
        top_overdue=top_overdue,
        incomplete=result.incomplete_rows,
        unresolved_owner=result.unresolved_owner,
    )
    return await pusher(cell, today=today)


# ── 逾期升级（每日 17:10，DESIGN §4.4）─────────────────────────────


@dataclass
class EscalationResult:
    """单次升级运行统计。"""

    escalated: int = 0
    departments: list[str] = field(default_factory=list)
    no_source: bool = False

    def summary(self) -> str:
        return (
            f"escalated={self.escalated} departments={self.departments} "
            f"no_source={self.no_source}"
        )


async def run_escalation(
    session: AsyncSession,
    *,
    resolver: OwnerResolver | None = None,
    refresher: Any = None,
    today: date | None = None,
) -> EscalationResult:
    """逾期升级：issued 且今日>due_date → remind_count+1 + escalated 事件 →
    刷新本部门批次卡追加逾期催办区（@部门负责人+安管），绝不逐条私发。

    无任何台账连接登记时 no_source（调度器如实留痕跳过）。
    """
    from app.modules.safety.facilities.reader import connection_configured

    today = today or _bj_today()
    result = EscalationResult()
    if not any(connection_configured(biz) for biz in BIZ_TYPES):
        result.no_source = True
        return result
    if resolver is None:
        from app.modules.safety.feishu import IdentityResolver

        resolver = IdentityResolver(session)
    if refresher is None:
        from app.modules.safety.facilities.notify import refresh_department_batch

        refresher = refresh_department_batch

    rows = (
        await session.execute(
            select(FacilityCheckTask).where(
                FacilityCheckTask.status == "issued",
                FacilityCheckTask.due_date < today,
                FacilityCheckTask.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    if not rows:
        return result

    from app.modules.safety.scheduler import ALERT_NOTIFY_OPEN_ID

    by_dept: dict[str, list[FacilityCheckTask]] = {}
    now = datetime.now(UTC)
    for t in rows:
        t.remind_count += 1
        t.last_reminded_at = now
        session.add(
            FacilityTaskEvent(
                task_id=t.id,
                event_type="escalated",
                operator="system",
                payload={
                    "remind_count": t.remind_count,
                    "over_days": (today - t.due_date).days,
                },
            )
        )
        by_dept.setdefault(t.department or "未填写部门", []).append(t)
        result.escalated += 1

    for dept, items in by_dept.items():
        red = [t for t in items if (today - t.due_date).days > 7]
        md = (
            f"🚨 **逾期升级**：本部门 {len(items)} 件校验已逾期"
            f"（其中 >7 天红档 {len(red)} 件），请尽快安排校验"
        )
        escalate_ids = [ALERT_NOTIFY_OPEN_ID]
        try:
            leader = await resolver.resolve_department_leader(dept)
            if leader is not None and getattr(leader, "open_id", ""):
                escalate_ids.append(leader.open_id)
        except Exception:  # noqa: BLE001 —— 领导人解析失败不阻塞升级
            logger.warning("逾期升级部门负责人解析失败: dept=%s", dept, exc_info=True)
        try:
            await refresher(
                session, dept,
                escalation_md=md, escalate_open_ids=escalate_ids, today=today,
            )
        except Exception:  # noqa: BLE001 —— 刷新失败不阻塞升级留痕
            logger.warning("逾期升级批次卡刷新失败: dept=%s", dept, exc_info=True)
        result.departments.append(dept)
    return result
