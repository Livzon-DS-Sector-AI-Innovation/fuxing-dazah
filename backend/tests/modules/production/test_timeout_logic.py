"""工序执行超时提醒的无数据库单元测试。"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.production.models import (
    Batch,
    NodeExecution,
    NodeExecutionTimeoutAlert,
    ProcessRoute,
    RouteNode,
)
from app.modules.production.repository import timeout as timeout_repo
from app.modules.production.repository.timeout import (
    NodeDurationBaseline,
    TimeoutMonitorContext,
)
from app.modules.production.scheduled import EXECUTION_TIMEOUT_SCAN_TASK
from app.modules.production.service import reminder_service, timeout_service
from app.modules.production.service.analytics_service import _percentile
from app.modules.production.service.reminder_service import (
    _build_timeout_content,
    _timeout_retry_delay,
)
from app.modules.production.service.timeout_service import timeout_monitor_status
from app.platform.scheduler import ScheduleStrategy


def _context(
    *,
    alert_status: str = "pending",
    expected_finish_at: datetime | None = None,
    execution_status: str = "in_progress",
    execution_seq: int = 1,
    is_deviation: bool = False,
) -> tuple[TimeoutMonitorContext, datetime]:
    started_at = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    expected = expected_finish_at or started_at + timedelta(hours=1)
    batch_id = uuid.uuid4()
    route_id = uuid.uuid4()
    node_id = uuid.uuid4()
    product_id = uuid.uuid4()
    execution = NodeExecution(
        id=uuid.uuid4(),
        batch_id=batch_id,
        node_id=node_id,
        execution_seq=execution_seq,
        status=execution_status,
        started_at=started_at,
        is_deviation=is_deviation,
    )
    batch = Batch(
        id=batch_id,
        batch_no="B-001",
        product_id=product_id,
        route_id=route_id,
        status="in_progress",
    )
    alert = NodeExecutionTimeoutAlert(
        id=uuid.uuid4(),
        execution_id=execution.id,
        product_id=product_id,
        route_id=route_id,
        node_id=node_id,
        estimated_duration_seconds=3600,
        estimate_sample_count=5,
        expected_finish_at=expected,
        status=alert_status,
    )
    route = ProcessRoute(id=route_id, route_name="路线 V1")
    node = RouteNode(
        id=node_id,
        route_id=route_id,
        node_code="N1",
        name="反应",
        stage_name="反应段",
        sort_order=1,
    )
    return TimeoutMonitorContext(alert, execution, batch, node, route, "产品 A"), started_at


def test_timeout_status_equal_expected_finish_is_overdue() -> None:
    context, started_at = _context()
    assert timeout_monitor_status(
        context.alert,
        execution_status="in_progress",
        now_dt=started_at + timedelta(hours=1),
    ) == "overdue"
    assert timeout_monitor_status(
        context.alert,
        execution_status="in_progress",
        now_dt=started_at + timedelta(minutes=59),
    ) == "monitoring"


@pytest.mark.parametrize(
    ("execution_status", "batch_status"),
    [
        ("completed", "in_progress"),
        ("aborted", "in_progress"),
        ("in_progress", "completed"),
        ("in_progress", "cancelled"),
    ],
)
def test_terminal_execution_or_batch_never_remains_overdue(
    execution_status: str,
    batch_status: str,
) -> None:
    """完成、中止或批次终态后，扫描/接口语义均为已解决。"""

    context, started_at = _context()
    assert timeout_monitor_status(
        context.alert,
        execution_status=execution_status,
        batch_status=batch_status,
        now_dt=started_at + timedelta(days=2),
    ) == "resolved"


def test_timeout_status_terminal_and_sent_states() -> None:
    context, started_at = _context(alert_status="sent")
    assert timeout_monitor_status(
        context.alert,
        execution_status="in_progress",
        now_dt=started_at + timedelta(hours=2),
    ) == "sent"

    context.alert.status = "resolved"
    assert timeout_monitor_status(
        context.alert,
        execution_status="in_progress",
        now_dt=started_at + timedelta(hours=2),
    ) == "resolved"
    assert timeout_monitor_status(
        context.alert,
        execution_status="completed",
        now_dt=started_at + timedelta(hours=2),
    ) == "resolved"


def test_no_alert_means_no_monitor_for_completed_but_not_started_is_not_reminded() -> None:
    context, started_at = _context()
    assert timeout_monitor_status(
        None,
        execution_status="in_progress",
        now_dt=started_at,
    ) == "not_monitored"
    assert timeout_monitor_status(
        None,
        execution_status="completed",
        now_dt=started_at,
    ) is None


class _FakeResult:
    def __init__(self, row: tuple[int, float | None]) -> None:
        self.row = row

    def one(self) -> tuple[int, float | None]:
        return self.row


class _RowcountResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _BaselineDb:
    """只捕获查询语句的最小 AsyncSession 替身。"""

    def __init__(self, row: tuple[int, float | None]) -> None:
        self.row = row
        self.statement = None

    async def execute(self, statement: object) -> _FakeResult:
        self.statement = statement
        return _FakeResult(self.row)


@pytest.mark.parametrize(
    ("sample_count", "expected"),
    [(3, None), (4, None), (5, "baseline")],
)
async def test_baseline_requires_at_least_five_samples(
    monkeypatch: pytest.MonkeyPatch,
    sample_count: int,
    expected: str | None,
) -> None:
    """少于 5 条即使数学上可求 P80 也不建立超时基线。"""

    product_id = uuid.uuid4()
    route_id = uuid.uuid4()
    node_id = uuid.uuid4()
    observed_at = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)

    async def fake_family(*_: object, **__: object) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        return {node_id}, {route_id}

    monkeypatch.setattr(timeout_repo, "_resolve_node_family", fake_family)
    db = _BaselineDb((sample_count, 3600.0))
    baseline = await timeout_repo.get_node_duration_p80_baseline(
        db,  # type: ignore[arg-type]
        product_id=product_id,
        route_id=route_id,
        node_id=node_id,
        now_dt=observed_at,
        window_days=365,
        min_samples=5,
    )

    if expected is None:
        assert baseline is None
    else:
        assert baseline is not None
        assert baseline.estimate_sample_count == 5
        assert baseline.estimate_method == "p80"
        assert baseline.estimate_window_days == 365


async def test_baseline_query_uses_full_one_year_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """年度窗口只纳入 observed_at 往前 365 天内的开始记录。"""

    product_id = uuid.uuid4()
    route_id = uuid.uuid4()
    node_id = uuid.uuid4()
    observed_at = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)

    async def fake_family(*_: object, **__: object) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        return {node_id}, {route_id}

    monkeypatch.setattr(timeout_repo, "_resolve_node_family", fake_family)
    db = _BaselineDb((5, 5400.0))
    baseline = await timeout_repo.get_node_duration_p80_baseline(
        db,  # type: ignore[arg-type]
        product_id=product_id,
        route_id=route_id,
        node_id=node_id,
        now_dt=observed_at,
        window_days=365,
        min_samples=5,
    )
    assert baseline is not None
    assert baseline.estimate_window_days == 365

    compiled = db.statement.compile(dialect=postgresql.dialect())  # type: ignore[union-attr]
    assert observed_at - timedelta(days=365) in compiled.params.values()
    assert observed_at in compiled.params.values()


async def test_timeout_baseline_forwarding_uses_adaptive_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """开始工序把 180 天优先、365 天回退策略交给仓储聚合。"""

    class _Redis:
        async def set(self, *_: object, **__: object) -> bool:
            return True

        async def eval(self, *_: object, **__: object) -> int:
            return 1

    aggregate = AsyncMock(return_value=None)
    monkeypatch.setattr(timeout_service, "_get_cached_baseline", AsyncMock(return_value=None))
    monkeypatch.setattr(timeout_service, "redis_client", _Redis())
    monkeypatch.setattr(timeout_service, "cache_set", AsyncMock())
    monkeypatch.setattr(timeout_service.repo, "get_node_duration_p80_baseline", aggregate)

    await timeout_service.get_timeout_baseline(
        object(),  # type: ignore[arg-type]
        product_id=uuid.uuid4(),
        route_id=uuid.uuid4(),
        node_id=uuid.uuid4(),
    )
    kwargs = aggregate.call_args.kwargs
    assert kwargs["window_days"] == 180
    assert kwargs["fallback_window_days"] == 365
    assert kwargs["min_samples"] == 5
    assert kwargs["percentile"] == 0.8


def test_timeout_baseline_cache_keys_separate_recent_and_annual_windows() -> None:
    """近期与年度回退结果不能共用缓存键，避免窗口口径串用。"""

    product_id = uuid.uuid4()
    route_id = uuid.uuid4()
    node_id = uuid.uuid4()
    recent_key = timeout_service._cache_key(
        product_id, route_id, node_id, window_days=180,
    )
    annual_key = timeout_service._cache_key(
        product_id, route_id, node_id, window_days=365,
    )
    assert recent_key != annual_key
    assert recent_key.endswith(":180")
    assert annual_key.endswith(":365")


async def test_renew_timeout_monitor_lease_checks_current_token() -> None:
    """发送期间续租只更新当前 sending worker 持有的令牌。"""

    class _UpdateDb:
        def __init__(self) -> None:
            self.statement = None

        async def execute(self, statement: object) -> _RowcountResult:
            self.statement = statement
            return _RowcountResult(1)

    db = _UpdateDb()
    alert_id = uuid.uuid4()
    observed_at = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    renewed = await timeout_repo.renew_timeout_monitor_lease(
        db,  # type: ignore[arg-type]
        alert_id,
        lease_token="lease-token",
        lease_seconds=300,
        now_dt=observed_at,
    )
    assert renewed is True
    compiled = db.statement.compile(dialect=postgresql.dialect())  # type: ignore[union-attr]
    assert "lease-token" in compiled.params.values()
    assert observed_at + timedelta(seconds=300) in compiled.params.values()


async def test_timeout_baseline_cache_hit_skips_history_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命中 Redis 基线后不再执行历史聚合查询。"""

    baseline = NodeDurationBaseline(
        estimated_duration_seconds=3600.0,
        estimate_sample_count=5,
        estimate_method="p80",
        estimate_window_days=365,
        estimate_version=timeout_service.TIMEOUT_ESTIMATE_VERSION,
        product_id=uuid.uuid4(),
        route_id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        computed_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    )
    cached = AsyncMock(return_value=baseline)
    aggregate = AsyncMock()
    monkeypatch.setattr(timeout_service, "_get_any_cached_baseline", cached)
    monkeypatch.setattr(timeout_service.repo, "get_node_duration_p80_baseline", aggregate)

    result = await timeout_service.get_timeout_baseline(
        object(),  # type: ignore[arg-type]
        product_id=baseline.product_id,
        route_id=baseline.route_id,
        node_id=baseline.node_id,
    )
    assert result is baseline
    cached.assert_awaited_once()
    aggregate.assert_not_awaited()


