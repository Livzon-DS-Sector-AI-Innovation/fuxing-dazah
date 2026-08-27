"""生产模块飞书提醒测试。

纯函数：工段计划开始时间（缺口即停）、工序结束下一工序接收人判定、
计划批次开工提醒时间窗（08:31-08:35）、卡片内容构建。
集成：计划单下达 / 工序结束提醒数据收集（真实 DB，无飞书调用）。
"""

import uuid
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import Batch, PlanItem, PlanOrder
from app.modules.production.schemas import (
    EdgeIn,
    NodeIn,
    ProductCreate,
    RouteCreate,
    RouteGraphIn,
)
from app.modules.production.service import assignment_service, route_service
from app.modules.production.service.reminder_service import (
    PlanItemReminder,
    _build_batch_start_content,
    _build_pending_batches_content,
    _build_plan_released_content,
    _build_step_completed_content,
    _collect_plan_released_reminders,
    _collect_step_completed_reminders,
    _due_plan_batches,
    _first_stage_leaders,
    _fmt_dt,
    _in_reminder_window,
    _pending_batches,
    _plan_stage_start_times,
    _recipient_kind,
    _to_local,
)


class TestPlanStageStartTimes:
    def test_lists_all_stages_when_durations_complete(self) -> None:
        """全部工段配置时长：逐一累加前序时长，全部列出。"""
        start = datetime(2026, 8, 28, 8, 0)
        result = _plan_stage_start_times(
            start, ["发酵", "提炼", "精制"], {"发酵": 5.0, "提炼": 3.0, "精制": 6.0},
        )
        assert [s for s, _ in result] == ["发酵", "提炼", "精制"]
        assert result[0][1] == datetime(2026, 8, 28, 8, 0)
        assert result[1][1] == datetime(2026, 8, 28, 13, 0)
        assert result[2][1] == datetime(2026, 8, 28, 16, 0)

    def test_gap_stage_listed_but_following_not(self) -> None:
        """首个缺口工段本身列出（用前序时长可算），其后工段不列。"""
        start = datetime(2026, 8, 28, 8, 0)
        result = _plan_stage_start_times(
            start, ["发酵", "提炼", "精制"], {"发酵": 5.0},
        )
        assert [s for s, _ in result] == ["发酵", "提炼"]
        assert result[1][1] == datetime(2026, 8, 28, 13, 0)

    def test_middle_gap_stops_at_gap_stage(self) -> None:
        """中间工段缺时长：缺口工段开始时间可算，其后不列。"""
        start = datetime(2026, 8, 28, 8, 0)
        result = _plan_stage_start_times(
            start, ["发酵", "提炼", "精制", "包装"], {"发酵": 2.0, "精制": 4.0},
        )
        assert [s for s, _ in result] == ["发酵", "提炼"]
        assert result[1][1] == datetime(2026, 8, 28, 10, 0)

    def test_no_durations_lists_only_first_stage(self) -> None:
        """无任何时长配置：仅计划项开始时间（第一工段）。"""
        start = datetime(2026, 8, 28, 8, 0)
        assert _plan_stage_start_times(start, ["发酵", "提炼"], None) == [
            ("发酵", start),
        ]
        assert _plan_stage_start_times(start, ["发酵", "提炼"], {}) == [
            ("发酵", start),
        ]

    def test_none_planned_start_returns_empty(self) -> None:
        assert _plan_stage_start_times(None, ["发酵"], {"发酵": 5.0}) == []


class TestRecipientKind:
    def test_batch_boundary_notifies_stage_leader(self) -> None:
        """跨批次边界：下一批尚不存在，提醒工段负责人（即使同工段名）。"""
        assert _recipient_kind(is_batch_boundary=True, same_stage=True) == "stage_leader"

    def test_cross_stage_notifies_stage_leader(self) -> None:
        """同批次但跨工段：提醒下一工段负责人。"""
        assert _recipient_kind(is_batch_boundary=False, same_stage=False) == "stage_leader"

    def test_same_batch_same_stage_notifies_owner(self) -> None:
        """同批次同工段：提醒批次负责人。"""
        assert _recipient_kind(is_batch_boundary=False, same_stage=True) == "owner"


