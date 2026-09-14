"""工序周期基线与超时监控记录的数据访问。

这里刻意把「开始时计算基线」和「扫描时消费快照」分开：
``get_node_duration_p80_baseline`` 只在工序开始流程调用，定时扫描只读取
``NodeExecutionTimeoutAlert.expected_finish_at``，绝不在扫描轮次重新计算 P80。
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now
from app.modules.production.models import (
    Batch,
    NodeExecution,
    NodeExecutionTimeoutAlert,
    ProcessRoute,
    Product,
    RouteNode,
)

__all__ = [
    "NodeDurationBaseline",
    "TimeoutMonitorContext",
    "get_node_duration_p80_baseline",
    "get_duration_baseline",
    "create_timeout_monitor",
    "create_timeout_monitor_for_execution",
    "get_timeout_monitor",
    "get_timeout_monitor_by_id",
    "get_timeout_monitors_by_execution_ids",
    "get_timeout_monitor_context",
    "list_due_timeout_monitors",
    "list_due_timeout_alerts",
    "claim_timeout_monitor",
    "claim_timeout_alert",
    "claim_timeout_monitors",
    "renew_timeout_monitor_lease",
    "mark_timeout_monitor_notified",
    "mark_timeout_alert_notified",
    "mark_timeout_monitor_failed",
    "mark_timeout_alert_failed",
    "defer_timeout_monitor",
    "record_timeout_delivery_progress",
    "resolve_timeout_monitor",
    "resolve_timeout_monitor_for_execution",
    "resolve_timeout_monitors_for_batch",
    "resolve_stale_timeout_monitors",
    "list_execution_ids_by_batch",
]


@dataclass(frozen=True, slots=True)
class NodeDurationBaseline:
    """工序耗时基线快照。

    ``estimated_duration_seconds`` 是 P80 的原始秒数（允许小数，避免
    ``percentile_cont`` 插值被提前截断）。``node_family_ids`` 用于审计本次
    查询纳入的当前路线血缘节点家族。
    """

    estimated_duration_seconds: float
    estimate_sample_count: int
    estimate_method: str
    estimate_window_days: int
    estimate_version: str
    product_id: uuid.UUID
    route_id: uuid.UUID
    node_id: uuid.UUID
    computed_at: datetime
    node_family_ids: tuple[uuid.UUID, ...] = ()

    @property
    def p80_seconds(self) -> float:
        """兼容调用方的简短别名。"""
        return self.estimated_duration_seconds

    @property
    def sample_count(self) -> int:
        return self.estimate_sample_count

    @property
    def duration_seconds(self) -> float:
        return self.estimated_duration_seconds


# 监控扫描返回的关联快照；发送前重新查询，避免把 ORM 对象带出会话。
@dataclass(frozen=True, slots=True)
class TimeoutMonitorContext:
    alert: NodeExecutionTimeoutAlert
    execution: NodeExecution
    batch: Batch
    node: RouteNode
    route: ProcessRoute
    product_name: str


async def _resolve_node_family(
    db: AsyncSession,
    *,
    route_id: uuid.UUID,
    node_id: uuid.UUID,
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """解析当前路线的血缘节点家族与路线集合。

    复用 lineage_service 的统一归并规则（origin_node_id 优先、node_code
    兜底）。采用局部导入是为了避免 repository ↔ service 的模块初始化环。
    """

    from app.modules.production.service.lineage_service import resolve_lineage

    graph = await resolve_lineage(db, route_id)
    if graph is None:
        return set(), set()
    for family in graph.families:
        if node_id == family.rep.id or node_id in family.member_id_set:
            return set(family.member_id_set), set(graph.route_ids)
    return set(), set(graph.route_ids)


async def get_node_duration_p80_baseline(
    db: AsyncSession,
    *,
    product_id: uuid.UUID,
    route_id: uuid.UUID,
    node_id: uuid.UUID,
    now_dt: datetime | None = None,
    window_days: int = 180,
    fallback_window_days: int | None = 365,
    min_samples: int = 5,
    percentile: float = 0.8,
    estimate_version: str = "v3",
) -> NodeDurationBaseline | None:
    """查询指定产品/路线血缘节点家族的 P80 基线。

    有效样本口径沿用周期分析：首次执行（``execution_seq=1``）、已完成、开始和
    结束时间完整且耗时大于 0 的记录；偏离执行不另建基线，仍与正常执行共用
    该口径。默认先统计近 180 天；如果样本数不足 ``min_samples``，再回退到近
    365 天。返回快照的 ``estimate_window_days`` 始终记录实际采用的窗口，避免
    页面或审计误以为年度样本仍是近期样本。两个窗口都不足时返回 ``None``，由
    开始流程决定不创建监控记录。
    """

    if window_days <= 0:
        raise ValueError("window_days 必须大于 0")
    if fallback_window_days is not None and fallback_window_days <= 0:
        raise ValueError("fallback_window_days 必须为正数或 None")
    if min_samples < 1:
        raise ValueError("min_samples 必须大于 0")
    if not 0 < percentile <= 1:
        raise ValueError("percentile 必须在 (0, 1] 范围内")

    family_node_ids, lineage_route_ids = await _resolve_node_family(
        db, route_id=route_id, node_id=node_id,
    )
    if not family_node_ids or not lineage_route_ids:
        return None

    observed_at = now_dt or now()
    duration_seconds = func.extract(
        "epoch", NodeExecution.finished_at - NodeExecution.started_at,
    )
    p80_expr = func.percentile_cont(float(percentile)).within_group(duration_seconds)
    family_ids = tuple(sorted(family_node_ids, key=str))

    # 只在开始工序时运行，低频工序最多多做一次年度聚合；扫描任务不会进入
    # 这里。先查短窗口可保留近期性，只有样本不足时才付出年度查询成本。
    candidate_windows = [window_days]
    if fallback_window_days is not None and fallback_window_days > window_days:
        candidate_windows.append(fallback_window_days)
    for effective_window_days in candidate_windows:
        since = observed_at - timedelta(days=effective_window_days)
        stmt = (
            select(func.count(NodeExecution.id), p80_expr)
            .select_from(NodeExecution)
            .join(
                Batch,
                (Batch.id == NodeExecution.batch_id)
                & (Batch.is_deleted == False),  # noqa: E712
            )
            .where(
                Batch.product_id == product_id,
                Batch.route_id.in_(lineage_route_ids),
                NodeExecution.node_id.in_(family_node_ids),
                NodeExecution.status == "completed",
                NodeExecution.execution_seq == 1,
                NodeExecution.started_at.is_not(None),
                NodeExecution.finished_at.is_not(None),
                NodeExecution.started_at >= since,
                NodeExecution.started_at <= observed_at,
                NodeExecution.finished_at > NodeExecution.started_at,
                NodeExecution.is_deleted == False,  # noqa: E712
            )
        )
        count, p80 = (await db.execute(stmt)).one()
        sample_count = int(count or 0)
        if sample_count < min_samples or p80 is None:
            continue
        p80_seconds = float(p80)
        if not math.isfinite(p80_seconds) or p80_seconds <= 0:
            continue
        return NodeDurationBaseline(
            estimated_duration_seconds=p80_seconds,
            estimate_sample_count=sample_count,
            estimate_method=f"p{int(percentile * 100):d}",
            estimate_window_days=effective_window_days,
            estimate_version=estimate_version,
            product_id=product_id,
            route_id=route_id,
            node_id=node_id,
            computed_at=observed_at,
            node_family_ids=family_ids,
        )
    return None


# 便于调用方使用更短的语义名称；保留显式 P80 名称作为主 API。
get_duration_baseline = get_node_duration_p80_baseline


async def create_timeout_monitor(
    db: AsyncSession,
    *,
    execution_id: uuid.UUID,
    product_id: uuid.UUID,
    route_id: uuid.UUID,
    node_id: uuid.UUID,
    estimated_duration_seconds: float,
    expected_finish_at: datetime,
    estimate_sample_count: int,
    estimate_method: str = "p80",
    estimate_window_days: int = 180,
    estimate_version: str = "v3",
    next_attempt_at: datetime | None = None,
    created_by: uuid.UUID | None = None,
) -> NodeExecutionTimeoutAlert:
    """创建一条监控快照；同一执行实例重复调用时幂等返回原记录。"""

    if not math.isfinite(float(estimated_duration_seconds)) or estimated_duration_seconds <= 0:
        raise ValueError("estimated_duration_seconds 必须为正数")
    if estimate_sample_count < 1:
        raise ValueError("estimate_sample_count 必须大于 0")

    existing_stmt = (
        select(NodeExecutionTimeoutAlert)
        .where(
            NodeExecutionTimeoutAlert.execution_id == execution_id,
            NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
        )
        .order_by(NodeExecutionTimeoutAlert.created_at.desc())
        .limit(1)
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    row = NodeExecutionTimeoutAlert(
        execution_id=execution_id,
        product_id=product_id,
        route_id=route_id,
        node_id=node_id,
        estimated_duration_seconds=float(estimated_duration_seconds),
        estimate_method=estimate_method,
        estimate_sample_count=estimate_sample_count,
        estimate_window_days=estimate_window_days,
        estimate_version=estimate_version,
        expected_finish_at=expected_finish_at,
        next_attempt_at=next_attempt_at or expected_finish_at,
        status="pending",
        attempt_count=0,
        created_by=created_by,
    )
    try:
        # savepoint 只包住竞态插入，不能回滚调用方 start 事务的其它写入。
        async with db.begin_nested():
            db.add(row)
            await db.flush()
        return row
    except IntegrityError:
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()
        if existing is None:
            raise
        return existing


async def create_timeout_monitor_for_execution(
    db: AsyncSession,
    *,
    execution_id: uuid.UUID,
    product_id: uuid.UUID,
    route_id: uuid.UUID,
    node_id: uuid.UUID,
    estimated_duration_seconds: float,
    expected_finish_at: datetime,
    estimate_sample_count: int,
    estimate_method: str = "p80",
    estimate_window_days: int = 180,
    estimate_version: str = "v3",
    next_attempt_at: datetime | None = None,
    created_by: uuid.UUID | None = None,
) -> NodeExecutionTimeoutAlert:
    """显式别名，供 execution_service 直接调用 repository 层。"""

    return await create_timeout_monitor(
        db,
        execution_id=execution_id,
        product_id=product_id,
        route_id=route_id,
        node_id=node_id,
        estimated_duration_seconds=estimated_duration_seconds,
        expected_finish_at=expected_finish_at,
        estimate_sample_count=estimate_sample_count,
        estimate_method=estimate_method,
        estimate_window_days=estimate_window_days,
        estimate_version=estimate_version,
        next_attempt_at=next_attempt_at,
        created_by=created_by,
    )


async def get_timeout_monitor(
    db: AsyncSession, execution_id: uuid.UUID,
) -> NodeExecutionTimeoutAlert | None:
    stmt = select(NodeExecutionTimeoutAlert).where(
        NodeExecutionTimeoutAlert.execution_id == execution_id,
        NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_timeout_monitor_by_id(
    db: AsyncSession,
    alert_id: uuid.UUID,
) -> NodeExecutionTimeoutAlert | None:
    """按告警主键读取，供发送/失败恢复状态机使用。"""

    stmt = select(NodeExecutionTimeoutAlert).where(
        NodeExecutionTimeoutAlert.id == alert_id,
        NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_timeout_monitors_by_execution_ids(
    db: AsyncSession, execution_ids: list[uuid.UUID],
) -> dict[uuid.UUID, NodeExecutionTimeoutAlert]:
    """批量读取执行对应的监控快照，供详情/看板避免 N+1 查询。"""

    if not execution_ids:
        return {}
    stmt = select(NodeExecutionTimeoutAlert).where(
        NodeExecutionTimeoutAlert.execution_id.in_(execution_ids),
        NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {row.execution_id: row for row in rows}


async def get_timeout_monitor_context(
    db: AsyncSession, alert_id: uuid.UUID,
) -> TimeoutMonitorContext | None:
    """读取发送卡片所需的执行/批次/节点/路线快照。"""

    stmt = (
        select(
            NodeExecutionTimeoutAlert,
            NodeExecution,
            Batch,
            RouteNode,
            ProcessRoute,
            Product.product_name,
        )
        .join(
            NodeExecution,
            (NodeExecution.id == NodeExecutionTimeoutAlert.execution_id)
            & (NodeExecution.is_deleted == False),  # noqa: E712
        )
        .join(
            Batch,
            (Batch.id == NodeExecution.batch_id) & (Batch.is_deleted == False),  # noqa: E712
        )
        .join(
            RouteNode,
            (RouteNode.id == NodeExecution.node_id) & (RouteNode.is_deleted == False),  # noqa: E712
        )
        .join(
            ProcessRoute,
            (ProcessRoute.id == Batch.route_id) & (ProcessRoute.is_deleted == False),  # noqa: E712
        )
        .join(
            Product,
            (Product.id == Batch.product_id) & (Product.is_deleted == False),  # noqa: E712
        )
        .where(
            NodeExecutionTimeoutAlert.id == alert_id,
            NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
        )
    )
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        return None
    alert, execution, batch, node, route, product_name = row
    return TimeoutMonitorContext(
        alert=alert,
        execution=execution,
        batch=batch,
        node=node,
        route=route,
        product_name=product_name,
    )


async def list_due_timeout_monitors(
    db: AsyncSession,
    *,
    now_dt: datetime | None = None,
    limit: int = 100,
) -> list[NodeExecutionTimeoutAlert]:
    """列出已到预计完成时间且可尝试的监控记录。

    只查表内快照；不会调用任何基线/分析查询。
    """

    if limit <= 0:
        return []
    observed_at = now_dt or now()
    stmt = (
        select(NodeExecutionTimeoutAlert)
        .join(
            NodeExecution,
            (NodeExecution.id == NodeExecutionTimeoutAlert.execution_id)
            & (NodeExecution.is_deleted == False),  # noqa: E712
        )
        .join(
            Batch,
            (Batch.id == NodeExecution.batch_id) & (Batch.is_deleted == False),  # noqa: E712
        )
        .where(
            NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
            # 重试记录保持 pending，通过 next_attempt_at 控制下次扫描；
            # sending 仅在租约过期后重新认领。
            NodeExecutionTimeoutAlert.status.in_(("pending", "sending")),
            NodeExecutionTimeoutAlert.expected_finish_at <= observed_at,
            or_(
                NodeExecutionTimeoutAlert.next_attempt_at.is_(None),
                NodeExecutionTimeoutAlert.next_attempt_at <= observed_at,
            ),
            or_(
                NodeExecutionTimeoutAlert.lease_until.is_(None),
                NodeExecutionTimeoutAlert.lease_until <= observed_at,
            ),
            NodeExecution.status == "in_progress",
            Batch.status.not_in(("completed", "cancelled")),
        )
        .order_by(
            NodeExecutionTimeoutAlert.expected_finish_at,
            NodeExecutionTimeoutAlert.created_at,
        )
        # 只锁告警快照行；joined 的执行/批次行不应被扫描器长时间占用，
        # 否则可能阻塞正常的完成/取消事务。
        .with_for_update(of=NodeExecutionTimeoutAlert, skip_locked=True)
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars())


list_due_timeout_alerts = list_due_timeout_monitors


async def claim_timeout_monitor(
    db: AsyncSession,
    alert_id: uuid.UUID,
    *,
    now_dt: datetime | None = None,
    lease_seconds: int = 300,
) -> NodeExecutionTimeoutAlert | None:
    """原子抢占一条到期记录，支持多实例扫描器去重。"""

    if lease_seconds <= 0:
        raise ValueError("lease_seconds 必须大于 0")
    observed_at = now_dt or now()
    lease_until = observed_at + timedelta(seconds=lease_seconds)
    lease_token = uuid.uuid4().hex
    stmt = (
        update(NodeExecutionTimeoutAlert)
        .where(
            NodeExecutionTimeoutAlert.id == alert_id,
            NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
            NodeExecutionTimeoutAlert.status.in_(("pending", "sending")),
            NodeExecutionTimeoutAlert.expected_finish_at <= observed_at,
            or_(
                NodeExecutionTimeoutAlert.next_attempt_at.is_(None),
                NodeExecutionTimeoutAlert.next_attempt_at <= observed_at,
            ),
            or_(
                NodeExecutionTimeoutAlert.lease_until.is_(None),
                NodeExecutionTimeoutAlert.lease_until <= observed_at,
            ),
            # 执行/批次状态也在 UPDATE 中再次校验，防止扫描取数后到认领前
            # 恰好完成或取消而仍被派发。
            NodeExecutionTimeoutAlert.execution_id.in_(
                select(NodeExecution.id).where(
                    NodeExecution.status == "in_progress",
                    NodeExecution.is_deleted == False,  # noqa: E712
                    NodeExecution.batch_id.in_(
                        select(Batch.id).where(
                            Batch.status.not_in(("completed", "cancelled")),
                            Batch.is_deleted == False,  # noqa: E712
                        )
                    ),
                )
            ),
        )
        .values(
            status="sending",
            attempt_count=func.coalesce(NodeExecutionTimeoutAlert.attempt_count, 0) + 1,
            lease_until=lease_until,
            lease_token=lease_token,
            triggered_at=func.coalesce(NodeExecutionTimeoutAlert.triggered_at, observed_at),
            last_error=None,
        )
        .returning(NodeExecutionTimeoutAlert.id)
    )
    claimed_id = (await db.execute(stmt)).scalar_one_or_none()
    if claimed_id is None:
        return None
    await db.flush()
    return await db.get(
        NodeExecutionTimeoutAlert,
        claimed_id,
        populate_existing=True,
    )


claim_timeout_alert = claim_timeout_monitor


async def claim_timeout_monitors(
    db: AsyncSession,
    alerts: list[NodeExecutionTimeoutAlert],
    *,
    now_dt: datetime | None = None,
    lease_seconds: int = 300,
) -> list[tuple[uuid.UUID, str]]:
    """批量认领扫描结果，避免每条记录再 ``SELECT`` 一次。

    ``list_due_timeout_monitors`` 已在同一扫描事务中用 ``SKIP LOCKED`` 锁住
    快照行；这里用一次 ``UPDATE … RETURNING`` 写入每行独立令牌。执行/批次
    状态仍在 UPDATE 条件中复核，完成竞态的行会自然落出返回集。
    """

    if not alerts:
        return []
    if lease_seconds <= 0:
        raise ValueError("lease_seconds 必须大于 0")
    observed_at = now_dt or now()
    lease_until = observed_at + timedelta(seconds=lease_seconds)
    token_by_id = {alert.id: uuid.uuid4().hex for alert in alerts}
    active_execution_ids = select(NodeExecution.id).where(
        NodeExecution.status == "in_progress",
        NodeExecution.is_deleted == False,  # noqa: E712
        NodeExecution.batch_id.in_(
            select(Batch.id).where(
                Batch.status.not_in(("completed", "cancelled")),
                Batch.is_deleted == False,  # noqa: E712
            )
        ),
    )
    stmt = (
        update(NodeExecutionTimeoutAlert)
        .where(
            NodeExecutionTimeoutAlert.id.in_(token_by_id),
            NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
            NodeExecutionTimeoutAlert.status.in_(("pending", "sending")),
            NodeExecutionTimeoutAlert.expected_finish_at <= observed_at,
            or_(
                NodeExecutionTimeoutAlert.next_attempt_at.is_(None),
                NodeExecutionTimeoutAlert.next_attempt_at <= observed_at,
            ),
            or_(
                NodeExecutionTimeoutAlert.lease_until.is_(None),
                NodeExecutionTimeoutAlert.lease_until <= observed_at,
            ),
            NodeExecutionTimeoutAlert.execution_id.in_(active_execution_ids),
        )
        .values(
            status="sending",
            attempt_count=func.coalesce(NodeExecutionTimeoutAlert.attempt_count, 0) + 1,
            lease_until=lease_until,
            lease_token=case(token_by_id, value=NodeExecutionTimeoutAlert.id),
            triggered_at=func.coalesce(NodeExecutionTimeoutAlert.triggered_at, observed_at),
            last_error=None,
        )
        .returning(
            NodeExecutionTimeoutAlert.id,
            NodeExecutionTimeoutAlert.lease_token,
        )
    )
    rows = (await db.execute(stmt)).all()
    await db.flush()
    return [(row.id, row.lease_token) for row in rows if row.lease_token]


async def renew_timeout_monitor_lease(
    db: AsyncSession,
    alert_id: uuid.UUID,
    *,
    lease_token: str,
    lease_seconds: int = 300,
    now_dt: datetime | None = None,
) -> bool:
    """续期当前发送 worker 的租约。

    发送飞书卡片发生在数据库事务之外，收件人较多或网络较慢时可能超过
    初始租约。续期只允许持有当前令牌且仍处于 ``sending`` 的 worker 执行；
    旧 worker、已解决记录或被新 worker 抢占的记录都会返回 ``False``。
    """

    if not lease_token:
        raise ValueError("lease_token 不能为空")
    if lease_seconds <= 0:
        raise ValueError("lease_seconds 必须大于 0")
    observed_at = now_dt or now()
    result = await db.execute(
        update(NodeExecutionTimeoutAlert)
        .where(
            NodeExecutionTimeoutAlert.id == alert_id,
            NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
            NodeExecutionTimeoutAlert.status == "sending",
            NodeExecutionTimeoutAlert.lease_token == lease_token,
        )
        .values(
            lease_until=observed_at + timedelta(seconds=lease_seconds),
        )
    )
    return bool(cast(Any, result).rowcount)


async def mark_timeout_monitor_notified(
    db: AsyncSession,
    alert_id: uuid.UUID,
    *,
    notified_at: datetime | None = None,
    recipient_user_ids: list[uuid.UUID] | None = None,
    lease_token: str | None = None,
) -> bool:
    """标记通知已进入发送管线并释放租约。"""

    notified_time = notified_at or now()
    recipient_values = (
        [str(uid) for uid in recipient_user_ids]
        if recipient_user_ids is not None
        else None
    )
    values: dict[str, object] = {
        "status": "sent",
        "notified_at": notified_time,
        "lease_until": None,
        "next_attempt_at": None,
        "lease_token": None,
        "last_error": None,
    }
    if recipient_user_ids is not None:
        values["notified_recipient_ids"] = recipient_values
    conditions = [
        NodeExecutionTimeoutAlert.id == alert_id,
        NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
        # 发送结果只能由当前 sending worker 写回；避免旧/手工调用把
        # resolved 或下一次重试的状态覆盖掉。
        NodeExecutionTimeoutAlert.status == "sending",
        # 网络发送完成后再写回时，执行可能已经在另一事务中结束；只有仍处于
        # 有效进行中的执行才允许进入 sent。若完成事务先提交，本条件自然
        # 不成立，由生命周期 resolver 保持 resolved 状态。
        NodeExecutionTimeoutAlert.execution_id.in_(
            select(NodeExecution.id).where(
                NodeExecution.status == "in_progress",
                NodeExecution.is_deleted == False,  # noqa: E712
                NodeExecution.batch_id.in_(
                    select(Batch.id).where(
                        Batch.status.not_in(("completed", "cancelled")),
                        Batch.is_deleted == False,  # noqa: E712
                    )
                ),
            )
        ),
    ]
    if lease_token is not None:
        conditions.extend(
            [
                NodeExecutionTimeoutAlert.lease_token == lease_token,
            ]
        )
    result = await db.execute(
        update(NodeExecutionTimeoutAlert).where(*conditions).values(**values)
    )
    return bool(cast(Any, result).rowcount)


mark_timeout_alert_notified = mark_timeout_monitor_notified


async def mark_timeout_monitor_failed(
    db: AsyncSession,
    alert_id: uuid.UUID,
    *,
    error: str,
    next_attempt_at: datetime,
    terminal: bool = False,
    recipient_user_ids: list[uuid.UUID] | None = None,
    lease_token: str | None = None,
    require_active_execution: bool = False,
) -> bool:
    """记录发送失败并安排重试；``terminal`` 用于达到重试上限的场景。"""

    values: dict[str, object] = {
        # 可重试失败仍保持待处理状态，依靠 next_attempt_at 延迟再次领取；
        # 只有达到上限/不可恢复错误才进入 failed 终态。
        "status": "failed" if terminal else "pending",
        "next_attempt_at": None if terminal else next_attempt_at,
        "lease_until": None,
        "lease_token": None,
        "last_error": error[:4000],
    }
    if recipient_user_ids is not None:
        values["notified_recipient_ids"] = [str(uid) for uid in recipient_user_ids]
    conditions = [
        NodeExecutionTimeoutAlert.id == alert_id,
        NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
        NodeExecutionTimeoutAlert.status == "sending",
    ]
    if require_active_execution:
        conditions.append(
            NodeExecutionTimeoutAlert.execution_id.in_(
                select(NodeExecution.id).where(
                    NodeExecution.status == "in_progress",
                    NodeExecution.is_deleted == False,  # noqa: E712
                    NodeExecution.batch_id.in_(
                        select(Batch.id).where(
                            Batch.status.not_in(("completed", "cancelled")),
                            Batch.is_deleted == False,  # noqa: E712
                        )
                    ),
                )
            )
        )

    if lease_token is not None:
        conditions.extend(
            [
                NodeExecutionTimeoutAlert.lease_token == lease_token,
            ]
        )
    result = await db.execute(
        update(NodeExecutionTimeoutAlert).where(*conditions).values(**values)
    )
    return bool(cast(Any, result).rowcount)


mark_timeout_alert_failed = mark_timeout_monitor_failed


async def defer_timeout_monitor(
    db: AsyncSession,
    alert_id: uuid.UUID,
    *,
    next_attempt_at: datetime,
    reason: str = "notification_disabled",
    lease_token: str | None = None,
    require_active_execution: bool = False,
) -> bool:
    """暂缓发送且不增加尝试次数（例如通知开关临时关闭）。"""

    conditions = [
        NodeExecutionTimeoutAlert.id == alert_id,
        NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
        NodeExecutionTimeoutAlert.status == "sending",
    ]
    if require_active_execution:
        conditions.append(
            NodeExecutionTimeoutAlert.execution_id.in_(
                select(NodeExecution.id).where(
                    NodeExecution.status == "in_progress",
                    NodeExecution.is_deleted == False,  # noqa: E712
                    NodeExecution.batch_id.in_(
                        select(Batch.id).where(
                            Batch.status.not_in(("completed", "cancelled")),
                            Batch.is_deleted == False,  # noqa: E712
                        )
                    ),
                )
            )
        )
    if lease_token is not None:
        conditions.extend(
            [
                NodeExecutionTimeoutAlert.lease_token == lease_token,
            ]
        )
    result = await db.execute(
        update(NodeExecutionTimeoutAlert)
        .where(*conditions)
        .values(
            status="pending",
            next_attempt_at=next_attempt_at,
            lease_until=None,
            lease_token=None,
            last_error=reason[:4000],
            # 暂停通知不应消耗有限的发送尝试次数。
            attempt_count=case(
                (
                    func.coalesce(NodeExecutionTimeoutAlert.attempt_count, 0) > 0,
                    func.coalesce(NodeExecutionTimeoutAlert.attempt_count, 0) - 1,
                ),
                else_=0,
            ),
        )
    )
    return bool(cast(Any, result).rowcount)


async def record_timeout_delivery_progress(
    db: AsyncSession,
    alert_id: uuid.UUID,
    *,
    recipient_user_ids: list[uuid.UUID],
    error: str,
    next_attempt_at: datetime,
    lease_token: str | None = None,
) -> bool:
    """保存部分收件人发送成功的进度，并安排失败收件人重试。"""

    return await mark_timeout_monitor_failed(
        db,
        alert_id,
        error=error,
        next_attempt_at=next_attempt_at,
        terminal=False,
        recipient_user_ids=recipient_user_ids,
        lease_token=lease_token,
    )


async def resolve_timeout_monitor(
    db: AsyncSession,
    alert_id: uuid.UUID,
    *,
    resolved_at: datetime | None = None,
    resolution_reason: str = "execution_finished",
    lease_token: str | None = None,
) -> bool:
    """执行完成/中止后关闭监控，防止已结束工序继续告警。"""

    conditions = [
        NodeExecutionTimeoutAlert.id == alert_id,
        NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
        NodeExecutionTimeoutAlert.status != "resolved",
    ]
    if lease_token is not None:
        conditions.extend(
            [
                NodeExecutionTimeoutAlert.status == "sending",
                NodeExecutionTimeoutAlert.lease_token == lease_token,
            ]
        )
    result = await db.execute(
        update(NodeExecutionTimeoutAlert)
        .where(*conditions)
        .values(
            status="resolved",
            resolved_at=resolved_at or now(),
            resolution_reason=resolution_reason,
            lease_until=None,
            lease_token=None,
            next_attempt_at=None,
        )
    )
    return bool(cast(Any, result).rowcount)


async def resolve_timeout_monitor_for_execution(
    db: AsyncSession,
    execution_id: uuid.UUID,
    *,
    resolved_at: datetime | None = None,
    resolution_reason: str = "execution_finished",
) -> int:
    """按执行实例关闭其监控（供 complete/abort 流程调用）。"""

    result = await db.execute(
        update(NodeExecutionTimeoutAlert)
        .where(
            NodeExecutionTimeoutAlert.execution_id == execution_id,
            NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
            NodeExecutionTimeoutAlert.status != "resolved",
        )
        .values(
            status="resolved",
            resolved_at=resolved_at or now(),
            resolution_reason=resolution_reason,
            lease_until=None,
            lease_token=None,
            next_attempt_at=None,
        )
    )
    return int(cast(Any, result).rowcount or 0)


async def list_execution_ids_by_batch(
    db: AsyncSession, batch_id: uuid.UUID,
) -> list[uuid.UUID]:
    """读取批次下执行 id，供批次终态批量关闭监控。"""

    stmt = select(NodeExecution.id).where(
        NodeExecution.batch_id == batch_id,
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def resolve_timeout_monitors_for_batch(
    db: AsyncSession,
    batch_id: uuid.UUID,
    *,
    resolved_at: datetime | None = None,
    resolution_reason: str = "batch_finished",
) -> int:
    """一次性关闭批次下所有执行的监控，避免逐执行 N+1 UPDATE。"""

    execution_ids = select(NodeExecution.id).where(
        NodeExecution.batch_id == batch_id,
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(
        update(NodeExecutionTimeoutAlert)
        .where(
            NodeExecutionTimeoutAlert.execution_id.in_(execution_ids),
            NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
            NodeExecutionTimeoutAlert.status != "resolved",
        )
        .values(
            status="resolved",
            resolved_at=resolved_at or now(),
            resolution_reason=resolution_reason,
            lease_until=None,
            lease_token=None,
            next_attempt_at=None,
        )
    )
    return int(cast(Any, result).rowcount or 0)


async def resolve_stale_timeout_monitors(
    db: AsyncSession,
    *,
    resolved_at: datetime | None = None,
    limit: int = 500,
) -> int:
    """回收生命周期旁路失败后遗留的未终态监控快照。

    正常完成/中止/报废路径会即时调用 resolver；扫描器再做一次轻量的
    最终状态 reconciliation，覆盖外部脚本直接改状态、事务重试或 resolver
    短暂失败的场景。只处理有限的未终态快照，不重新计算历史基线。
    """

    if limit <= 0:
        return 0

    active_execution_ids = (
        select(NodeExecution.id)
        .join(
            Batch,
            (Batch.id == NodeExecution.batch_id) & (Batch.is_deleted == False),  # noqa: E712
        )
        .where(
            NodeExecution.is_deleted == False,  # noqa: E712
            NodeExecution.status == "in_progress",
            Batch.status.not_in(("completed", "cancelled")),
        )
    )
    # 先领取有限数量的告警 id：软删/缺失的执行也不在 active 子查询中，
    # 会被视为终态回收；批量上限避免历史脏数据拖长正常扫描事务。
    candidate_stmt = (
        select(NodeExecutionTimeoutAlert.id)
        .where(
            NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
            NodeExecutionTimeoutAlert.status.in_(
                ("pending", "sending", "sent", "failed")
            ),
            ~NodeExecutionTimeoutAlert.execution_id.in_(active_execution_ids),
        )
        .order_by(NodeExecutionTimeoutAlert.updated_at)
        .with_for_update(of=NodeExecutionTimeoutAlert, skip_locked=True)
        .limit(limit)
    )
    candidate_ids = list((await db.execute(candidate_stmt)).scalars())
    if not candidate_ids:
        return 0
    result = await db.execute(
        update(NodeExecutionTimeoutAlert)
        .where(
            NodeExecutionTimeoutAlert.id.in_(candidate_ids),
            NodeExecutionTimeoutAlert.is_deleted == False,  # noqa: E712
            NodeExecutionTimeoutAlert.status.in_(
                ("pending", "sending", "sent", "failed")
            ),
        )
        .values(
            status="resolved",
            resolved_at=resolved_at or now(),
            resolution_reason="stale_execution_state_reconciled",
            lease_until=None,
            lease_token=None,
            next_attempt_at=None,
        )
    )
    return int(cast(Any, result).rowcount or 0)