async def test_insufficient_baseline_writes_short_negative_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两个窗口都不足样本时写入 60 秒负缓存，避免连续开始重复聚合。"""

    class _Redis:
        async def set(self, *_: object, **__: object) -> bool:
            return True

        async def eval(self, *_: object) -> int:
            return 1

    aggregate = AsyncMock(return_value=None)
    cache_write = AsyncMock()
    monkeypatch.setattr(
        timeout_service,
        "_get_any_cached_baseline",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(timeout_service, "redis_client", _Redis())
    monkeypatch.setattr(timeout_service, "cache_set", cache_write)
    monkeypatch.setattr(
        timeout_service.repo,
        "get_node_duration_p80_baseline",
        aggregate,
    )

    product_id, route_id, node_id = (uuid.uuid4() for _ in range(3))
    result = await timeout_service.get_timeout_baseline(
        object(),  # type: ignore[arg-type]
        product_id=product_id,
        route_id=route_id,
        node_id=node_id,
    )

    assert result is None
    aggregate.assert_awaited_once()
    cache_write.assert_awaited_once()
    cache_key, cache_value = cache_write.call_args.args[:2]
    assert cache_key == timeout_service._cache_key(
        product_id, route_id, node_id, window_days=180,
    )
    assert cache_value == timeout_service._NEGATIVE_BASELINE_CACHE_MARKER
    assert cache_write.call_args.kwargs["ex"] == (
        timeout_service.TIMEOUT_NEGATIVE_CACHE_TTL_SECONDS
    )


async def test_negative_baseline_cache_hit_skips_history_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负缓存命中直接保持未监控，不再查询历史聚合。"""

    cached = AsyncMock(return_value=timeout_service._NEGATIVE_BASELINE_CACHE_HIT)
    aggregate = AsyncMock()
    monkeypatch.setattr(timeout_service, "_get_any_cached_baseline", cached)
    monkeypatch.setattr(
        timeout_service.repo,
        "get_node_duration_p80_baseline",
        aggregate,
    )

    result = await timeout_service.get_timeout_baseline(
        object(),  # type: ignore[arg-type]
        product_id=uuid.uuid4(),
        route_id=uuid.uuid4(),
        node_id=uuid.uuid4(),
    )

    assert result is None
    cached.assert_awaited_once()
    aggregate.assert_not_awaited()