class TestReminderWindow:
    def test_window_accepts_0831_to_0835_exclusive_end(self) -> None:
        assert _in_reminder_window(time(8, 31)) is True
        assert _in_reminder_window(time(8, 34, 59)) is True
        assert _in_reminder_window(time(8, 35)) is False

    def test_before_window_rejected(self) -> None:
        assert _in_reminder_window(time(8, 30, 59)) is False
        assert _in_reminder_window(time(0, 0)) is False

    def test_evening_rejected(self) -> None:
        assert _in_reminder_window(time(18, 0)) is False


class TestCardContent:
    def test_fmt_dt_compact(self) -> None:
        assert _fmt_dt(datetime(2026, 8, 28, 8, 0)) == "08-28 08:00"

    def test_plan_released_content_lists_items_and_stage_times(self) -> None:
        item = PlanItemReminder(
            item_no=1,
            product_name="产品A",
            batch_no="PO001-1",
            stage_times=[
                ("发酵", datetime(2026, 8, 28, 8, 0)),
                ("提炼", datetime(2026, 8, 28, 13, 0)),
            ],
        )
        content = _build_plan_released_content("PO001", "八月排产", [item])
        assert "PO001" in content
        assert "八月排产" in content
        assert "计划项 1" in content and "产品A" in content and "PO001-1" in content
        assert "发酵：08-28 08:00" in content
        assert "提炼：08-28 13:00" in content

    def test_plan_released_content_multiple_items(self) -> None:
        items = [
            PlanItemReminder(
                item_no=i,
                product_name=f"产品{i}",
                batch_no=f"P-{i}",
                stage_times=[("发酵", datetime(2026, 8, 28, 8, 0))],
            )
            for i in (1, 2)
        ]
        content = _build_plan_released_content("PO001", "排产", items)
        assert "计划项 1" in content and "计划项 2" in content

    def test_batch_start_content(self) -> None:
        content = _build_batch_start_content(
            "P-1", "产品A", 12.5, "kg", datetime(2026, 8, 28, 14, 0),
        )
        assert "P-1" in content and "产品A" in content
        assert "12.5 kg" in content
        assert "08-28 14:00" in content

    def test_batch_start_content_without_quantity(self) -> None:
        content = _build_batch_start_content("P-1", "产品A", None, None, datetime(2026, 8, 28, 8, 0))
        assert "P-1" in content and "产品A" in content

    def test_step_completed_content_to_owner(self) -> None:
        content = _build_step_completed_content("B-1", "投料", "发酵", to_owner=True)
        assert "B-1" in content
        assert "投料" in content and "发酵" in content
        assert "请安排下一工序" in content

    def test_step_completed_content_to_stage_leader(self) -> None:
        content = _build_step_completed_content("B-1", "发酵", "提炼", to_owner=False)
        assert "B-1" in content
        assert "发酵" in content and "提炼" in content
        assert "请关注" in content


@pytest.fixture
async def same_stage_route(db_session: AsyncSession) -> dict[str, Any]:
    """同工段两工序路线：D(投料/发酵) --normal--> E(灭菌/发酵)。"""
    code = uuid.uuid4().hex[:8]
    product = await route_service.create_product(
        db_session,
        ProductCreate(product_name=f"同工段产品-{code}", product_code=f"P-{code}"),
        user=None,
    )
    route = await route_service.create_route(
        db_session, RouteCreate(product_id=product.id, route_name=f"同工段-{code}"), user=None
    )
    graph = RouteGraphIn(
        nodes=[
            NodeIn(node_code="D", name="投料", stage_name="发酵", sort_order=1),
            NodeIn(node_code="E", name="灭菌", stage_name="发酵", sort_order=2),
        ],
        edges=[EdgeIn(from_node_code="D", to_node_code="E")],
    )
    await route_service.save_graph(db_session, route.id, graph, user=None)
    route = await route_service.publish_route(db_session, route.id, user=None)
    g = await route_service.get_graph(db_session, route.id)
    nodes = {n.node_code: n for n in g.nodes}
    return {"product": product, "route": route, "node_d": nodes["D"], "node_e": nodes["E"]}


