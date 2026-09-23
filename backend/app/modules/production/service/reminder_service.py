"""生产模块飞书提醒服务。

计划单下达 / 计划批次预计开工 / 工序结束 / 计划单完成 / 工序超时提醒的收集与发送。
各类提醒支持启用开关与额外通知人员配置（NOTIFICATION_TYPES +
notification_configs 表，无配置行按默认启用处理）。
消息发送为尽力而为（fire-and-forget）：失败仅记日志，不影响业务事务。
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress
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
from app.modules.production.repository.assignment import (
    list_node_assignments,
    list_stage_assignments,
)
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
            "工序完成后通知下一工序接收人：跨批次或跨工段立即通知下一工段"
            "负责人；同批次同工段延迟 30 分钟通知批次负责人"
            "（届时若下一工序已开始则不再通知）。",
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
        NotificationTypeDef(
            "execution_timeout", "工序超时提醒",
            "工序执行超过历史 P80 参考时长后，提醒本次执行负责人；"
            "无可用负责人时回退到节点负责人或工段负责人。",
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


# 同批次同工段卡（发批次负责人）的延迟发送秒数：给批次负责人缓冲，
# 到期时若下一工序已开始则放弃发送（跨工段卡不受影响，始终立即发）
STEP_COMPLETED_OWNER_DELAY_SECONDS = 30 * 60

# 超时提醒发送侧的资源边界：扫描器可以批量认领，但飞书请求全局最多并发 10 个。
TIMEOUT_SEND_CONCURRENCY = 10
TIMEOUT_SEND_TIMEOUT_SECONDS = 15
TIMEOUT_RETRY_BASE_SECONDS = 60
TIMEOUT_RETRY_MAX_SECONDS = 30 * 60
TIMEOUT_RETRY_LIMIT = 5


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
        extras: list[uuid.UUID] = []
        if row is not None:
            for raw_id in row.extra_recipients or []:
                try:
                    if raw_id:
                        extras.append(uuid.UUID(str(raw_id)))
                except (TypeError, ValueError, AttributeError):
                    logger.warning(
                        "忽略无效的通知额外人员 user_id: notify_type=%s value=%r",
                        code,
                        raw_id,
                    )
        result[code] = (row.is_enabled if row is not None else True, extras)
    return result


async def notification_type_enabled(
    db: AsyncSession,
    notify_type: str,
) -> bool:
    """读取单个通知开关；无配置行按默认启用。"""

    if notify_type not in NOTIFICATION_TYPES:
        return False
    return (await _notification_settings(db))[notify_type][0]


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


_TIMEOUT_SEND_SEMAPHORE = asyncio.Semaphore(TIMEOUT_SEND_CONCURRENCY)


def _format_duration(seconds: float | int | None) -> str:
    """把秒数格式化为适合飞书卡片阅读的墙钟时长。"""

    if seconds is None:
        return "—"
    total = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}小时{minutes:02d}分"
    if minutes:
        return f"{minutes}分{secs:02d}秒"
    return f"{secs}秒"


def _build_timeout_content(
    context: repo.TimeoutMonitorContext,
    *,
    observed_at: datetime | None = None,
) -> str:
    """构建工序超时卡片正文。

    文案只提示“可能超时”，不把统计阈值解释为生产异常；同时保留
    偏离/返工标记，方便收件人判断是否需要核对现场状态。
    """

    alert = context.alert
    execution = context.execution
    batch = context.batch
    observed = observed_at or now()
    started_at = _to_local(execution.started_at)
    expected_finish = _to_local(alert.expected_finish_at)
    # 测试数据/历史手工补录可能是 naive datetime；统一到同一时区再相减，
    # 避免后台提醒因 aware/naive 混用而丢失。
    start_for_calc = execution.started_at
    observed_for_calc = observed
    if start_for_calc.tzinfo is None and observed_for_calc.tzinfo is not None:
        start_for_calc = start_for_calc.replace(tzinfo=observed_for_calc.tzinfo)
    elif start_for_calc.tzinfo is not None and observed_for_calc.tzinfo is None:
        observed_for_calc = observed_for_calc.replace(tzinfo=start_for_calc.tzinfo)
    elapsed = max(0.0, (observed_for_calc - start_for_calc).total_seconds())
    status_marks: list[str] = []
    if execution.is_deviation:
        status_marks.append("偏离流程")
    if execution.execution_seq > 1:
        status_marks.append(f"第 {execution.execution_seq} 次执行（返工/重做）")

    lines = [
        "**工序可能超时，请确认并更新进度**",
        "",
        f"批次：{batch.batch_no}",
        f"产品：{context.product_name}",
        f"路线：{context.route.route_name}",
        f"工序：{context.node.name}",
        f"开始时间：{_fmt_dt(started_at) if started_at else '—'}",
        f"预计完成：{_fmt_dt(expected_finish) if expected_finish else '—'}",
        f"预计时长（P80）：{_format_duration(alert.estimated_duration_seconds)}",
        f"当前已用时：{_format_duration(elapsed)}",
    ]
    if status_marks:
        lines.append(f"执行标记：{'；'.join(status_marks)}")
    if execution.deviation_reason:
        lines.append(f"偏离原因：{execution.deviation_reason}")

    # 正文只做超时提示，不带跳转链接：收件人直接回系统查看即可。
    return "\n".join(lines)


def _timeout_retry_delay(attempt_count: int) -> int:
    """指数退避（上限 30 分钟），attempt_count 从 1 开始。"""

    exponent = max(0, min(attempt_count - 1, 8))
    delay = TIMEOUT_RETRY_BASE_SECONDS * (2 ** exponent)
    return int(min(TIMEOUT_RETRY_MAX_SECONDS, delay))


def _parse_recipient_snapshot(raw: list[str] | None) -> set[uuid.UUID]:
    """解析已成功发送的 user_id 快照，忽略旧数据中的坏值。"""

    result: set[uuid.UUID] = set()
    for value in raw or []:
        try:
            result.add(uuid.UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    return result


async def _timeout_recipients(
    db: AsyncSession,
    context: repo.TimeoutMonitorContext,
    extras: list[uuid.UUID],
) -> tuple[list[uuid.UUID], dict[uuid.UUID, str]]:
    """按 owner → node → stage 逐层兜底，并一次解析所需 open_id。

    “命中”只看业务分配是否存在，不以飞书 open_id 是否已同步为条件：
    一旦执行负责人存在，就不再向节点/工段负责人扩散；open_id 暂缺时由
    发送重试记录问题，避免同一提醒在优先级之外额外打扰其他人。
    """

    execution = context.execution
    batch = context.batch
    node = context.node
    extra_ids = list(dict.fromkeys(extras))
    # 按优先级逐层查找。命中一层后立即停止，不再读取更低层的分配，
    # 既符合兜底语义，也避免每条提醒无谓地查询整条路线的工段负责人。
    owner_ids = [execution.owner_id] if execution.owner_id else []
    selected = list(dict.fromkeys(owner_ids))
    if not selected:
        node_ids = [
            row.user_id
            for row in await list_node_assignments(
                db, route_id=batch.route_id, node_id=node.id,
            )
        ]
        selected = list(dict.fromkeys(node_ids))

    if not selected and node.stage_name:
        stage_ids = [
            row.user_id
            for row in await list_stage_assignments(db, route_id=batch.route_id)
            if row.stage_name == node.stage_name
        ]
        selected = list(dict.fromkeys(stage_ids))
    merged = _merge_recipients(selected, extra_ids)
    open_ids = await _user_open_ids(db, merged)
    return merged, open_ids


async def _send_timeout_to_user(
    open_id: str,
    *,
    title: str,
    content: str,
) -> bool:
    """受全局并发上限和单次超时保护的单人发送。"""

    from app.platform.integrations.feishu.notification import send_user_card

    async with _TIMEOUT_SEND_SEMAPHORE:
        try:
            return bool(
                await asyncio.wait_for(
                    send_user_card(open_id, title=title, content=content),
                    timeout=TIMEOUT_SEND_TIMEOUT_SECONDS,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("工序超时提醒发送异常: open_id=%s", open_id)
            return False


async def _timeout_lease_heartbeat(
    alert_id: uuid.UUID,
    lease_token: str,
    stop_event: asyncio.Event,
) -> None:
    """在飞书网络调用期间续期告警租约。

    扫描器一次可认领较多记录，且单条提醒可能包含多个收件人。若发送耗时
    超过初始租约，另一实例会把同一记录重新认领，造成重复发送；心跳只在
    实际网络调用期间运行，完成后立即由调用方停止，不会为每条执行常驻计时器。
    """

    # 局部导入避免 timeout_service → reminder_service 的调度依赖形成模块
    # 初始化环；timeout_service 只在扫描派发时反向导入 notify 函数。
    from app.modules.production.service.timeout_service import (
        TIMEOUT_LEASE_RENEW_INTERVAL_SECONDS,
        TIMEOUT_LEASE_SECONDS,
    )

    interval = min(
        TIMEOUT_LEASE_RENEW_INTERVAL_SECONDS,
        max(1, TIMEOUT_LEASE_SECONDS // 2),
    )
    while True:
        try:
            stopped = await asyncio.wait_for(stop_event.wait(), timeout=interval)
            if stopped:
                return
        except TimeoutError:
            # 到续租时间，下面开启一个短数据库事务；Redis/调度器不参与。
            pass
        except asyncio.CancelledError:
            raise

        try:
            async with async_session_factory() as db:
                renewed = await repo.renew_timeout_monitor_lease(
                    db,
                    alert_id,
                    lease_token=lease_token,
                    lease_seconds=TIMEOUT_LEASE_SECONDS,
                )
                await db.commit()
            # 记录已被完成/取消 resolver 关闭，或被另一个 worker 抢占；
            # 继续续租没有意义，尽快退出让最终写回校验接管。
            if not renewed:
                return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # 一次续租失败不应中断提醒发送；下一轮仍会重试，最终写回
            # 仍会校验租约令牌和到期时间。
            logger.exception("工序超时提醒租约续期失败: alert_id=%s", alert_id)


async def notify_timeout_alert(
    alert_id: uuid.UUID,
    lease_token: str | None = None,
) -> None:
    """发送一条已认领的工序超时提醒，并持久化重试进度。

    读取/认领与飞书网络调用分离；网络调用结束后再次校验执行和批次状态，
    防止完成或取消竞态下误发。每个执行的告警记录只会进入一次 sent。
    """

    try:
        enabled, extras = await _read_settings_with_retry("execution_timeout")
    except Exception:
        logger.exception("读取工序超时提醒配置失败: alert_id=%s", alert_id)
        # 交给 dispatch 层按当前租约记录一次失败并安排退避；直接返回会让
        # sending 状态一直等到租约过期，既不计次数也无法观察失败原因。
        raise

    async with async_session_factory() as db:
        context = await repo.get_timeout_monitor_context(db, alert_id)
        if context is None:
            # 记录已被软删/关联数据不存在：关闭 sending，避免租约循环重试。
            await repo.mark_timeout_monitor_failed(
                db,
                alert_id,
                error="timeout_context_not_found",
                next_attempt_at=now(),
                terminal=True,
                lease_token=lease_token,
            )
            await db.commit()
            return
        alert = context.alert
        observed_at = now()
        # 认领令牌是发送 worker 的所有权证明。租约过期或已被另一实例
        # 重新认领时，旧 worker 直接退出，不能覆盖新 worker 的状态。
        if alert.status != "sending":
            return
        if lease_token is not None and alert.lease_token != lease_token:
            logger.info("跳过已失效的工序超时提醒租约: alert_id=%s", alert_id)
            return
        effective_lease_token = lease_token or alert.lease_token
        lease_until = alert.lease_until
        if lease_until is not None:
            compare_lease_until = lease_until
            compare_observed_at = observed_at
            if compare_lease_until.tzinfo is None and compare_observed_at.tzinfo is not None:
                compare_lease_until = compare_lease_until.replace(
                    tzinfo=compare_observed_at.tzinfo,
                )
            elif compare_lease_until.tzinfo is not None and compare_observed_at.tzinfo is None:
                compare_observed_at = compare_observed_at.replace(
                    tzinfo=compare_lease_until.tzinfo,
                )
            if compare_lease_until <= compare_observed_at:
                logger.info("跳过已过期的工序超时提醒租约: alert_id=%s", alert_id)
                return
        if (
            context.execution.status != "in_progress"
            or context.batch.status in ("completed", "cancelled")
        ):
            await repo.resolve_timeout_monitor(
                db,
                alert_id,
                resolution_reason="execution_or_batch_finished",
                lease_token=effective_lease_token,
            )
            await db.commit()
            return
        if not enabled:
            await repo.defer_timeout_monitor(
                db,
                alert_id,
                next_attempt_at=now() + timedelta(minutes=10),
                reason="notification_disabled",
                lease_token=effective_lease_token,
                require_active_execution=True,
            )
            await db.commit()
            return
        expected_for_compare = alert.expected_finish_at
        if expected_for_compare.tzinfo is None and observed_at.tzinfo is not None:
            expected_for_compare = expected_for_compare.replace(tzinfo=observed_at.tzinfo)
        elif expected_for_compare.tzinfo is not None and observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=expected_for_compare.tzinfo)
        if observed_at < expected_for_compare:
            await repo.defer_timeout_monitor(
                db,
                alert_id,
                next_attempt_at=expected_for_compare,
                reason="not_due",
                lease_token=effective_lease_token,
                require_active_execution=True,
            )
            await db.commit()
            return
        recipient_ids, open_ids = await _timeout_recipients(db, context, extras)
        already_sent = _parse_recipient_snapshot(alert.notified_recipient_ids)
        sendable_ids = [uid for uid in recipient_ids if uid in open_ids]
        # 没有同步飞书 open_id 的收件人也属于本次提醒的目标：不能因为
        # 同一批次中另一个收件人可发送，就把该目标静默当成“已发送”。
        # 已在之前重试中成功的收件人即使后来被删除/脱离通讯录，也不应
        # 再次阻断本条提醒的终态。
        unavailable_ids = [
            uid for uid in recipient_ids
            if uid not in open_ids and uid not in already_sent
        ]
        pending_ids = [uid for uid in sendable_ids if uid not in already_sent]
        content = _build_timeout_content(context, observed_at=observed_at)
        # 会话内只保留纯数据，网络调用在事务外完成，避免长事务占用连接。
        attempt_count = int(alert.attempt_count or 0)

    if not recipient_ids:
        # 没有任何业务收件人时按失败处理；达到上限后进入 failed 终态并留痕。
        terminal = attempt_count >= TIMEOUT_RETRY_LIMIT
        async with async_session_factory() as db:
            await repo.mark_timeout_monitor_failed(
                db,
                alert_id,
                error="no_feishu_recipient",
                next_attempt_at=(
                    now()
                    if terminal
                    else now() + timedelta(seconds=_timeout_retry_delay(attempt_count))
                ),
                terminal=terminal,
                recipient_user_ids=sorted(already_sent, key=str) or None,
                lease_token=effective_lease_token,
                require_active_execution=True,
            )
            await db.commit()
        return

    if not pending_ids and not unavailable_ids:
        # 重试期间所有收件人都已成功，补写 sent（理论上通常已在上次调用完成）。
        async with async_session_factory() as db:
            await repo.mark_timeout_monitor_notified(
                db,
                alert_id,
                notified_at=now(),
                recipient_user_ids=recipient_ids,
                lease_token=effective_lease_token,
            )
            await db.commit()
        return

    if not sendable_ids and unavailable_ids:
        # 有目标收件人尚未同步 open_id；保留已成功快照，按失败重试，
        # 让通讯录同步后仍有机会补发，而不是误标为 sent。
        terminal = attempt_count >= TIMEOUT_RETRY_LIMIT
        async with async_session_factory() as db:
            await repo.mark_timeout_monitor_failed(
                db,
                alert_id,
                error=f"no_feishu_recipient:{len(unavailable_ids)}",
                next_attempt_at=(
                    now()
                    if terminal
                    else now() + timedelta(seconds=_timeout_retry_delay(attempt_count))
                ),
                terminal=terminal,
                recipient_user_ids=sorted(already_sent, key=str) or None,
                lease_token=effective_lease_token,
                require_active_execution=True,
            )
            await db.commit()
        return

    # 仅在实际网络发送期间续租；没有租令牌的兼容性/手工调用不启动心跳。
    heartbeat_stop: asyncio.Event | None = None
    heartbeat_task: asyncio.Task[None] | None = None
    if effective_lease_token:
        heartbeat_stop = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            _timeout_lease_heartbeat(
                alert_id,
                effective_lease_token,
                heartbeat_stop,
            )
        )
    try:
        send_results = await asyncio.gather(
            *(
                _send_timeout_to_user(
                    open_ids[uid],
                    title="工序超时提醒",
                    content=content,
                )
                if uid in open_ids
                else asyncio.sleep(0, result=False)
                for uid in pending_ids
            ),
            return_exceptions=False,
        )
    finally:
        if heartbeat_stop is not None:
            heartbeat_stop.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
    successful = [uid for uid, ok in zip(pending_ids, send_results, strict=True) if ok]
    successful_union = sorted(already_sent | set(successful), key=str)

    async with async_session_factory() as db:
        # 网络调用期间执行可能已经完成/中止；发送前后的双重校验都保留，
        # 这里是最终闸门，完成后不再把记录标成已发送。
        latest = await repo.get_timeout_monitor_context(db, alert_id)
        if latest is None:
            await db.commit()
            return
        latest_lease = latest.alert.lease_token
        if (
            latest.alert.status != "sending"
            or effective_lease_token is not None
            and latest_lease != effective_lease_token
        ):
            # 另一 worker 已接管或 resolver 已关闭；旧发送结果不可再写回。
            await db.commit()
            return
        latest_lease_until = latest.alert.lease_until
        if latest_lease_until is not None:
            latest_compare_until = latest_lease_until
            latest_compare_now = now()
            if latest_compare_until.tzinfo is None and latest_compare_now.tzinfo is not None:
                latest_compare_until = latest_compare_until.replace(
                    tzinfo=latest_compare_now.tzinfo,
                )
            elif latest_compare_until.tzinfo is not None and latest_compare_now.tzinfo is None:
                latest_compare_now = latest_compare_now.replace(
                    tzinfo=latest_compare_until.tzinfo,
                )
            if latest_compare_until <= latest_compare_now:
                await db.commit()
                return
        if (
            latest.execution.status != "in_progress"
            or latest.batch.status in ("completed", "cancelled")
        ):
            await repo.resolve_timeout_monitor(
                db,
                alert_id,
                resolution_reason="execution_or_batch_finished",
                lease_token=effective_lease_token,
            )
        elif len(successful) == len(pending_ids) and not unavailable_ids:
            await repo.mark_timeout_monitor_notified(
                db,
                alert_id,
                notified_at=now(),
                recipient_user_ids=successful_union,
                lease_token=effective_lease_token,
            )
        else:
            terminal = attempt_count >= TIMEOUT_RETRY_LIMIT
            await repo.mark_timeout_monitor_failed(
                db,
                alert_id,
                error=(
                    "feishu_send_failed:"
                    f"{len(pending_ids) - len(successful)}"
                    f";no_feishu_recipient:{len(unavailable_ids)}"
                ),
                next_attempt_at=(
                    now()
                    if terminal
                    else now() + timedelta(seconds=_timeout_retry_delay(attempt_count))
                ),
                terminal=terminal,
                recipient_user_ids=successful_union,
                lease_token=effective_lease_token,
                require_active_execution=True,
            )
        await db.commit()
    logger.info(
        "工序超时提醒处理完成: alert_id=%s success=%d/%d attempt=%d",
        alert_id, len(successful), len(pending_ids), attempt_count,
    )


async def _row_status_is(
    db: AsyncSession, model: Any, row_id: uuid.UUID, status: str,
) -> bool:
    """行状态是否已变为目标值（后台任务确认事务提交用）。"""
    stmt = select(model.status).where(
        model.id == row_id,
        model.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none() == status


async def _read_settings_with_retry(
    notify_type: str,
) -> tuple[bool, list[uuid.UUID]]:
    """读取提醒配置，瞬时 DB 故障短暂重试（与 _wait_until_committed 同口径）。

    配置读取发生在等待事务提交之前：无重试时连接池竞争/滚动部署的
    瞬时抖动会直接静默丢通知。
    """
    last_error: Exception | None = None
    for _ in range(5):
        try:
            async with async_session_factory() as db:
                return (await _notification_settings(db))[notify_type]
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        await asyncio.sleep(0.5)
    assert last_error is not None
    raise last_error


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
    enabled, extras = await _read_settings_with_retry(notify_type)
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
    """工序结束提醒（后台任务入口）：确认提交后再收集接收人与卡片并发送。

    跨批次边界/跨工段卡立即发；同批次同工段卡（发批次负责人）
    转入延迟发送——到期时若下一工序已开始则放弃。
    """
    try:
        enabled, extras = await _read_settings_with_retry("step_completed")
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
            owner_cards = [r for r in reminders if r.to_owner]
            immediate_cards = [r for r in reminders if not r.to_owner]
            if owner_cards:
                _spawn(_send_delayed_owner_cards(payload))
            if not immediate_cards:
                return
            open_ids, sends = await _prepare_step_card_sends(
                db, immediate_cards, extras,
            )
        await asyncio.gather(
            *(_send_cards(open_ids, uids, title, content) for uids, title, content in sends)
        )
    except Exception:
        logger.exception("工序完成提醒发送异常: batch_id=%s", payload.batch_id)


async def _prepare_step_card_sends(
    db: AsyncSession,
    cards: list[StepCompletedReminder],
    extras: list[uuid.UUID],
) -> tuple[dict[uuid.UUID, str], list[tuple[list[uuid.UUID], str, str]]]:
    """工序完成提醒的发送准备：合并追加人员、统一解析 open_id、组卡。

    立即路径与延迟路径共用；返回后由调用方在会话外并行发送。
    """
    user_ids_per_card = [_merge_recipients(r.user_ids, extras) for r in cards]
    all_uids = sorted(
        {uid for uids in user_ids_per_card for uid in uids}, key=str,
    )
    open_ids = await _user_open_ids(db, all_uids)
    sends = [
        (uids, "工序完成提醒", _build_step_completed_content(
            r.batch_no, r.finished_node, r.next_node, r.to_owner,
        ))
        for r, uids in zip(cards, user_ids_per_card, strict=True)
    ]
    return open_ids, sends


async def _delayed_owner_cards(
    db: AsyncSession, payload: StepCompletedEvent,
) -> list[StepCompletedReminder]:
    """延迟到期后应发的同批次同工段卡；条件不满足返回空（放弃发送）。

    放弃条件：批次已删/已完成/已取消，结束节点已不存在，
    或下一工序已开始（任一 normal 出边目标节点存在
    in_progress/completed 执行；aborted 不算已开始）。
    """
    batch = await repo.get_batch(db, payload.batch_id)
    if batch is None or batch.status in ("completed", "cancelled"):
        return []
    nodes = await repo.get_nodes_by_ids(db, [payload.node_id])
    node = nodes[0] if nodes else None
    if node is None:
        return []
    edges = await repo.get_route_edges(db, batch.route_id)
    target_ids = {
        e.to_node_id for e in edges
        if e.from_node_id == payload.node_id and e.edge_type == "normal"
    }
    if target_ids:
        started = (
            await repo.in_progress_node_ids(db, payload.batch_id)
            | await repo.completed_node_ids(db, payload.batch_id)
        )
        if target_ids & started:
            logger.info(
                "工序完成延迟提醒放弃（下一工序已开始）: batch_id=%s",
                payload.batch_id,
            )
            return []
    return [
        r for r in await _collect_step_completed_reminders(db, batch, node)
        if r.to_owner
    ]


async def _send_delayed_owner_cards(payload: StepCompletedEvent) -> None:
    """同批次同工段卡的延迟发送（30 分钟缓冲）。

    缓冲内批次负责人多半已自行开工，届时下一工序已开始即不再打扰；
    配置关闭同样放弃。接收人与卡片按到期时点重新收集。
    """
    await asyncio.sleep(STEP_COMPLETED_OWNER_DELAY_SECONDS)
    try:
        enabled, extras = await _read_settings_with_retry("step_completed")
        if not enabled:
            return
        async with async_session_factory() as db:
            cards = await _delayed_owner_cards(db, payload)
            if not cards:
                return
            open_ids, sends = await _prepare_step_card_sends(db, cards, extras)
        await asyncio.gather(
            *(_send_cards(open_ids, uids, title, content) for uids, title, content in sends)
        )
    except Exception:
        logger.exception("工序完成延迟提醒异常: batch_id=%s", payload.batch_id)


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