async def test_recent_negative_cache_does_not_hide_annual_positive_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """新样本已写入年度正缓存时，近期负哨兵不能遮蔽它。"""

    baseline = NodeDurationBaseline(
        estimated_duration_seconds=5400.0,
        estimate_sample_count=5,
        estimate_method="p80",
        estimate_window_days=365,
        estimate_version=timeout_service.TIMEOUT_ESTIMATE_VERSION,
        product_id=uuid.uuid4(),
        route_id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        computed_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    )
    cached_values = iter(
        [timeout_service._NEGATIVE_BASELINE_CACHE_HIT, baseline]
    )

    async def fake_get_cached(*_: object, **__: object):
        return next(cached_values)

    monkeypatch.setattr(timeout_service, "_get_cached_baseline", fake_get_cached)
    result = await timeout_service._get_any_cached_baseline(
        baseline.product_id,
        baseline.route_id,
        baseline.node_id,
    )
    assert result is baseline


class _SequenceBaselineDb:
    """返回多轮聚合结果并保留每一轮 SQL，验证窗口回退顺序。"""

    def __init__(self, rows: list[tuple[int, float | None]]) -> None:
        self.rows = list(rows)
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult(self.rows.pop(0))


async def test_repository_falls_back_from_180_days_to_one_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """180 天样本不足时再查年度窗口，并在快照记录实际采用的 365 天。"""

    product_id = uuid.uuid4()
    route_id = uuid.uuid4()
    node_id = uuid.uuid4()
    observed_at = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)

    async def fake_family(*_: object, **__: object) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        return {node_id}, {route_id}

    monkeypatch.setattr(timeout_repo, "_resolve_node_family", fake_family)
    db = _SequenceBaselineDb([(3, 3000.0), (5, 5400.0)])
    baseline = await timeout_repo.get_node_duration_p80_baseline(
        db,  # type: ignore[arg-type]
        product_id=product_id,
        route_id=route_id,
        node_id=node_id,
        now_dt=observed_at,
        window_days=180,
        fallback_window_days=365,
        min_samples=5,
    )
    assert baseline is not None
    assert baseline.estimate_sample_count == 5
    assert baseline.estimate_window_days == 365
    assert len(db.statements) == 2
    compiled = [
        statement.compile(dialect=postgresql.dialect())  # type: ignore[union-attr]
        for statement in db.statements
    ]
    assert observed_at - timedelta(days=180) in compiled[0].params.values()
    assert observed_at - timedelta(days=365) in compiled[1].params.values()