async def _make_batch(db: AsyncSession, route: Any, batch_no: str) -> Batch:
    batch = Batch(
        batch_no=batch_no,
        product_id=route.product_id,
        route_id=route.id,
        status="pending",
        creation_type="direct",
    )
    db.add(batch)
    await db.flush()
    return batch


class TestCollectStepCompletedReminders:
    async def test_last_node_returns_empty(self, db_session: AsyncSession, published_route: dict[str, Any]) -> None:
        """精制 C 无 normal 出边（仅 rework）：最后一道工序不提醒。"""
        batch = await _make_batch(db_session, published_route["route"], "B-LAST")
        result = await _collect_step_completed_reminders(db_session, batch, published_route["node_c"])
        assert result == []

    async def test_cross_stage_notifies_next_stage_leader(self, db_session: AsyncSession, published_route: dict[str, Any]) -> None:
        """提炼 B → 精制 C（同批次跨工段）：提醒精制工段负责人。"""
        batch = await _make_batch(db_session, published_route["route"], "B-X")
        batch.owner_user_id = uuid.uuid4()
        await db_session.flush()
        leader = uuid.uuid4()
        await assignment_service.create_stage_assignment(
            db_session, user_id=leader, stage_name="精制",
            route_id=published_route["route"].id, created_by=leader,
        )
        result = await _collect_step_completed_reminders(db_session, batch, published_route["node_b"])
        assert len(result) == 1
        assert result[0].to_owner is False
        assert result[0].next_node == "精制"
        assert result[0].user_ids == [leader]

    async def test_batch_boundary_notifies_next_stage_leader(self, db_session: AsyncSession, published_route: dict[str, Any]) -> None:
        """发酵 A --boundary--> 提炼 B：跨批次边界提醒提炼工段负责人。"""
        batch = await _make_batch(db_session, published_route["route"], "B-BD")
        batch.owner_user_id = uuid.uuid4()
        await db_session.flush()
        leader = uuid.uuid4()
        await assignment_service.create_stage_assignment(
            db_session, user_id=leader, stage_name="提炼",
            route_id=published_route["route"].id, created_by=leader,
        )
        result = await _collect_step_completed_reminders(db_session, batch, published_route["node_a"])
        assert len(result) == 1
        assert result[0].to_owner is False
        assert result[0].user_ids == [leader]

    async def test_same_stage_notifies_batch_owner(self, db_session: AsyncSession, same_stage_route: dict[str, Any]) -> None:
        """同批次同工段：提醒批次负责人。"""
        batch = await _make_batch(db_session, same_stage_route["route"], "B-OWN")
        owner = uuid.uuid4()
        batch.owner_user_id = owner
        await db_session.flush()
        result = await _collect_step_completed_reminders(db_session, batch, same_stage_route["node_d"])
        assert len(result) == 1
        assert result[0].to_owner is True
        assert result[0].user_ids == [owner]

    async def test_owner_missing_falls_back_to_stage_leader(self, db_session: AsyncSession, same_stage_route: dict[str, Any]) -> None:
        """同批次同工段但无归属人：回退提醒下一工段负责人。"""
        batch = await _make_batch(db_session, same_stage_route["route"], "B-NOOWN")
        leader = uuid.uuid4()
        await assignment_service.create_stage_assignment(
            db_session, user_id=leader, stage_name="发酵",
            route_id=same_stage_route["route"].id, created_by=leader,
        )
        result = await _collect_step_completed_reminders(db_session, batch, same_stage_route["node_d"])
        assert len(result) == 1
        assert result[0].to_owner is False
        assert result[0].user_ids == [leader]


