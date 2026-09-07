"""生产模块飞书提醒服务。

计划单下达 / 计划批次预计开工 / 工序结束 / 计划单完成四类提醒的收集与发送。
各类提醒支持启用开关与额外通知人员配置（NOTIFICATION_TYPES +
notification_configs 表，无配置行按默认启用处理）。
消息发送为尽力而为（fire-and-forget）：失败仅记日志，不影响业务事务。
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.core.time import APP_TZ, now
from app.modules.production import repository as repo
from app.modules.production.models import (
    Batch,
    NotificationConfig,
    PlanItem,
    PlanOrder,
)
from app.modules.production.models.execution import NodeExecution
from app.modules.production.models.planning import PlanAllocation, PlanChangeLog
from app.modules.production.models.product import Product
from app.modules.production.models.route import RouteNode
from app.modules.production.repository.assignment import list_stage_assignments
from app.modules.production.service.route_service import build_stage_order
from app.platform.identity.models import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NotificationTypeDef:
    """通知类型定义：编码/名称/说明，配置页展示与发送侧共用。"""

    code: str
    name: str
    description: str


NOTIFICATION_TYPES: dict[str, NotificationTypeDef] = {
    t.code: t
    for t in (
        NotificationTypeDef(
            "plan_released", "计划单下达提醒",
            "计划单下达后，通知所涉工艺路径全部工段负责人，"
            "内容含各计划项的工段计划开始时间。",
        ),
        NotificationTypeDef(
            "step_completed", "工序完成提醒",
            "工序完成后通知下一工序接收人：同批次同工段为批次负责人，"
            "跨批次或跨工段为下一工段负责人。",
        ),
        NotificationTypeDef(
            "batch_start_due", "计划批次开工提醒",
            "每日 08:31，将预计当天开工的计划批次通知其路线第一工段负责人。",
        ),
        NotificationTypeDef(
            "pending_batches", "待开工批次清单提醒",
            "每日 08:31，向批次负责人汇总全部待开工批次"
            "（无主批次发第一工段负责人）。",
        ),
        NotificationTypeDef(
            "plan_completed", "计划单完成提醒",
            "计划单关闭且全部计划项非进行中/已分配时，"
            "通知所涉工艺路径全部工段负责人，附执行统计"
            "（计划项数、完成数、变更情况、各工序平均耗时）。",
        ),
    )
}


@dataclass(frozen=True, slots=True)
class PlanItemReminder:
    """单个计划项的提醒数据（纯数据，跨异步边界用）。"""

    item_no: int
    product_name: str
    batch_no: str
    stage_times: list[tuple[str, datetime]]


@dataclass(frozen=True, slots=True)
class PlanReleasedReminder:
    """计划单下达提醒载荷。"""

    order_id: uuid.UUID
    order_no: str
    title: str
    user_ids: list[uuid.UUID]
    items: list[PlanItemReminder]


@dataclass(frozen=True, slots=True)
class StepCompletedEvent:
    """工序结束事件（跨异步边界）；提醒数据在确认提交后于后台收集。"""

    batch_id: uuid.UUID
    execution_id: uuid.UUID
    node_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class StepCompletedReminder:
    """工序结束提醒载荷。to_owner=True 发批次负责人版，否则发工段负责人版。"""

    batch_no: str
    finished_node: str
    next_node: str
    to_owner: bool
    user_ids: list[uuid.UUID]


@dataclass(frozen=True, slots=True)
class BatchStartReminder:
    """计划批次预计开工提醒载荷。"""

    batch_no: str
    product_name: str
    planned_start: datetime
    quantity: float | None
    unit: str | None
    user_ids: list[uuid.UUID]


@dataclass(frozen=True, slots=True)
class NodeDurationStat:
    """单工序耗时统计（跨异步边界用）。"""

    node_name: str
    avg_hours: float
    count: int


@dataclass(frozen=True, slots=True)
class RouteDurationStats:
    """单条工艺路径的工序耗时统计。"""

    route_name: str
    nodes: list[NodeDurationStat]


@dataclass(frozen=True, slots=True)
class PlanClosedReminder:
    """计划单完成提醒载荷。"""

    order_id: uuid.UUID
    order_no: str
    title: str
    total_items: int
    completed_items: int
    change_reasons: list[str]
    routes: list[RouteDurationStats]
    user_ids: list[uuid.UUID]


def _to_local(dt: datetime | None) -> datetime | None:
    """tz-aware 时间转 Asia/Shanghai 墙钟时间；naive 视为本地时间原样返回。"""
    if dt is not None and dt.tzinfo is not None:
        return dt.astimezone(APP_TZ)
    return dt


def _plan_stage_start_times(
    planned_start: datetime | None,
    stage_order: list[str],
    durations: dict[str, float] | None,
) -> list[tuple[str, datetime]]:
    """计划项各工段计划开始时间（遇缺口即停）。

    工段 k 的开始 = planned_start + k 之前所有工段时长之和，
    仅当前面所有工段都配置了时长才可算；首个未配置时长的工段本身
    仍列出（其开始时间可算），其后所有工段不再列出。

    注意：语义与 workbench_service._calc_stage_times 不同（缺口即停
    vs 缺失按 0 回退 planned_start），两者不可合并。
    """
    if not planned_start:
        return []
    result: list[tuple[str, datetime]] = []
    accumulated = timedelta(0)
    for sn in stage_order:
        result.append((sn, planned_start + accumulated))
        duration = (durations or {}).get(sn)
        if duration is None:
            break
        accumulated += timedelta(hours=duration)
    return result


def _recipient_kind(is_batch_boundary: bool, same_stage: bool) -> str:
    """工序结束提醒的接收人类型：stage_leader / owner。

    跨批次边界（下一批尚不存在）或跨工段 → 工段负责人；
    同批次同工段 → 批次负责人。
    """
    if is_batch_boundary or not same_stage:
        return "stage_leader"
    return "owner"


# 计划批次开工提醒时间窗（scheduled.py 的 time_of_day 由此派生，改动须同步）
REMINDER_WINDOW_START = time(8, 31)
REMINDER_WINDOW_END = time(8, 35)


def _in_reminder_window(now_time: time) -> bool:
    """计划批次开工提醒时间窗：08:31 ≤ t < 08:35。"""
    return REMINDER_WINDOW_START <= now_time < REMINDER_WINDOW_END


# ── 卡片内容构建 ────────────────────────────────────────────────


def _fmt_dt(dt: datetime) -> str:
    """本地紧凑时间展示：MM-DD HH:mm。"""
    return dt.strftime("%m-%d %H:%M")


def _build_plan_released_content(
    order_no: str, title: str, items: list[PlanItemReminder],
) -> str:
    """计划单下达提醒正文：每个计划项一行 + 各工段计划开始时间。"""
    lines = [f"**计划单 {order_no}（{title}）已下达**，各计划项工段安排如下：", ""]
    for item in items:
        lines.append(
            f"计划项 {item.item_no}：{item.product_name}（批次 {item.batch_no}）"
        )
        lines.extend(f"- {stage}：{_fmt_dt(ts)}" for stage, ts in item.stage_times)
        lines.append("")
    return "\n".join(lines)


def _build_batch_start_content(
    batch_no: str,
    product_name: str,
    quantity: float | None,
    unit: str | None,
    planned_start: datetime,
) -> str:
    """计划批次预计开工提醒正文。"""
    lines = [
        f"**批次 {batch_no}（{product_name}）预计今天开工**，请及时安排。",
        "",
        f"计划开始时间：{_fmt_dt(planned_start)}",
    ]
    if quantity is not None:
        qty = f"{quantity:g} {unit}" if unit else f"{quantity:g}"
        lines.append(f"数量：{qty}")
    return "\n".join(lines)


def _build_step_completed_content(
    batch_no: str, finished_node: str, next_node: str, to_owner: bool,
) -> str:
    """工序结束提醒正文。to_owner=True 为批次负责人版，否则为工段负责人版。"""
    if to_owner:
        return (
            f"**批次 {batch_no} 已完成工序「{finished_node}」**，"
            f"请安排下一工序「{next_node}」。"
        )
    return (
        f"**批次 {batch_no} 已完成工序「{finished_node}」**，"
        f"下一工序「{next_node}」待开始/接收，请关注。"
    )


def _build_pending_batches_content(entries: list[tuple[str, str]]) -> str:
    """待开工批次清单正文：每行 批次号（产品名）。"""
    lines = ["**您有以下待开工批次**，请及时安排：", ""]
    lines.extend(f"- {batch_no}（{product_name}）" for batch_no, product_name in entries)
    return "\n".join(lines)


def _build_plan_closed_content(payload: PlanClosedReminder) -> str:
    """计划单完成提醒正文：执行统计（计划项/完成/变更/工序耗时）。"""
    lines = [
        f"**计划单 {payload.order_no}（{payload.title}）已顺利执行完成**",
        "",
        f"计划项总数：{payload.total_items}",
        f"已完成：{payload.completed_items}",
    ]
    if payload.change_reasons:
        lines.append(f"变更情况：共 {len(payload.change_reasons)} 次变更")
        lines.extend(f"- {reason}" for reason in payload.change_reasons)
    else:
        lines.append("变更情况：无变更")
    for route in payload.routes:
        lines.append(f"工序平均耗时（{route.route_name}）：")
        lines.extend(
            f"- {n.node_name}：{n.avg_hours:.1f} 小时（{n.count} 次）"
            for n in route.nodes
        )
    if not payload.routes:
        lines.append("工序平均耗时：暂无执行记录")
    return "\n".join(lines)


# ── 提醒数据收集（同步，供 service 内 fire-and-forget）────────────


def _durations_dict(config: list[dict[str, Any]] | None) -> dict[str, float] | None:
    """stage_config / stage_durations（JSONB 列表）→ {stage_name: duration_hours}。"""
    if not config:
        return None
    result: dict[str, float] = {}
    for d in config:
        name = d.get("stage_name")
        if not name:
            continue
        result[name] = d.get("duration_hours", 0)
    return result


async def _stage_leaders(
    db: AsyncSession, route_id: uuid.UUID, stage_name: str,
) -> list[uuid.UUID]:
    """指定路线+工段的全部负责人 user_id。"""
    rows = await list_stage_assignments(db, route_id=route_id)
    return [r.user_id for r in rows if r.stage_name == stage_name]


async def _collect_plan_released_reminders(
    db: AsyncSession,
    order: PlanOrder,
    items: list[PlanItem],
    item_batch_nos: dict[uuid.UUID, str],
) -> PlanReleasedReminder | None:
    """计划单下达提醒数据：路线全部工段负责人（按 user 去重）+ 每计划项工段时间。

    工段顺序与开始时间按缺口即停规则计算；无负责人或无路线时返回 None。
    """
    route_ids = {i.route_id for i in items if i.route_id}
    if not route_ids:
        return None
    user_ids: set[uuid.UUID] = set()
    for rid in route_ids:
        user_ids.update(r.user_id for r in await list_stage_assignments(db, route_id=rid))
    if not user_ids:
        return None

    nodes_by_route: dict[uuid.UUID, list[RouteNode]] = {
        rid: await repo.get_route_nodes(db, rid) for rid in route_ids
    }
    order_durations = _durations_dict(order.stage_config)
    item_reminders: list[PlanItemReminder] = []
    for item in items:
        if not item.route_id:
            continue
        nodes = nodes_by_route.get(item.route_id, [])
        stage_order = build_stage_order(nodes)
        # 计划项显式配置优先，否则继承计划单 stage_config
        durations = _durations_dict(item.stage_durations) or order_durations
        times = _plan_stage_start_times(
            _to_local(item.planned_start), stage_order, durations,
        )
        if not times:
            continue
        item_reminders.append(
            PlanItemReminder(
                item_no=item.item_no,
                product_name=item.product_name,
                batch_no=item_batch_nos.get(item.id, ""),
                stage_times=times,
            )
        )
    if not item_reminders:
        return None
    return PlanReleasedReminder(
        order_id=order.id,
        order_no=order.order_no,
        title=order.title,
        user_ids=sorted(user_ids, key=str),
        items=item_reminders,
    )


# 计划单完成提醒的阻断状态：任一计划项处于进行中/已分配则不提醒
_PLAN_CLOSED_BLOCKING_STATUSES = ("in_progress", "allocated")


async def _route_node_duration_stats(
    db: AsyncSession, route_id: uuid.UUID, batch_ids: list[uuid.UUID],
) -> list[NodeDurationStat]:
    """指定路线关联批次的各工序平均耗时（小时，含回流重做）。"""
    if not batch_ids:
        return []
    duration_sec = func.extract(
        "epoch", NodeExecution.finished_at - NodeExecution.started_at,
    )
    stmt = (
        select(
            RouteNode.name,
            func.count(),
            func.avg(duration_sec) / 3600.0,
        )
        .select_from(NodeExecution)
        .join(RouteNode, RouteNode.id == NodeExecution.node_id)
        .where(
            NodeExecution.batch_id.in_(batch_ids),
            NodeExecution.status == "completed",
            NodeExecution.finished_at.is_not(None),
            NodeExecution.started_at.is_not(None),
            NodeExecution.is_deleted == False,  # noqa: E712
            RouteNode.is_deleted == False,  # noqa: E712
            RouteNode.route_id == route_id,
        )
        .group_by(RouteNode.id, RouteNode.name, RouteNode.sort_order)
        .order_by(RouteNode.sort_order)
    )
    rows = (await db.execute(stmt)).all()
    return [
        NodeDurationStat(node_name=name, avg_hours=avg or 0.0, count=count)
        for name, count, avg in rows
    ]


async def _collect_plan_closed_reminders(
    db: AsyncSession,
    order: PlanOrder,
    items: list[PlanItem],
) -> PlanClosedReminder | None:
    """计划单完成提醒数据：全部计划项非进行中/已分配时才收集。

    统计：计划项总数/已完成数、变更日志（各次原因）、各路线工序
    平均耗时（该单关联批次全部已完成执行，含回流重做）。
    接收人：所涉路线全部工段负责人去重。无可接收人时返回 None。
    """
    if not items:
        return None
    if any(i.status in _PLAN_CLOSED_BLOCKING_STATUSES for i in items):
        return None
    route_ids = {i.route_id for i in items if i.route_id}
    if not route_ids:
        return None
    user_ids: set[uuid.UUID] = set()
    for rid in route_ids:
        user_ids.update(
            r.user_id for r in await list_stage_assignments(db, route_id=rid)
        )
    if not user_ids:
        return None

    log_rows = await db.execute(
        select(PlanChangeLog.change_reason)
        .where(
            PlanChangeLog.plan_order_id == order.id,
            PlanChangeLog.is_deleted == False,  # noqa: E712
        )
        .order_by(PlanChangeLog.plan_version)
    )
    change_reasons = [row[0] for row in log_rows.all()]

    # 关联批次按路线分组，逐路线聚合工序耗时
    batches_by_item = await repo.get_batches_by_plan_items(
        db, [i.id for i in items],
    )
    batch_ids_by_route: dict[uuid.UUID, list[uuid.UUID]] = {}
    for batch in batches_by_item.values():
        if batch.route_id in route_ids:
            batch_ids_by_route.setdefault(batch.route_id, []).append(batch.id)
    routes = await repo.get_routes_by_ids(db, sorted(route_ids, key=str))
    route_stats: list[RouteDurationStats] = []
    for route in sorted(routes, key=lambda r: r.route_name):
        nodes = await _route_node_duration_stats(
            db, route.id, batch_ids_by_route.get(route.id, []),
        )
        if nodes:
            route_stats.append(
                RouteDurationStats(route_name=route.route_name, nodes=nodes)
            )

    return PlanClosedReminder(
        order_id=order.id,
        order_no=order.order_no,
        title=order.title,
        total_items=len(items),
        completed_items=sum(1 for i in items if i.status == "completed"),
        change_reasons=change_reasons,
        routes=route_stats,
        user_ids=sorted(user_ids, key=str),
    )


async def _collect_step_completed_reminders(
    db: AsyncSession,
    batch: Batch,
    node: RouteNode,
) -> list[StepCompletedReminder]:
    """工序结束后的下一工序提醒数据。

    最后一道工序（无 normal 出边）返回空列表。接收人规则：
    跨批次边界或跨工段 → 工段负责人；同批次同工段 → 批次负责人
    （无归属人时回退工段负责人）。接收人相同的多条出边合并为一张卡。
    """
    edges = await repo.get_route_edges(db, batch.route_id)
    next_edges = [
        e for e in edges
        if e.from_node_id == node.id and e.edge_type == "normal"
    ]
    if not next_edges:
        return []
    to_node_ids = {e.to_node_id for e in next_edges}
    to_nodes = {
        n.id: n for n in await repo.get_nodes_by_ids(db, list(to_node_ids))
    }
    # 无 ORDER BY 的查询行序不确定，按目标工序 sort_order 稳定排序保证卡片文案确定
    next_edges.sort(
        key=lambda e: (
            to_nodes[e.to_node_id].sort_order if e.to_node_id in to_nodes else 1 << 30,
            str(e.to_node_id),
        ),
    )
    # 一次查询拿到该路线全部工段分配，构建 stage → 负责人 map
    leaders_by_stage: dict[str, list[uuid.UUID]] = {}
    for sa in await list_stage_assignments(db, route_id=batch.route_id):
        leaders_by_stage.setdefault(sa.stage_name, []).append(sa.user_id)
    # key = (是否批次负责人, 接收人集合) → 下一工序名列表
    grouped: dict[tuple[bool, tuple[uuid.UUID, ...]], list[str]] = {}
    for e in next_edges:
        to_node = to_nodes.get(e.to_node_id)
        if to_node is None:
            continue
        kind = _recipient_kind(
            e.is_batch_boundary, to_node.stage_name == node.stage_name,
        )
        if kind == "owner":
            user_ids = [batch.owner_user_id] if batch.owner_user_id else []
            if not user_ids:
                # 无归属人：回退提醒下一工段负责人
                kind = "stage_leader"
                user_ids = leaders_by_stage.get(to_node.stage_name, [])
        else:
            user_ids = leaders_by_stage.get(to_node.stage_name, [])
        if not user_ids:
            continue
        key = (kind == "owner", tuple(sorted(user_ids, key=str)))
        grouped.setdefault(key, []).append(to_node.name)
    return [
        StepCompletedReminder(
            batch_no=batch.batch_no,
            finished_node=node.name,
            next_node="、".join(names),
            to_owner=to_owner,
            user_ids=list(users),
        )
        for (to_owner, users), names in grouped.items()
    ]


async def _due_plan_batches(
    db: AsyncSession, today: date,
) -> list[tuple[Batch, PlanItem]]:
    """预计今天开工、尚未开始的计划批次（含其计划项快照）。

    creation_type=plan 且 status ∈ {scheduled, pending}；planned_start
    按本地时区归日期与 today 比较（naive 视为本地时间）。
    """
    stmt = (
        select(Batch, PlanItem)
        .join(PlanAllocation, PlanAllocation.batch_id == Batch.id)
        .join(PlanItem, PlanItem.id == PlanAllocation.plan_item_id)
        .join(PlanOrder, PlanOrder.id == PlanItem.plan_order_id)
        .where(
            Batch.creation_type == "plan",
            Batch.status.in_(("scheduled", "pending")),
            Batch.is_deleted == False,  # noqa: E712
            PlanAllocation.is_deleted == False,  # noqa: E712
            PlanItem.is_deleted == False,  # noqa: E712
            # 计划单已关闭的批次不再提醒（close_plan_order 不联动批次状态）
            PlanOrder.status == "released",
            PlanOrder.is_deleted == False,  # noqa: E712
        )
    )
    rows = (await db.execute(stmt)).all()
    result: list[tuple[Batch, PlanItem]] = []
    for batch, item in rows:
        start = _to_local(item.planned_start)
        if start is None or start.date() != today:
            continue
        result.append((batch, item))
    return result


async def _first_stage_leaders(
    db: AsyncSession, route_id: uuid.UUID,
) -> list[uuid.UUID]:
    """路线第一工段（按 sort_order 首节点）的全部负责人。"""
    nodes = await repo.get_route_nodes(db, route_id)
    stage_order = build_stage_order(nodes)
    if not stage_order:
        return []
    return await _stage_leaders(db, route_id, stage_order[0])


async def _pending_batches(db: AsyncSession) -> list[tuple[Batch, str]]:
    """全部待开工（pending）批次及其产品名（不限计划日期）。"""
    rows = await db.execute(
        select(Batch, Product.product_name)
        .join(Product, Product.id == Batch.product_id)
        .where(
            Batch.status == "pending",
            Batch.is_deleted == False,  # noqa: E712
        )
    )
    return [(batch, name) for batch, name in rows.all()]


# ── 发送与后台任务入口 ─────────────────────────────────────────

# 事件循环只持有 Task 的弱引用，必须保存引用防 GC 中途回收
_BG_TASKS: set[asyncio.Task[None]] = set()


def _spawn(coro: Coroutine[Any, Any, None]) -> None:
    """创建后台任务并保存引用（done 时自动清理）。"""
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


async def _notification_settings(
    db: AsyncSession,
) -> dict[str, tuple[bool, list[uuid.UUID]]]:
    """全部通知类型的配置：notify_type → (是否启用, 额外通知人员)。

    无配置行的类型按默认（启用、无额外人员）处理，
    与引入配置前的行为一致。
    """
    rows = await db.execute(
        select(NotificationConfig).where(
            NotificationConfig.is_deleted == False,  # noqa: E712
        )
    )
    configs = {r.notify_type: r for r in rows.scalars()}
    result: dict[str, tuple[bool, list[uuid.UUID]]] = {}
    for code in NOTIFICATION_TYPES:
        row = configs.get(code)
        extras = (
            [uuid.UUID(uid) for uid in (row.extra_recipients or []) if uid]
            if row is not None
            else []
        )
        result[code] = (row.is_enabled if row is not None else True, extras)
    return result


def _merge_recipients(
    base: list[uuid.UUID], extras: list[uuid.UUID],
) -> list[uuid.UUID]:
    """功能接收人 + 配置的额外人员合并去重（保持首现顺序）。

    _send_cards 按列表逐人发送，重复 user_id 会发重卡，必须去重。
    """
    return list(dict.fromkeys([*base, *extras]))


async def _wait_until_committed(
    check: Callable[[AsyncSession], Awaitable[bool]],
) -> bool:
    """轮询等待业务事务提交（新会话读到提交后的状态才返回 True）。

    请求事务的 commit 发生在响应阶段，后台任务可能先于 commit 运行；
    最多等 ~10 秒（大计划单/高负载下 commit 可能超过 2.5 秒），
    等不到视为事务回滚，放弃发送避免虚假提醒。
    单次轮询的瞬时异常（连接池竞争等）不中断等待，继续重试。
    """
    last_error: Exception | None = None
    for _ in range(20):
        try:
            async with async_session_factory() as db:
                if await check(db):
                    return True
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        await asyncio.sleep(0.5)
    if last_error is not None:
        logger.exception("提醒前置校验查询反复失败", exc_info=last_error)
    return False


async def _user_open_ids(
    db: AsyncSession, user_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """identity.users 查飞书 open_id（仅系统登录过的用户可推送）。"""
    if not user_ids:
        return {}
    rows = await db.execute(
        select(User.id, User.feishu_open_id).where(
            User.id.in_(user_ids),
            User.is_deleted == False,  # noqa: E712
        )
    )
    return {uid: oid for uid, oid in rows.all() if oid}


async def _send_cards(
    open_ids: dict[uuid.UUID, str],
    user_ids: list[uuid.UUID],
    title: str,
    content: str,
) -> None:
    """按已解析的 open_id 映射逐人发送飞书卡片（尽力而为）。"""
    from app.platform.integrations.feishu.notification import send_user_card

    for uid in user_ids:
        oid = open_ids.get(uid)
        if not oid:
            logger.warning("提醒跳过（无飞书 open_id）: user_id=%s", uid)
            continue
        ok = await send_user_card(oid, title=title, content=content)
        if not ok:
            logger.warning("提醒发送失败: user_id=%s", uid)


async def _row_status_is(
    db: AsyncSession, model: Any, row_id: uuid.UUID, status: str,
) -> bool:
    """行状态是否已变为目标值（后台任务确认事务提交用）。"""
    stmt = select(model.status).where(
        model.id == row_id,
        model.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none() == status


async def _send_configured_notification(
    notify_type: str,
    status_check: Callable[[AsyncSession], Awaitable[bool]],
    user_ids: list[uuid.UUID],
    title: str,
    content: str,
    ctx: str,
) -> None:
    """按类型配置发送单卡提醒：配置禁用或业务事务未提交则跳过。

    计划单下达/完成共用的发送管线；新增同类提醒时复用，
    避免再复制一遍配置读取→等待提交→合并接收人→解析 open_id→发卡。
    """
    async with async_session_factory() as db:
        enabled, extras = (await _notification_settings(db))[notify_type]
    if not enabled:
        return
    committed = await _wait_until_committed(status_check)
    if not committed:
        logger.warning("提醒放弃（事务未提交）: %s", ctx)
        return
    merged = _merge_recipients(user_ids, extras)
    async with async_session_factory() as db:
        open_ids = await _user_open_ids(db, merged)
    await _send_cards(open_ids, merged, title, content)


async def notify_plan_released(payload: PlanReleasedReminder) -> None:
    """计划单下达提醒（后台任务入口）。"""
    try:
        await _send_configured_notification(
            "plan_released",
            lambda db: _row_status_is(db, PlanOrder, payload.order_id, "released"),
            payload.user_ids,
            "生产计划下达提醒",
            _build_plan_released_content(
                payload.order_no, payload.title, payload.items,
            ),
            f"order_no={payload.order_no}",
        )
    except Exception:
        logger.exception("计划单下达提醒发送异常: order_no=%s", payload.order_no)


async def notify_plan_closed(payload: PlanClosedReminder) -> None:
    """计划单完成提醒（后台任务入口）。"""
    try:
        await _send_configured_notification(
            "plan_completed",
            lambda db: _row_status_is(db, PlanOrder, payload.order_id, "closed"),
            payload.user_ids,
            "计划单完成提醒",
            _build_plan_closed_content(payload),
            f"order_no={payload.order_no}",
        )
    except Exception:
        logger.exception("计划单完成提醒发送异常: order_no=%s", payload.order_no)


async def notify_step_completed(payload: StepCompletedEvent) -> None:
    """工序结束提醒（后台任务入口）：确认提交后再收集接收人与卡片并发送。"""
    try:
        async with async_session_factory() as db:
            enabled, extras = (await _notification_settings(db))["step_completed"]
        if not enabled:
            return
        committed = await _wait_until_committed(
            lambda db: _row_status_is(db, NodeExecution, payload.execution_id, "completed"),
        )
        if not committed:
            logger.warning(
                "工序完成提醒放弃（事务未提交）: batch_id=%s", payload.batch_id,
            )
            return
        async with async_session_factory() as db:
            batch = await repo.get_batch(db, payload.batch_id)
            nodes = await repo.get_nodes_by_ids(db, [payload.node_id])
            node = nodes[0] if nodes else None
            if batch is None or node is None:
                return
            reminders = await _collect_step_completed_reminders(db, batch, node)
            if not reminders:
                return
            # 同一次任务内统一解析 open_id，各卡并行发送
            user_ids_per_card = [
                _merge_recipients(r.user_ids, extras) for r in reminders
            ]
            all_uids = sorted(
                {uid for uids in user_ids_per_card for uid in uids}, key=str,
            )
            open_ids = await _user_open_ids(db, all_uids)
            sends = [
                (uids, "工序完成提醒", _build_step_completed_content(
                    r.batch_no, r.finished_node, r.next_node, r.to_owner,
                ))
                for r, uids in zip(reminders, user_ids_per_card, strict=True)
            ]
        await asyncio.gather(
            *(_send_cards(open_ids, uids, title, content) for uids, title, content in sends)
        )
    except Exception:
        logger.exception("工序完成提醒发送异常: batch_id=%s", payload.batch_id)


async def _cached_first_stage_leaders(
    db: AsyncSession,
    route_id: uuid.UUID,
    cache: dict[uuid.UUID, list[uuid.UUID]],
) -> list[uuid.UUID]:
    """带缓存的路线首工段负责人查询（同一路线批次共享，避免 N+1）。"""
    leaders = cache.get(route_id)
    if leaders is None:
        leaders = await _first_stage_leaders(db, route_id)
        cache[route_id] = leaders
    return leaders


async def notify_batch_start_due() -> None:
    """每日 08:31 定时提醒（时间窗外直接返回）。

    1. 计划批次开工提醒：预计今天开工的计划批次 → 第一工段负责人
    2. 待开工批次清单：全部 pending 批次 → 批次负责人（无主回退第一工段负责人）

    全部接收人 open_id 一次解析，各卡并行发送。
    """
    now_dt = now()
    if not _in_reminder_window(now_dt.time()):
        return
    # 每日单发任务，一次瞬时失败即丢失全天提醒：时间窗内重试几次
    for attempt in range(3):
        try:
            await _send_batch_start_due_reminders(now_dt)
            return
        except Exception:
            logger.exception("每日开工/待开工提醒定时任务异常（第 %d 次尝试）", attempt + 1)
            await asyncio.sleep(5)


async def _send_batch_start_due_reminders(now_dt: datetime) -> None:
    """收集并发送当日计划批次开工提醒 + 待开工批次清单。"""
    async with async_session_factory() as db:
        settings = await _notification_settings(db)
        start_enabled, start_extras = settings["batch_start_due"]
        pending_enabled, pending_extras = settings["pending_batches"]
        leaders_cache: dict[uuid.UUID, list[uuid.UUID]] = {}
        sends: list[tuple[list[uuid.UUID], str, str]] = []

        # ── 1. 计划批次开工提醒 ──
        if start_enabled:
            for batch, item in await _due_plan_batches(db, now_dt.date()):
                leaders = await _cached_first_stage_leaders(
                    db, batch.route_id, leaders_cache,
                )
                if not leaders:
                    continue
                content = _build_batch_start_content(
                    batch.batch_no, item.product_name,
                    batch.quantity, batch.unit,
                    _to_local(item.planned_start) or now_dt,
                )
                sends.append((
                    _merge_recipients(leaders, start_extras),
                    "计划批次开工提醒", content,
                ))

        # ── 2. 待开工批次清单 ──
        # 有主 → 批次负责人；无主（计划批次激活未开工）→ 第一工段负责人
        if pending_enabled:
            by_owner: dict[uuid.UUID, list[tuple[str, str]]] = {}
            unowned_groups: dict[tuple[uuid.UUID, ...], list[tuple[str, str]]] = {}
            for batch, product_name in await _pending_batches(db):
                entry = (batch.batch_no, product_name)
                if batch.owner_user_id is not None:
                    by_owner.setdefault(batch.owner_user_id, []).append(entry)
                    continue
                leaders = await _cached_first_stage_leaders(
                    db, batch.route_id, leaders_cache,
                )
                if leaders:
                    key = tuple(sorted(leaders, key=str))
                    unowned_groups.setdefault(key, []).append(entry)
            for owner_id, entries in by_owner.items():
                sends.append((
                    _merge_recipients([owner_id], pending_extras),
                    "待开工批次提醒",
                    _build_pending_batches_content(entries),
                ))
            for leader_ids, entries in unowned_groups.items():
                sends.append((
                    _merge_recipients(list(leader_ids), pending_extras),
                    "待开工批次提醒",
                    _build_pending_batches_content(entries),
                ))

        # 一次解析全部接收人 open_id，再并行发送
        all_uids = sorted({uid for uids, _, _ in sends for uid in uids}, key=str)
        open_ids = await _user_open_ids(db, all_uids)
    await asyncio.gather(
        *(_send_cards(open_ids, uids, title, content) for uids, title, content in sends)
    )


async def schedule_plan_released_notification(
    db: AsyncSession,
    order: PlanOrder,
    items: list[PlanItem],
    item_batch_nos: dict[uuid.UUID, str],
) -> None:
    """计划单下达成功后的提醒收集 + 后台发送（fire-and-forget）。

    收集在请求事务内同步完成（纯数据快照），发送在后台执行，
    发送前轮询确认事务已提交（避免回滚时发出虚假提醒）。
    """
    try:
        payload = await _collect_plan_released_reminders(
            db, order, items, item_batch_nos,
        )
    except Exception:
        logger.exception("计划单下达提醒收集失败: order_no=%s", order.order_no)
        return
    if payload:
        _spawn(notify_plan_released(payload))


async def schedule_plan_closed_notification(
    db: AsyncSession,
    order: PlanOrder,
    items: list[PlanItem],
) -> None:
    """计划单关闭后的完成提醒收集 + 后台发送（fire-and-forget）。

    仅当全部计划项非进行中/已分配时才会产生提醒（收集内部判定）。
    收集在请求事务内同步完成（纯数据快照），发送在后台执行，
    发送前轮询确认事务已提交（避免回滚时发出虚假提醒）。
    """
    try:
        payload = await _collect_plan_closed_reminders(db, order, items)
    except Exception:
        logger.exception("计划单完成提醒收集失败: order_no=%s", order.order_no)
        return
    if payload:
        _spawn(notify_plan_closed(payload))


def schedule_step_completed_notification(
    batch_id: uuid.UUID, execution_id: uuid.UUID, node_id: uuid.UUID,
) -> None:
    """工序结束后的提醒（fire-and-forget）。

    不在请求事务内做任何查询：后台任务先确认事务提交，
    再在新会话中收集接收人与卡片内容。
    """
    _spawn(notify_step_completed(StepCompletedEvent(
        batch_id=batch_id, execution_id=execution_id, node_id=node_id,
    )))