async def test_repository_does_not_query_year_when_180_day_samples_suffice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """180 天已有 5 条有效记录时只做一次近期聚合，节省数据库资源。"""

    product_id = uuid.uuid4()
    route_id = uuid.uuid4()
    node_id = uuid.uuid4()
    observed_at = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)

    async def fake_family(*_: object, **__: object) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        return {node_id}, {route_id}

    monkeypatch.setattr(timeout_repo, "_resolve_node_family", fake_family)
    db = _SequenceBaselineDb([(5, 5400.0)])
    baseline = await timeout_repo.get_node_duration_p80_baseline(
        db,  # type: ignore[arg-type]
        product_id=product_id,
        route_id=route_id,
        node_id=node_id,
        now_dt=observed_at,
        window_days=180,
        fallback_window_days=365,
        min_samples=5,
    )
    assert baseline is not None
    assert baseline.estimate_window_days == 180
    assert len(db.statements) == 1


async def test_repository_does_not_create_baseline_when_both_windows_are_small(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """近 180 天和近一年都不足 5 条时，保持不监控。"""

    product_id = uuid.uuid4()
    route_id = uuid.uuid4()
    node_id = uuid.uuid4()

    async def fake_family(*_: object, **__: object) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        return {node_id}, {route_id}

    monkeypatch.setattr(timeout_repo, "_resolve_node_family", fake_family)
    db = _SequenceBaselineDb([(3, 3000.0), (4, 4800.0)])
    baseline = await timeout_repo.get_node_duration_p80_baseline(
        db,  # type: ignore[arg-type]
        product_id=product_id,
        route_id=route_id,
        node_id=node_id,
        window_days=180,
        fallback_window_days=365,
        min_samples=5,
    )
    assert baseline is None
    assert len(db.statements) == 2


async def test_five_sample_baseline_freezes_expected_finish_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第五条样本到来后，开始时创建一次快照并冻结预计完成时间。"""

    context, started_at = _context()
    baseline = NodeDurationBaseline(
        estimated_duration_seconds=5400.0,
        estimate_sample_count=5,
        estimate_method="p80",
        estimate_window_days=365,
        estimate_version=timeout_service.TIMEOUT_ESTIMATE_VERSION,
        product_id=context.batch.product_id,
        route_id=context.batch.route_id,
        node_id=context.execution.node_id,
        computed_at=started_at,
    )
    created = NodeExecutionTimeoutAlert(
        id=uuid.uuid4(),
        execution_id=context.execution.id,
        product_id=context.batch.product_id,
        route_id=context.batch.route_id,
        node_id=context.execution.node_id,
        estimated_duration_seconds=5400.0,
        estimate_sample_count=5,
        estimate_window_days=365,
        estimate_method="p80",
        expected_finish_at=started_at + timedelta(seconds=5400),
    )
    create_mock = AsyncMock(return_value=created)
    monkeypatch.setattr(timeout_service, "get_timeout_baseline", AsyncMock(return_value=baseline))
    monkeypatch.setattr(timeout_service.repo, "create_timeout_monitor", create_mock)

    result = await timeout_service.create_timeout_monitor_for_execution(
        object(),  # type: ignore[arg-type]
        context.execution,
        context.batch,
        now_dt=started_at,
    )
    assert result is created
    kwargs = create_mock.call_args.kwargs
    assert kwargs["estimated_duration_seconds"] == 5400.0
    assert kwargs["estimate_sample_count"] == 5
    assert kwargs["estimate_window_days"] == 365
    assert kwargs["expected_finish_at"] == started_at + timedelta(seconds=5400)


async def test_not_started_execution_does_not_query_baseline_or_create_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未点击开始（没有 started_at）不进入超时监控。"""

    context, _ = _context()
    context.execution.started_at = None  # type: ignore[assignment]
    baseline_mock = AsyncMock()
    create_mock = AsyncMock()
    monkeypatch.setattr(timeout_service, "get_timeout_baseline", baseline_mock)
    monkeypatch.setattr(timeout_service.repo, "create_timeout_monitor", create_mock)

    result = await timeout_service.create_timeout_monitor_for_execution(
        object(),  # type: ignore[arg-type]
        context.execution,
        context.batch,
    )
    assert result is None
    baseline_mock.assert_not_awaited()
    create_mock.assert_not_awaited()


async def test_timeout_recipients_stop_at_execution_owner_and_merge_extras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命中执行负责人后不向节点/工段扩散，但仍合并额外人员并去重。"""

    context, _ = _context()
    owner_id = uuid.uuid4()
    extra_id = uuid.uuid4()
    context.execution.owner_id = owner_id
    node_lookup = AsyncMock()
    stage_lookup = AsyncMock()
    open_lookup = AsyncMock(
        return_value={owner_id: "ou_owner", extra_id: "ou_extra"},
    )
    monkeypatch.setattr(reminder_service, "list_node_assignments", node_lookup)
    monkeypatch.setattr(reminder_service, "list_stage_assignments", stage_lookup)
    monkeypatch.setattr(reminder_service, "_user_open_ids", open_lookup)

    db = object()
    recipients, open_ids = await reminder_service._timeout_recipients(
        db, context, [extra_id, owner_id, extra_id],  # type: ignore[arg-type]
    )
    assert recipients == [owner_id, extra_id]
    assert open_ids == {owner_id: "ou_owner", extra_id: "ou_extra"}
    node_lookup.assert_not_awaited()
    stage_lookup.assert_not_awaited()
    open_lookup.assert_awaited_once_with(db, [owner_id, extra_id])


async def test_timeout_recipients_fall_back_node_then_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无执行负责人时使用节点负责人；节点也为空时才使用工段负责人。"""

    context, _ = _context()
    node_id = uuid.uuid4()
    stage_id = uuid.uuid4()
    extra_id = uuid.uuid4()
    node_lookup = AsyncMock(
        return_value=[SimpleNamespace(user_id=node_id)],
    )
    stage_lookup = AsyncMock(
        return_value=[SimpleNamespace(stage_name=context.node.stage_name, user_id=stage_id)],
    )
    monkeypatch.setattr(reminder_service, "list_node_assignments", node_lookup)
    monkeypatch.setattr(reminder_service, "list_stage_assignments", stage_lookup)
    monkeypatch.setattr(
        reminder_service,
        "_user_open_ids",
        AsyncMock(return_value={node_id: "ou_node", extra_id: "ou_extra"}),
    )

    db = object()
    recipients, _ = await reminder_service._timeout_recipients(
        db, context, [extra_id],  # type: ignore[arg-type]
    )
    assert recipients == [node_id, extra_id]
    stage_lookup.assert_not_awaited()

    node_lookup.return_value = []
    recipients, _ = await reminder_service._timeout_recipients(
        db, context, [extra_id],  # type: ignore[arg-type]
    )
    assert recipients == [stage_id, extra_id]
    stage_lookup.assert_awaited_once()


def test_percentile_cont_interpolation_and_retry_backoff() -> None:
    # 数学上 3 条记录也能插值计算 P80，但业务门槛仍由上面的基线测试约束为 5 条。
    assert _percentile([1.0, 2.0, 3.0], 0.8) == 2.6
    assert _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.8) == 4.2
    assert _percentile([], 0.8) is None
    assert _timeout_retry_delay(1) == 60
    assert _timeout_retry_delay(2) == 120
    assert _timeout_retry_delay(5) == 960
    assert _timeout_retry_delay(99) == 1800


def test_timeout_card_marks_deviation_and_rework_without_declaring_abnormal() -> None:
    context, started_at = _context(execution_seq=2, is_deviation=True)
    content = _build_timeout_content(
        context,
        observed_at=started_at + timedelta(hours=2),
    )
    assert "工序可能超时，请确认并更新进度" in content
    assert "偏离流程" in content
    assert "第 2 次执行（返工/重做）" in content
    assert "生产异常" not in content
    assert "预计时长（P80）" in content
    # 飞书提醒不带跳转链接，收件人直接回系统查看。
    assert "打开执行详情" not in content
    assert "http" not in content


def test_timeout_scheduler_runs_every_ten_minutes() -> None:
    assert EXECUTION_TIMEOUT_SCAN_TASK.schedule.strategy == ScheduleStrategy.INTERVAL
    assert EXECUTION_TIMEOUT_SCAN_TASK.schedule.interval_seconds == 600