class TestCollectPlanReleasedReminders:
    async def test_dedup_leaders_and_compute_stage_times(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """按 user 去重工段负责人；工段时间按缺口即停规则计算。"""
        route = published_route["route"]
        user1, user2 = uuid.uuid4(), uuid.uuid4()
        # user1 负责两个工段（去重验证），user2 负责一个
        await assignment_service.create_stage_assignment(
            db_session, user_id=user1, stage_name="发酵", route_id=route.id, created_by=user1,
        )
        await assignment_service.create_stage_assignment(
            db_session, user_id=user1, stage_name="提炼", route_id=route.id, created_by=user1,
        )
        await assignment_service.create_stage_assignment(
            db_session, user_id=user2, stage_name="精制", route_id=route.id, created_by=user2,
        )
        order = PlanOrder(
            order_no=f"PO-{uuid.uuid4().hex[:8]}", title="测试计划单",
            status="confirmed", product_id=route.product_id, route_id=route.id,
            stage_config=[
                {"stage_name": "发酵", "duration_hours": 5.0},
                {"stage_name": "提炼", "duration_hours": 3.0},
            ],
        )
        db_session.add(order)
        await db_session.flush()
        start = datetime(2026, 8, 28, 8, 0)
        item = PlanItem(
            plan_order_id=order.id, item_no=1, product_id=route.product_id,
            product_name="测试产品", route_id=route.id, planned_start=start,
            status="scheduled",
        )
        db_session.add(item)
        await db_session.flush()

        result = await _collect_plan_released_reminders(
            db_session, order, [item], {item.id: "PO-1"},
        )
        assert result is not None
        assert set(result.user_ids) == {user1, user2}
        assert len(result.items) == 1
        times = result.items[0].stage_times
        assert [s for s, _ in times] == ["发酵", "提炼", "精制"]
        assert times[0][1] == start
        assert times[1][1] == datetime(2026, 8, 28, 13, 0)
        assert times[2][1] == datetime(2026, 8, 28, 16, 0)

    async def test_item_duration_override(self, db_session: AsyncSession, published_route: dict[str, Any]) -> None:
        """计划项显式工段时长覆盖计划单配置。"""
        route = published_route["route"]
        leader = uuid.uuid4()
        await assignment_service.create_stage_assignment(
            db_session, user_id=leader, stage_name="发酵",
            route_id=route.id, created_by=leader,
        )
        order = PlanOrder(
            order_no=f"PO-{uuid.uuid4().hex[:8]}", title="测试计划单",
            status="confirmed", product_id=route.product_id, route_id=route.id,
            stage_config=[{"stage_name": "发酵", "duration_hours": 5.0}],
        )
        db_session.add(order)
        await db_session.flush()
        start = datetime(2026, 8, 28, 8, 0)
        item = PlanItem(
            plan_order_id=order.id, item_no=1, product_id=route.product_id,
            product_name="测试产品", route_id=route.id, planned_start=start,
            status="scheduled",
            stage_durations=[{"stage_name": "发酵", "duration_hours": 2.0}],
        )
        db_session.add(item)
        await db_session.flush()

        result = await _collect_plan_released_reminders(
            db_session, order, [item], {item.id: "PO-1"},
        )
        assert result is not None
        times = result.items[0].stage_times
        assert times[0][1] == start
        assert times[1][1] == datetime(2026, 8, 28, 10, 0)

    async def test_no_assignments_returns_none(self, db_session: AsyncSession, published_route: dict[str, Any]) -> None:
        """路线上没有任何工段负责人时不发送。"""
        route = published_route["route"]
        order = PlanOrder(
            order_no=f"PO-{uuid.uuid4().hex[:8]}", title="测试计划单",
            status="confirmed", product_id=route.product_id, route_id=route.id,
        )
        db_session.add(order)
        await db_session.flush()
        item = PlanItem(
            plan_order_id=order.id, item_no=1, product_id=route.product_id,
            product_name="测试产品", route_id=route.id,
            planned_start=datetime(2026, 8, 28, 8, 0), status="scheduled",
        )
        db_session.add(item)
        await db_session.flush()

        result = await _collect_plan_released_reminders(
            db_session, order, [item], {item.id: "PO-1"},
        )
        assert result is None


class TestDuePlanBatches:
    async def _setup_order_item(self, db_session: AsyncSession, route: Any, planned_start: datetime, status: str = "scheduled") -> Batch:
        """直接构造计划单+计划项+批次+分配，返回批次。"""
        order = PlanOrder(
            order_no=f"PO-{uuid.uuid4().hex[:8]}", title="排产",
            status="released", product_id=route.product_id, route_id=route.id,
        )
        db_session.add(order)
        await db_session.flush()
        item = PlanItem(
            plan_order_id=order.id, item_no=1, product_id=route.product_id,
            product_name="测试产品", route_id=route.id, planned_start=planned_start,
            status="allocated",
        )
        db_session.add(item)
        await db_session.flush()
        batch = Batch(
            batch_no=f"B-{uuid.uuid4().hex[:8]}", product_id=route.product_id,
            route_id=route.id, status=status, creation_type="plan",
        )
        db_session.add(batch)
        await db_session.flush()
        from app.modules.production.models import PlanAllocation

        db_session.add(PlanAllocation(plan_item_id=item.id, batch_id=batch.id))
        await db_session.flush()
        return batch

    async def test_returns_only_plan_batches_starting_today(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        today_start = datetime(2026, 8, 27, 14, 0)
        tomorrow_start = datetime(2026, 8, 28, 8, 0)
        batch_today = await self._setup_order_item(db_session, published_route["route"], today_start)
        await self._setup_order_item(db_session, published_route["route"], tomorrow_start)

        result = await _due_plan_batches(db_session, today_start.date())
        result_ids = {b.id for b, _ in result}
        # 共享 dev 库可能混入历史遗留的今日批次，只断言本次创建的批次
        assert batch_today.id in result_ids
        today_items = {i.product_name for _, i in result if i.id is not None}
        assert "测试产品" in today_items

    async def test_excludes_started_and_non_plan_batches(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        start = datetime(2026, 8, 27, 14, 0)
        in_progress = await self._setup_order_item(db_session, published_route["route"], start, status="in_progress")
        batch = Batch(
            batch_no=f"B-{uuid.uuid4().hex[:8]}", product_id=published_route["route"].product_id,
            route_id=published_route["route"].id, status="scheduled", creation_type="direct",
        )
        db_session.add(batch)
        await db_session.flush()
        result = await _due_plan_batches(db_session, start.date())
        result_ids = {b.id for b, _ in result}
        assert in_progress.id not in result_ids
        assert batch.id not in result_ids


class TestFirstStageLeaders:
    async def test_returns_only_first_stage_leaders(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        route = published_route["route"]
        first = uuid.uuid4()
        second = uuid.uuid4()
        await assignment_service.create_stage_assignment(
            db_session, user_id=first, stage_name="发酵", route_id=route.id, created_by=first,
        )
        await assignment_service.create_stage_assignment(
            db_session, user_id=second, stage_name="提炼", route_id=route.id, created_by=second,
        )
        result = await _first_stage_leaders(db_session, route.id)
        assert result == [first]


class TestToLocal:
    def test_aware_utc_converted_to_shanghai(self) -> None:
        """tz-aware（如 asyncpg 返回的 UTC）转 Asia/Shanghai 墙钟时间。"""
        dt = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)
        result = _to_local(dt)
        assert result == datetime(2026, 8, 28, 8, 0, tzinfo=timezone(timedelta(hours=8)))

    def test_naive_unchanged(self) -> None:
        """naive（前端本地时间直存）原样返回。"""
        dt = datetime(2026, 8, 28, 8, 0)
        assert _to_local(dt) == dt

    def test_none_returns_none(self) -> None:
        assert _to_local(None) is None


@pytest.fixture
async def split_route(db_session: AsyncSession) -> dict[str, Any]:
    """分裂路线：A(发酵) --boundary--> B1(提炼一/提炼) 与 B2(提炼二/提炼)。"""
    code = uuid.uuid4().hex[:8]
    product = await route_service.create_product(
        db_session,
        ProductCreate(product_name=f"分裂产品-{code}", product_code=f"P-{code}"),
        user=None,
    )
    route = await route_service.create_route(
        db_session, RouteCreate(product_id=product.id, route_name=f"分裂-{code}"), user=None
    )
    graph = RouteGraphIn(
        nodes=[
            NodeIn(node_code="A", name="发酵", stage_name="发酵", sort_order=1),
            NodeIn(node_code="B1", name="提炼一", stage_name="提炼", sort_order=2),
            NodeIn(node_code="B2", name="提炼二", stage_name="提炼", sort_order=3),
        ],
        edges=[
            EdgeIn(from_node_code="A", to_node_code="B1", is_batch_boundary=True),
            EdgeIn(from_node_code="A", to_node_code="B2", is_batch_boundary=True),
        ],
    )
    await route_service.save_graph(db_session, route.id, graph, user=None)
    route = await route_service.publish_route(db_session, route.id, user=None)
    g = await route_service.get_graph(db_session, route.id)
    nodes = {n.node_code: n for n in g.nodes}
    return {"product": product, "route": route, "node_a": nodes["A"]}


class TestSplitEdgesGrouped:
    async def test_split_edges_merge_into_one_card_per_recipient(
        self, db_session: AsyncSession, split_route: dict[str, Any],
    ) -> None:
        """同一工段负责人的多条出边合并为一张卡，下一工序名用顿号连接。"""
        batch = await _make_batch(db_session, split_route["route"], "B-SPLIT")
        leader = uuid.uuid4()
        await assignment_service.create_stage_assignment(
            db_session, user_id=leader, stage_name="提炼",
            route_id=split_route["route"].id, created_by=leader,
        )
        result = await _collect_step_completed_reminders(db_session, batch, split_route["node_a"])
        assert len(result) == 1
        assert result[0].to_owner is False
        assert result[0].next_node == "提炼一、提炼二"
        assert result[0].user_ids == [leader]


class TestPendingBatchesContent:
    def test_lists_each_pending_batch(self) -> None:
        content = _build_pending_batches_content(
            [("B-1", "产品A"), ("B-2", "产品B")],
        )
        assert "待开工批次" in content
        assert "B-1（产品A）" in content
        assert "B-2（产品B）" in content


class TestPendingBatchesQuery:
    async def test_returns_pending_batches_with_product_name(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """只返回 pending 批次并带产品名（共享 dev 库有遗留数据，用成员断言）。"""
        route = published_route["route"]
        p1 = await _make_batch(db_session, route, f"B-P1-{uuid.uuid4().hex[:6]}")
        p2 = await _make_batch(db_session, route, f"B-P2-{uuid.uuid4().hex[:6]}")
        running = await _make_batch(db_session, route, f"B-P3-{uuid.uuid4().hex[:6]}")
        running.status = "in_progress"
        await db_session.flush()

        result = await _pending_batches(db_session)
        by_no = {b.batch_no: name for b, name in result}
        assert p1.batch_no in by_no and p2.batch_no in by_no
        assert running.batch_no not in by_no
        assert by_no[p1.batch_no] == published_route["product"].product_name
