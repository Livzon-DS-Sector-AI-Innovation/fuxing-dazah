"""工序周期超时监控编排。

监控采用「开始时快照 + 到期索引扫描」：开始工序时只计算一次历史 P80，
将预计完成时间写入独立记录；定时任务只消费到期记录，不在扫描轮次重新
聚合历史数据，也不为每个执行创建常驻定时器。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, cast
from weakref import WeakValueDictionary

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.core.redis import cache_get, cache_set, redis_client
from app.core.time import now
from app.modules.production import repository as repo
from app.modules.production.models import (
    Batch,
    NodeExecution,
    NodeExecutionTimeoutAlert,
)

logger = logging.getLogger(__name__)

# 先用半年窗口兼顾工艺变化与低频生产的样本量；样本不足时再回退到年度
# 窗口，避免少批次工序完全失去超时监控。
TIMEOUT_WINDOW_DAYS = 180
TIMEOUT_FALLBACK_WINDOW_DAYS = 365
TIMEOUT_MIN_SAMPLES = 5
TIMEOUT_PERCENTILE = 0.8
TIMEOUT_ESTIMATE_VERSION = "v3"
TIMEOUT_CACHE_TTL_SECONDS = 30 * 60
# 样本不足时也短暂缓存“无基线”结论，避免低频工序在连续开始多个执行时
# 每次都重复做 180 天 + 365 天聚合。TTL 刻意远短于正向基线，给新完成样本
# 很快生效的机会；监控门槛仍由仓储层的 min_samples=5 强制执行。
TIMEOUT_NEGATIVE_CACHE_TTL_SECONDS = 60
TIMEOUT_CACHE_LOCK_SECONDS = 20
# Redis is an optimisation only.  Never let a slow/unavailable Redis instance
# hold the transaction that is starting a normal execution indefinitely.
TIMEOUT_CACHE_IO_TIMEOUT_SECONDS = 0.5
# A short cross-process wait lets the lock holder populate Redis.  Same-process
# callers additionally share a keyed asyncio lock (see ``_LOCAL_BASELINE_LOCKS``)
# so a slow aggregate is still executed only once per worker.
TIMEOUT_SINGLE_FLIGHT_WAIT_SECONDS = 2.0
TIMEOUT_SCAN_BATCH_SIZE = 200
TIMEOUT_LEASE_SECONDS = 5 * 60
# 发送可能包含多个收件人，单次飞书调用超时或收件人较多时可能超过一
# 个租约周期。发送 worker 在网络调用期间按此间隔续租，避免旧 worker
# 尚未结束时被另一实例误认为可抢占。
TIMEOUT_LEASE_RENEW_INTERVAL_SECONDS = 60
TIMEOUT_MAX_ATTEMPTS = 5
TIMEOUT_DISPATCH_CONCURRENCY = 10

# Redis 中用于表示“两个统计窗口都不足样本”的短 TTL 哨兵值。不能用空值，
# 因为空值在 Redis 中等同于缓存未命中，无法减少重复聚合。
_NEGATIVE_BASELINE_CACHE_MARKER = (
    "__production_timeout_no_baseline_v3__"
)


class _NegativeBaselineCacheHit:
    """内部标记：区分“缓存命中但无基线”和“缓存未命中”。"""


_NEGATIVE_BASELINE_CACHE_HIT = _NegativeBaselineCacheHit()

# PostgreSQL advisory lock key（只用于缩减多实例重复扫描，数据库唯一约束/租约
# 仍是最终幂等保障）。
_SCAN_LOCK_KEY = 7_214_003_081

# Weak values keep this map bounded as product/route/node combinations change.
_LOCAL_BASELINE_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def _cache_key(
    product_id: uuid.UUID,
    route_id: uuid.UUID,
    node_id: uuid.UUID,
    *,
    window_days: int | None = None,
) -> str:
    # 同一估算键下分别缓存实际采用的窗口；年度回退结果不能伪装成 180 天
    # 结果，否则 estimate_window_days 与缓存键会失去可审计的一致性。
    effective_window_days = (
        TIMEOUT_WINDOW_DAYS if window_days is None else window_days
    )
    return (
        f"production:timeout:p80:{TIMEOUT_ESTIMATE_VERSION}:"
        f"{product_id}:{route_id}:{node_id}:{effective_window_days}"
    )


def _baseline_coordination_key(
    product_id: uuid.UUID, route_id: uuid.UUID, node_id: uuid.UUID,
) -> str:
    """本地/Redis single-flight 的策略键，不代表某个实际统计窗口。"""

    return (
        f"production:timeout:p80:{TIMEOUT_ESTIMATE_VERSION}:flight:"
        f"{product_id}:{route_id}:{node_id}:"
        f"{TIMEOUT_WINDOW_DAYS}-{TIMEOUT_FALLBACK_WINDOW_DAYS}"
    )


def _lock_key(cache_key: str) -> str:
    return f"{cache_key}:lock"


def _baseline_from_json(raw: str) -> repo.NodeDurationBaseline | None:
    try:
        data = json.loads(raw)
        return repo.NodeDurationBaseline(
            estimated_duration_seconds=float(data["estimated_duration_seconds"]),
            estimate_sample_count=int(data["estimate_sample_count"]),
            estimate_method=str(data.get("estimate_method", "p80")),
            estimate_window_days=int(data.get("estimate_window_days", TIMEOUT_WINDOW_DAYS)),
            estimate_version=str(data.get("estimate_version", TIMEOUT_ESTIMATE_VERSION)),
            product_id=uuid.UUID(str(data["product_id"])),
            route_id=uuid.UUID(str(data["route_id"])),
            node_id=uuid.UUID(str(data["node_id"])),
            computed_at=datetime.fromisoformat(str(data["computed_at"])),
            node_family_ids=tuple(
                uuid.UUID(str(v)) for v in data.get("node_family_ids", [])
            ),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _baseline_to_json(baseline: repo.NodeDurationBaseline) -> str:
    return json.dumps(
        {
            "estimated_duration_seconds": baseline.estimated_duration_seconds,
            "estimate_sample_count": baseline.estimate_sample_count,
            "estimate_method": baseline.estimate_method,
            "estimate_window_days": baseline.estimate_window_days,
            "estimate_version": baseline.estimate_version,
            "product_id": str(baseline.product_id),
            "route_id": str(baseline.route_id),
            "node_id": str(baseline.node_id),
            "computed_at": baseline.computed_at.isoformat(),
            "node_family_ids": [str(v) for v in baseline.node_family_ids],
        },
        ensure_ascii=False,
    )


async def _cache_baseline_result(
    product_id: uuid.UUID,
    route_id: uuid.UUID,
    node_id: uuid.UUID,
    baseline: repo.NodeDurationBaseline | None,
) -> None:
    """写入正向或短 TTL 负向基线缓存。

    仅在仓储聚合正常返回后调用；数据库异常会直接抛给上层，不会被误记为
    “样本不足”。缓存本身是可选优化，Redis 异常仍按原策略降级。
    """

    if baseline is None:
        cache_key = _cache_key(
            product_id,
            route_id,
            node_id,
            window_days=TIMEOUT_WINDOW_DAYS,
        )
        cache_value = _NEGATIVE_BASELINE_CACHE_MARKER
        cache_ttl = TIMEOUT_NEGATIVE_CACHE_TTL_SECONDS
    else:
        cache_key = _cache_key(
            product_id,
            route_id,
            node_id,
            window_days=baseline.estimate_window_days,
        )
        cache_value = _baseline_to_json(baseline)
        cache_ttl = TIMEOUT_CACHE_TTL_SECONDS
    try:
        await asyncio.wait_for(
            cache_set(cache_key, cache_value, ex=cache_ttl),
            timeout=TIMEOUT_CACHE_IO_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        logger.debug("写入周期基线缓存失败", exc_info=True)


async def _release_cache_lock(key: str, token: str) -> None:
    """只释放自己持有的 single-flight 锁，避免误删其他实例的锁。"""

    try:
        await asyncio.wait_for(
            cast(Any, redis_client).eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end",
                1,
                key,
                token,
            ),
            timeout=TIMEOUT_CACHE_IO_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        logger.debug("释放周期基线缓存锁失败", exc_info=True)


async def _get_cached_baseline(
    product_id: uuid.UUID, route_id: uuid.UUID, node_id: uuid.UUID,
    *,
    window_days: int | None = None,
    raise_on_error: bool = False,
) -> repo.NodeDurationBaseline | _NegativeBaselineCacheHit | None:
    """读取基线缓存，并区分负缓存命中与真正的缓存未命中。

    负缓存只保存极短时间（由写入侧控制 TTL），因此新样本到来后不会被长
    时间遮蔽；哨兵本身也不携带任何业务数据。
    """
    try:
        raw = await asyncio.wait_for(
            cache_get(
                _cache_key(
                    product_id, route_id, node_id, window_days=window_days,
                )
            ),
            timeout=TIMEOUT_CACHE_IO_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        logger.debug("读取周期基线缓存失败", exc_info=True)
        if raise_on_error:
            raise
        return None
    if not raw:
        return None
    if raw == _NEGATIVE_BASELINE_CACHE_MARKER:
        return _NEGATIVE_BASELINE_CACHE_HIT
    baseline = _baseline_from_json(raw)
    if baseline is None:
        logger.warning("周期基线缓存格式无效，将重新计算")
    return baseline


async def _get_any_cached_baseline(
    product_id: uuid.UUID, route_id: uuid.UUID, node_id: uuid.UUID,
    *,
    raise_on_error: bool = False,
) -> repo.NodeDurationBaseline | _NegativeBaselineCacheHit | None:
    """按近期→年度顺序读取缓存，返回实际窗口对应的快照或负缓存命中。"""

    negative_hit = False
    for window_days in (TIMEOUT_WINDOW_DAYS, TIMEOUT_FALLBACK_WINDOW_DAYS):
        baseline = await _get_cached_baseline(
            product_id,
            route_id,
            node_id,
            window_days=window_days,
            raise_on_error=raise_on_error,
        )
        # 负缓存只表示“当时两个窗口都不足”。必须继续检查年度正缓存，
        # 否则新完成的第五条样本可能已写入年度基线，却被近期负缓存短暂遮蔽。
        if isinstance(baseline, _NegativeBaselineCacheHit):
            negative_hit = True
            continue
        if baseline is not None:
            return baseline
    return _NEGATIVE_BASELINE_CACHE_HIT if negative_hit else None


async def get_timeout_baseline(
    db: AsyncSession,
    *,
    product_id: uuid.UUID,
    route_id: uuid.UUID,
    node_id: uuid.UUID,
    now_dt: datetime | None = None,
) -> repo.NodeDurationBaseline | None:
    """读取缓存或计算单个路线/工序的 P80 基线。

    该函数只应在工序开始时调用。Redis 不可用时自动降级为一次受限的数据库
    聚合流程（最多查询近 180 天和近 365 天两个窗口）；两个窗口样本都不足时
    写入 60 秒短 TTL 负缓存，避免低频工序连续开始时重复聚合。缓存故障不会
    影响业务流程。
    """

    key = _baseline_coordination_key(product_id, route_id, node_id)
    cached = await _get_any_cached_baseline(product_id, route_id, node_id)
    if isinstance(cached, _NegativeBaselineCacheHit):
        return None
    if cached is not None:
        return cached

    # Coordinate concurrent starts in this worker.  The wait is bounded so a
    # broken event loop/task cannot block the production start path forever;
    # the Redis lock below coordinates the remaining cross-process case.
    local_lock = _LOCAL_BASELINE_LOCKS.get(key)
    if local_lock is None:
        local_lock = asyncio.Lock()
        _LOCAL_BASELINE_LOCKS[key] = local_lock
    local_lock_acquired = False
    try:
        await asyncio.wait_for(
            local_lock.acquire(), timeout=TIMEOUT_SINGLE_FLIGHT_WAIT_SECONDS,
        )
        local_lock_acquired = True
    except TimeoutError:
        logger.debug("等待本地周期基线 single-flight 超时，将直接降级查询")

    if not local_lock_acquired:
        # A direct database query is preferable to delaying the actual start
        # operation when the local coordinator is unhealthy.
        baseline = await repo.get_node_duration_p80_baseline(
            db,
            product_id=product_id,
            route_id=route_id,
            node_id=node_id,
            now_dt=now_dt,
            window_days=TIMEOUT_WINDOW_DAYS,
            fallback_window_days=TIMEOUT_FALLBACK_WINDOW_DAYS,
            min_samples=TIMEOUT_MIN_SAMPLES,
            percentile=TIMEOUT_PERCENTILE,
            estimate_version=TIMEOUT_ESTIMATE_VERSION,
        )
        if baseline is None:
            # 另一个持锁调用可能在本次降级聚合期间刚写入正基线；再读一
            # 次只接受正缓存，避免把本次执行错误地判为“无可用样本”。
            cached_after = await _get_any_cached_baseline(
                product_id, route_id, node_id,
            )
            if isinstance(cached_after, repo.NodeDurationBaseline):
                return cached_after
        # 已有同进程调用持有 single-flight 锁时，这条路径是超时降级查询；
        # 不把它得到的“无基线”写入负缓存，避免稍后锁持有者算出正基线后
        # 又被迟到的负结果短暂遮蔽。正基线仍可写入，供后续调用复用。
        if baseline is not None:
            await _cache_baseline_result(product_id, route_id, node_id, baseline)
        return baseline

    lock_key = _lock_key(key)
    token = uuid.uuid4().hex
    acquired = False
    lock_error = False
    try:
        cached = await _get_any_cached_baseline(product_id, route_id, node_id)
        if isinstance(cached, _NegativeBaselineCacheHit):
            return None
        if cached is not None:
            return cached
        try:
            acquired = bool(
                await asyncio.wait_for(
                    redis_client.set(
                        lock_key, token, ex=TIMEOUT_CACHE_LOCK_SECONDS, nx=True,
                    ),
                    timeout=TIMEOUT_CACHE_IO_TIMEOUT_SECONDS,
                )
            )
        except Exception:  # noqa: BLE001
            logger.debug("获取周期基线缓存锁失败，将直接查询数据库", exc_info=True)
            lock_error = True

        if not acquired and not lock_error:
            # 另一实例正在计算时等待一小段时间，让其结果复用；每次 I/O
            # 都有超时，Redis 故障时最多等待一个有界窗口。
            deadline = asyncio.get_running_loop().time() + TIMEOUT_SINGLE_FLIGHT_WAIT_SECONDS
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.05)
                try:
                    cached = await _get_any_cached_baseline(
                        product_id,
                        route_id,
                        node_id,
                        raise_on_error=True,
                    )
                except Exception:  # noqa: BLE001
                    # Redis is optional; stop polling immediately on an I/O
                    # failure and fall back to one database aggregate.
                    logger.debug("single-flight 等待期间 Redis 不可用", exc_info=True)
                    break
                if isinstance(cached, _NegativeBaselineCacheHit):
                    return None
                if cached is not None:
                    return cached

        baseline = await repo.get_node_duration_p80_baseline(
            db,
            product_id=product_id,
            route_id=route_id,
            node_id=node_id,
            now_dt=now_dt,
            window_days=TIMEOUT_WINDOW_DAYS,
            fallback_window_days=TIMEOUT_FALLBACK_WINDOW_DAYS,
            min_samples=TIMEOUT_MIN_SAMPLES,
            percentile=TIMEOUT_PERCENTILE,
            estimate_version=TIMEOUT_ESTIMATE_VERSION,
        )
        await _cache_baseline_result(product_id, route_id, node_id, baseline)
        return baseline
    finally:
        if acquired:
            await _release_cache_lock(lock_key, token)
        local_lock.release()


async def create_timeout_monitor_for_execution(
    db: AsyncSession,
    execution: NodeExecution,
    batch: Batch,
    *,
    created_by: uuid.UUID | None = None,
    now_dt: datetime | None = None,
) -> NodeExecutionTimeoutAlert | None:
    """开始工序时冻结基线并创建监控记录；样本不足返回 ``None``。"""

    # 该保护不仅服务于正常 start 流程，也防止内部重试/脚本误把已结束执行
    # 建成可发送的监控记录。正式需求只覆盖“started_at + in_progress”。
    if (
        execution.is_deleted
        or batch.is_deleted
        or execution.status != "in_progress"
        or execution.started_at is None
        or execution.batch_id != batch.id
        or batch.status in ("completed", "cancelled")
    ):
        return None

    baseline = await get_timeout_baseline(
        db,
        product_id=batch.product_id,
        route_id=batch.route_id,
        node_id=execution.node_id,
        now_dt=now_dt,
    )
    if baseline is None:
        return None
    expected_finish_at = execution.started_at + timedelta(
        seconds=baseline.estimated_duration_seconds,
    )
    return await repo.create_timeout_monitor(
        db,
        execution_id=execution.id,
        product_id=baseline.product_id,
        route_id=baseline.route_id,
        node_id=baseline.node_id,
        estimated_duration_seconds=baseline.estimated_duration_seconds,
        expected_finish_at=expected_finish_at,
        estimate_sample_count=baseline.estimate_sample_count,
        estimate_method=baseline.estimate_method,
        estimate_window_days=baseline.estimate_window_days,
        estimate_version=baseline.estimate_version,
        created_by=created_by,
    )


def timeout_monitor_status(
    alert: NodeExecutionTimeoutAlert | None,
    *,
    execution_status: str,
    batch_status: str | None = None,
    now_dt: datetime | None = None,
) -> str | None:
    """把持久化状态映射为 API/UI 语义状态。"""

    if alert is None:
        return "not_monitored" if execution_status == "in_progress" else None
    # 完成/中止与批次终态是业务上的关闭条件。即使异步 resolver 尚未落库，
    # API 也不能把这条执行继续展示为 overdue，扫描发送侧同样会再次校验。
    if execution_status != "in_progress" or batch_status in ("completed", "cancelled"):
        return "resolved"
    if alert.status in ("sent", "notified"):
        return "sent"
    if alert.status == "failed":
        return "failed"
    if alert.status == "resolved":
        return "resolved"
    if alert.status in ("sending", "processing"):
        return "sending"
    observed_at = now_dt or now()
    expected = alert.expected_finish_at
    if expected.tzinfo is None and observed_at.tzinfo is not None:
        expected = expected.replace(tzinfo=observed_at.tzinfo)
    elif expected.tzinfo is not None and observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=expected.tzinfo)
    if expected <= observed_at:
        return "overdue"
    return "monitoring"


def timeout_info(
    execution: NodeExecution,
    alert: NodeExecutionTimeoutAlert | None,
    *,
    batch_status: str | None = None,
    now_dt: datetime | None = None,
) -> dict[str, Any]:
    """返回可直接合并到执行 API schema 的监控字段。"""

    return {
        "estimated_duration_seconds": (
            float(alert.estimated_duration_seconds) if alert is not None else None
        ),
        "expected_finish_at": alert.expected_finish_at if alert is not None else None,
        "timeout_monitor_status": timeout_monitor_status(
            alert,
            execution_status=execution.status,
            batch_status=batch_status,
            now_dt=now_dt,
        ),
        "timeout_notified_at": alert.notified_at if alert is not None else None,
    }


def apply_timeout_info[OutputT](
    output: OutputT,
    execution: NodeExecution,
    alert: NodeExecutionTimeoutAlert | None,
    *,
    batch_status: str | None = None,
    now_dt: datetime | None = None,
) -> OutputT:
    """把监控快照字段写入任意执行响应对象并返回它。

    ``ExecutionOut``、``NodeExecutionListItem`` 和看板响应共享同一组可选
    字段；统一在 service 层填充，避免 API 层重复读取/解释告警状态。
    """

    for key, value in timeout_info(
        execution, alert, batch_status=batch_status, now_dt=now_dt,
    ).items():
        setattr(output, key, value)
    return output


async def resolve_timeout_for_execution(
    db: AsyncSession,
    execution_id: uuid.UUID,
    *,
    reason: str = "execution_finished",
    resolved_at: datetime | None = None,
) -> int:
    return await repo.resolve_timeout_monitor_for_execution(
        db,
        execution_id,
        resolved_at=resolved_at,
        resolution_reason=reason,
    )


async def get_timeout_monitor_safe(
    db: AsyncSession,
    execution_id: uuid.UUID,
) -> NodeExecutionTimeoutAlert | None:
    """旁路读取单条监控；表/连接异常时不污染调用方业务事务。"""

    try:
        async with db.begin_nested():
            return await repo.get_timeout_monitor(db, execution_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "读取工序超时监控失败（已降级）: execution_id=%s",
            execution_id,
        )
        return None


async def get_timeout_monitors_safe(
    db: AsyncSession,
    execution_ids: list[uuid.UUID],
) -> dict[uuid.UUID, NodeExecutionTimeoutAlert]:
    """旁路批量读取监控；失败返回空映射并保留主事务可用。"""

    if not execution_ids:
        return {}
    try:
        async with db.begin_nested():
            return await repo.get_timeout_monitors_by_execution_ids(db, execution_ids)
    except Exception:  # noqa: BLE001
        logger.exception(
            "批量读取工序超时监控失败（已降级）: execution_count=%d",
            len(execution_ids),
        )
        return {}


async def resolve_timeout_for_batch(
    db: AsyncSession,
    batch_id: uuid.UUID,
    *,
    reason: str = "batch_finished",
    resolved_at: datetime | None = None,
) -> int:
    """关闭批次下所有监控记录（取消/完成批次时调用）。"""

    return await repo.resolve_timeout_monitors_for_batch(
        db,
        batch_id,
        resolved_at=resolved_at,
        resolution_reason=reason,
    )


async def _try_scan_lock(db: AsyncSession) -> bool:
    """尝试获取数据库 advisory lock；非 PostgreSQL 测试环境降级放行。"""

    try:
        value = (
            await db.execute(
                # Transaction-level lock is released by the same COMMIT/ROLLBACK
                # that closes the claim transaction.  A session-level lock could
                # survive a pooled connection swap between commit and unlock.
                text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                {"lock_key": _SCAN_LOCK_KEY},
            )
        ).scalar_one()
        return bool(value)
    except Exception:  # noqa: BLE001
        logger.debug("获取超时扫描 advisory lock 失败，降级执行", exc_info=True)
        await db.rollback()
        return True


_DISPATCH_TASKS: set[asyncio.Task[None]] = set()
_TIMEOUT_DISPATCH_SEMAPHORE = asyncio.Semaphore(TIMEOUT_DISPATCH_CONCURRENCY)


def _spawn_dispatch(coro: Any) -> None:
    task = asyncio.create_task(coro)
    _DISPATCH_TASKS.add(task)
    task.add_done_callback(_DISPATCH_TASKS.discard)


def _timeout_retry_delay(attempt_count: int) -> int:
    """扫描派发异常时的有界指数退避（秒）。"""

    exponent: int = max(0, min(attempt_count - 1, 8))
    return int(min(30 * 60, 60 * (2 ** exponent)))


async def _record_dispatch_failure(
    alert_id: uuid.UUID,
    lease_token: str | None,
    error: str,
) -> None:
    """把未被提醒服务处理的异常归入同一重试状态机。"""

    try:
        async with async_session_factory() as db:
            alert = await repo.get_timeout_monitor_by_id(db, alert_id)
            if alert is None:
                return
            if alert.status != "sending":
                return
            if lease_token is not None and alert.lease_token != lease_token:
                return
            attempt_count = int(alert.attempt_count or 0)
            terminal = attempt_count >= TIMEOUT_MAX_ATTEMPTS
            await repo.mark_timeout_monitor_failed(
                db,
                alert_id,
                error=error,
                next_attempt_at=(
                    now()
                    if terminal
                    else now() + timedelta(seconds=_timeout_retry_delay(attempt_count))
                ),
                terminal=terminal,
                lease_token=lease_token,
                require_active_execution=True,
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        # 原始异常已经记录；若连失败落库也不可用，租约到期后扫描器仍会
        # 恢复该记录，避免后台任务因二次异常崩溃。
        logger.exception("记录工序超时提醒派发失败状态失败: alert_id=%s", alert_id)


async def scan_timeout_monitors() -> None:
    """扫描到期快照并认领，发送工作在独立后台任务中执行。"""

    async with async_session_factory() as db:
        if not await _try_scan_lock(db):
            return
        observed_at = now()
        try:
            async with db.begin_nested():
                await repo.resolve_stale_timeout_monitors(
                    db,
                    resolved_at=observed_at,
                )
        except Exception:  # noqa: BLE001
            # 生命周期 resolver 已在主路径尽力执行；reconciliation 失败不应
            # 阻断本轮其它到期记录的认领，下一轮继续兜底。
            logger.exception("回收失效工序超时监控失败")
        # 通知关闭时只做一次轻量配置查询和生命周期回收，不批量认领后
        # 再为每条记录创建 session/task。重新开启后最晚下一轮恢复发送。
        from app.modules.production.service.reminder_service import (
            notification_type_enabled,
        )

        if not await notification_type_enabled(db, "execution_timeout"):
            await db.commit()
            return
        due = await repo.list_due_timeout_monitors(
            db, now_dt=observed_at, limit=TIMEOUT_SCAN_BATCH_SIZE,
        )
        claimed_ids = await repo.claim_timeout_monitors(
            db,
            due,
            now_dt=observed_at,
            lease_seconds=TIMEOUT_LEASE_SECONDS,
        )
        # pg_try_advisory_xact_lock is transaction-scoped; this commit (or the
        # session context's rollback on error) releases it automatically.
        await db.commit()

    # 扫描器只做有限批量认领，避免阻塞统一 scheduler；租约过期后可恢复。
    for alert_id, lease_token in claimed_ids:
        _spawn_dispatch(dispatch_timeout_alert(alert_id, lease_token))


async def dispatch_timeout_alert(
    alert_id: uuid.UUID,
    lease_token: str | None = None,
) -> None:
    """把一条已认领的超时记录交给提醒服务发送。"""

    from app.modules.production.service.reminder_service import notify_timeout_alert

    try:
        # Bound the number of independent AsyncSession/network pipelines even
        # when one scan claims its full 200-record batch.
        async with _TIMEOUT_DISPATCH_SEMAPHORE:
            if lease_token is None:
                await notify_timeout_alert(alert_id)
            else:
                await notify_timeout_alert(alert_id, lease_token)
    except Exception:  # noqa: BLE001
        logger.exception("工序超时提醒派发异常: alert_id=%s", alert_id)
        await _record_dispatch_failure(
            alert_id,
            lease_token,
            "timeout_dispatch_exception",
        )


__all__ = [
    "TIMEOUT_ESTIMATE_VERSION",
    "TIMEOUT_FALLBACK_WINDOW_DAYS",
    "TIMEOUT_NEGATIVE_CACHE_TTL_SECONDS",
    "TIMEOUT_MAX_ATTEMPTS",
    "TIMEOUT_CACHE_IO_TIMEOUT_SECONDS",
    "TIMEOUT_DISPATCH_CONCURRENCY",
    "TIMEOUT_LEASE_RENEW_INTERVAL_SECONDS",
    "TIMEOUT_MIN_SAMPLES",
    "TIMEOUT_PERCENTILE",
    "TIMEOUT_SCAN_BATCH_SIZE",
    "TIMEOUT_WINDOW_DAYS",
    "apply_timeout_info",
    "create_timeout_monitor_for_execution",
    "dispatch_timeout_alert",
    "get_timeout_baseline",
    "get_timeout_monitor_safe",
    "get_timeout_monitors_safe",
    "resolve_timeout_for_batch",
    "resolve_timeout_for_execution",
    "scan_timeout_monitors",
    "timeout_info",
    "timeout_monitor_status",
]
