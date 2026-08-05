"""计划项状态与批次执行联动测试。

覆盖：
- repo 谱系/覆盖查询
- sync_plan_item_status 判定：allocated 保持、开工置 in_progress、节点覆盖置 completed、
  单线拆分链、报废换批、工段子集配置、手工批次 no-op
- execution/batch 触发点端到端
"""

import uuid
from datetime import datetime, timedelta, UTC

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production import repository as repo
from app.modules.production.models import Batch, BatchLink, NodeExecution
from app.modules.production.models.planning import PlanItem
from app.modules.production.schemas import (
    BatchCreate,
    ChildBatchIn,
    DeriveIn,
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldValueIn,
    PlanItemCreate,
    PlanItemScheduleIn,
    PlanOrderCreate,
)
from app.modules.production.schemas.planning import StageConfigItem
from app.modules.production.service import (
    assignment_service,
    batch_service,
    execution_service,
    planning_service,
    workbench_service,
)
from app.platform.identity.models import User
from tests.modules.production.conftest import rand_code


async def _get_or_create_user(db: AsyncSession) -> User:
    """获取已有测试用户，若无则创建。"""
    stmt = select(User).where(User.is_deleted == False).limit(1)  # noqa: E712
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name="测试用户", employee_no="TEST001")
    db.add(user)
    await db.flush()
    return user


async def _make_batch(db: AsyncSession, ctx: dict) -> Batch:
    """创建一条不归属计划单的手工批次。"""
    return await batch_service.create_batch(
        db,
        BatchCreate(batch_no=rand_code("B"), product_id=ctx["product"].id, route_id=ctx["route"].id),
        user=None,
    )


async def _make_plan_batch(
    db: AsyncSession,
    ctx: dict,
    user: User,
    stage_durations: list[StageConfigItem] | None = None,
) -> tuple[PlanItem, Batch]:
    """创建计划单 + 计划项 + 排程 + 下达，返回 (计划项, 根批次)。"""
    order = await planning_service.create_plan_order(
        db,
        PlanOrderCreate(
            order_no=rand_code("PO"),
            title="计划单",
            product_id=ctx["product"].id,
            route_id=ctx["route"].id,
            priority="medium",
        ),
        user=user,
    )
    item = await planning_service.create_plan_item(
        db,
        order.id,
        PlanItemCreate(
            product_id=ctx["product"].id,
            product_name="中间体X",
            route_id=ctx["route"].id,
            planned_quantity=100,
            unit="kg",
            batch_no=rand_code("I"),
            priority="medium",
            stage_durations=stage_durations,
        ),
        user=user,
    )
    now = datetime.now(UTC)
    await planning_service.schedule_plan_item(
        db,
        item.id,
        PlanItemScheduleIn(planned_start=now, planned_end=now + timedelta(hours=8)),
        user=user,
    )
    await planning_service.confirm_plan_order(db, order.id, user=user)
    await planning_service.release_plan_order(db, order.id, user=user)
    batch_id = (await repo.get_plan_allocations_by_item(db, item.id))[0].batch_id
    batch = await repo.get_batch(db, batch_id)
    assert batch is not None
    return item, batch


async def _activate(db: AsyncSession, batch: Batch, ctx: dict, user: User) -> None:
    """给用户分配第一工段（发酵）权限并激活计划批次。"""
    await assignment_service.create_stage_assignment(
        db,
        user_id=user.id,
        stage_name="发酵",
        route_id=ctx["route"].id,
        created_by=user.id,
    )
    await workbench_service.activate_planned_batch(db, batch.id, user)


def _field_values_for(defs: list, phase: str) -> list[FieldValueIn]:
    """为指定 phase 的必填字段生成合法测试值（real service 会校验必填字段）。"""
    values = []
    for d in defs:
        if d.phase != phase or not d.required:
            continue
        if d.data_type == "numeric":
            lo = d.min_value if d.min_value is not None else -100.0
            hi = d.max_value if d.max_value is not None else 100.0
            value = round((lo + hi) / 2, 1)
        elif d.data_type == "boolean":
            value = True
        elif d.data_type == "select":
            value = d.options[0] if d.options else "a"
        else:
            value = "test"
        values.append(FieldValueIn(field_key=d.field_key, value=value))
    return values


async def _run_node(db: AsyncSession, batch: Batch, node) -> None:
    """在该批次上开始并完成一个节点的执行（自动填充必填字段）。"""
    defs = list(getattr(node, "fields", None) or [])
    ex = await execution_service.start_execution(
        db, batch.id,
        ExecutionStartIn(node_id=node.id, field_values=_field_values_for(defs, "start")),
        user=None,
    )
    await execution_service.complete_execution(
        db, ex.id,
        ExecutionCompleteIn(field_values=_field_values_for(defs, "end")),
        user=None,
    )


async def _derive(db: AsyncSession, parent: Batch, ctx: dict) -> Batch:
    """从父批次沿 A→B 边界边拆出单子批次。"""
    # derive 要求父批次 in_progress/completed 且边界边起点工序已完结，测试里直接置位
    parent.status = "in_progress"
    existing = (
        await db.execute(
            select(NodeExecution.id).where(
                NodeExecution.batch_id == parent.id,
                NodeExecution.node_id == ctx["node_a"].id,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if existing is None:
        now = datetime.now(UTC)
        db.add(
            NodeExecution(
                batch_id=parent.id,
                node_id=ctx["node_a"].id,
                execution_seq=1,
                status="completed",
                started_at=now,
                finished_at=now,
            )
        )
    await db.flush()
    children = await batch_service.derive_batches(
        db,
        parent.id,
        DeriveIn(
            edge_id=ctx["edge_ab"].id,
            children=[ChildBatchIn(batch_no=rand_code("B"))],
        ),
        user=None,
    )
    return children[0]


class TestRepoSyncQueries:
    async def test_get_parent_batch_id(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """子批次能回溯到父批次；根批次无父返回 None。"""
        ctx = published_route
        parent = await _make_batch(db_session, ctx)
        child = await _derive(db_session, parent, ctx)
        assert await repo.get_parent_batch_id(db_session, child.id) == parent.id
        assert await repo.get_parent_batch_id(db_session, parent.id) is None

    async def test_get_child_batch_ids(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """父批次能看到全部非删除子批次。"""
        ctx = published_route
        parent = await _make_batch(db_session, ctx)
        child1 = await _derive(db_session, parent, ctx)
        child2 = await _derive(db_session, parent, ctx)
        ids = set(await repo.get_child_batch_ids(db_session, parent.id))
        assert ids == {child1.id, child2.id}

    async def test_get_completed_node_ids_by_batches(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """只统计 completed 执行，in_progress 与 aborted 不计。"""
        ctx = published_route
        batch = await _make_batch(db_session, ctx)
        await _run_node(db_session, batch, ctx["node_a"])  # completed
        ex = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=ctx["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25.5)],
            ),
            user=None,
        )
        # ex 保持 in_progress
        assert await repo.get_completed_node_ids_by_batches(
            db_session, [batch.id],
        ) == {ctx["node_a"].id}
        assert ctx["node_b"].id not in await repo.get_completed_node_ids_by_batches(
            db_session, [batch.id],
        )
        assert await repo.get_completed_node_ids_by_batches(db_session, []) == set()


class TestSyncCore:
    async def test_allocated_stays_until_batch_in_progress(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """release 后批次 scheduled，sync 不改状态；批次 in_progress 后 sync 置 in_progress。"""
        user = await _get_or_create_user(db_session)
        item, batch = await _make_plan_batch(db_session, published_route, user)
        assert item.status == "allocated"
        await planning_service.sync_plan_item_status(db_session, batch.id)
        assert (await repo.get_plan_item(db_session, item.id)).status == "allocated"
        batch.status = "in_progress"
        await planning_service.sync_plan_item_status(db_session, batch.id)
        assert (await repo.get_plan_item(db_session, item.id)).status == "in_progress"

    async def test_completed_when_all_nodes_done(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """未配置工段 = route 全量判定：A/B/C 全部完成后 sync 置 completed。"""
        user = await _get_or_create_user(db_session)
        item, batch = await _make_plan_batch(db_session, published_route, user)
        batch.status = "in_progress"
        await planning_service.sync_plan_item_status(db_session, batch.id)
        await _run_node(db_session, batch, published_route["node_a"])
        await _run_node(db_session, batch, published_route["node_b"])
        await planning_service.sync_plan_item_status(db_session, batch.id)
        assert (await repo.get_plan_item(db_session, item.id)).status == "in_progress"
        await _run_node(db_session, batch, published_route["node_c"])
        await planning_service.sync_plan_item_status(db_session, batch.id)
        assert (await repo.get_plan_item(db_session, item.id)).status == "completed"

    async def test_completed_with_single_branch_split(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """单线拆分：根完成 A 后 derive 子批次，子批次完成 B/C 后 sync 置 completed。"""
        user = await _get_or_create_user(db_session)
        item, batch = await _make_plan_batch(db_session, published_route, user)
        batch.status = "in_progress"
        await _run_node(db_session, batch, published_route["node_a"])
        child = await _derive(db_session, batch, published_route)
        await _run_node(db_session, child, published_route["node_b"])
        await _run_node(db_session, child, published_route["node_c"])
        await planning_service.sync_plan_item_status(db_session, child.id)
        assert (await repo.get_plan_item(db_session, item.id)).status == "completed"

    async def test_cancelled_then_rederive_completes(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """报废换批：子批次报废后从父重新拆分，新子批次完成后 sync 置 completed。"""
        user = await _get_or_create_user(db_session)
        item, batch = await _make_plan_batch(db_session, published_route, user)
        batch.status = "in_progress"
        await _run_node(db_session, batch, published_route["node_a"])
        child1 = await _derive(db_session, batch, published_route)
        await batch_service.cancel_batch(db_session, child1.id, user=None)
        # 报废后覆盖未满，保持 in_progress
        await planning_service.sync_plan_item_status(db_session, child1.id)
        assert (await repo.get_plan_item(db_session, item.id)).status == "in_progress"
        child2 = await _derive(db_session, batch, published_route)
        await _run_node(db_session, child2, published_route["node_b"])
        await _run_node(db_session, child2, published_route["node_c"])
        await planning_service.sync_plan_item_status(db_session, child2.id)
        assert (await repo.get_plan_item(db_session, item.id)).status == "completed"

    async def test_cancelled_middle_chain_skips_to_live_grandchild(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """中间批次报废但存续孙批次仍有效：cancelled 不打断判定，孙批次完成后 sync 置 completed。"""
        user = await _get_or_create_user(db_session)
        item, batch = await _make_plan_batch(db_session, published_route, user)
        batch.status = "in_progress"
        await _run_node(db_session, batch, published_route["node_a"])
        child = await _derive(db_session, batch, published_route)
        grandchild = await _derive(db_session, child, published_route)
        await batch_service.cancel_batch(db_session, child.id, user=None)
        await _run_node(db_session, grandchild, published_route["node_b"])
        await _run_node(db_session, grandchild, published_route["node_c"])
        await planning_service.sync_plan_item_status(db_session, grandchild.id)
        assert (await repo.get_plan_item(db_session, item.id)).status == "completed"

    async def test_stage_subset_config(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """配置工段子集：只配「提炼」，B 完成即 completed，A/C 无关。"""
        user = await _get_or_create_user(db_session)
        stages = [StageConfigItem(stage_name="提炼", duration_hours=8, color="#1890ff")]
        item, batch = await _make_plan_batch(
            db_session, published_route, user, stage_durations=stages,
        )
        batch.status = "in_progress"
        await _run_node(db_session, batch, published_route["node_a"])
        await planning_service.sync_plan_item_status(db_session, batch.id)
        assert (await repo.get_plan_item(db_session, item.id)).status == "in_progress"
        await _run_node(db_session, batch, published_route["node_b"])
        await planning_service.sync_plan_item_status(db_session, batch.id)
        assert (await repo.get_plan_item(db_session, item.id)).status == "completed"

    async def test_sync_noop_for_manual_batch(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """手工批次（无 PlanAllocation）触发 sync 不报错、不产生计划项变化。"""
        batch = await batch_service.create_batch(
            db_session,
            BatchCreate(batch_no=rand_code("B"), product_id=published_route["product"].id, route_id=published_route["route"].id),
            user=None,
        )
        await planning_service.sync_plan_item_status(db_session, batch.id)  # 不抛异常
        await _run_node(db_session, batch, published_route["node_a"])
        await planning_service.sync_plan_item_status(db_session, batch.id)  # 不抛异常


class TestExecutionTriggers:
    async def test_start_flips_item_to_in_progress(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """真实流程：下达 → 激活 → 首工序开始，计划项自动 in_progress。"""
        user = await _get_or_create_user(db_session)
        item, batch = await _make_plan_batch(db_session, published_route, user)
        assert item.status == "allocated"
        await _activate(db_session, batch, published_route, user)
        await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id), user=None,
        )
        assert (await repo.get_plan_item(db_session, item.id)).status == "in_progress"

    async def test_complete_flow_ends_with_completed(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """真实流程：完成全部工序后计划项自动 completed。"""
        user = await _get_or_create_user(db_session)
        item, batch = await _make_plan_batch(db_session, published_route, user)
        await _activate(db_session, batch, published_route, user)
        await _run_node(db_session, batch, published_route["node_a"])
        await _run_node(db_session, batch, published_route["node_b"])
        assert (await repo.get_plan_item(db_session, item.id)).status == "in_progress"
        await _run_node(db_session, batch, published_route["node_c"])
        assert (await repo.get_plan_item(db_session, item.id)).status == "completed"


class TestBatchTriggers:
    async def test_derive_keeps_item_in_progress(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """拆分后覆盖未满，计划项保持 in_progress 不误报完成。"""
        user = await _get_or_create_user(db_session)
        item, batch = await _make_plan_batch(db_session, published_route, user)
        await _activate(db_session, batch, published_route, user)
        await _run_node(db_session, batch, published_route["node_a"])
        child = await _derive(db_session, batch, published_route)
        # derive 触发点自动 sync
        assert (await repo.get_plan_item(db_session, item.id)).status == "in_progress"

    async def test_cancel_then_rederive_flow(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """端到端：报废（cancel 触发 sync 不置 cancelled）→ 换批 → 完成后自动 completed。"""
        user = await _get_or_create_user(db_session)
        item, batch = await _make_plan_batch(db_session, published_route, user)
        await _activate(db_session, batch, published_route, user)
        await _run_node(db_session, batch, published_route["node_a"])
        child1 = await _derive(db_session, batch, published_route)
        await batch_service.cancel_batch(db_session, child1.id, user=None)
        assert (await repo.get_plan_item(db_session, item.id)).status == "in_progress"
        child2 = await _derive(db_session, batch, published_route)
        await _run_node(db_session, child2, published_route["node_b"])
        await _run_node(db_session, child2, published_route["node_c"])
        assert (await repo.get_plan_item(db_session, item.id)).status == "completed"


class TestComputeProgress:
    """_compute_item_batch_progress 谱系链合并：子批次继承父批次已完成的工序进度。"""

    async def test_progress_merges_parent_completed_stages(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """根批次完成 A/B 后拆出 pending 子批次：进度显示链上最远 A/B 而非全灰。"""
        user = await _get_or_create_user(db_session)
        item, batch = await _make_plan_batch(db_session, published_route, user)
        await _activate(db_session, batch, published_route, user)
        await _run_node(db_session, batch, published_route["node_a"])
        await _run_node(db_session, batch, published_route["node_b"])
        child = await _derive(db_session, batch, published_route)

        from app.modules.production.service.planning_service import _compute_item_batch_progress
        progress = await _compute_item_batch_progress(db_session, batch)
        assert progress is not None
        # 批号取链末端（子批次），状态取链合并（有 in_progress → in_progress）
        assert progress.batch_no == child.batch_no
        assert progress.batch_status == "in_progress"
        # 最远执行工序 = 链上 sort_order 最远的（node_b），不因拆分而倒退
        assert progress.latest_stage == published_route["node_b"].name
        assert progress.latest_stage_status == "completed"
        assert [n.name for n in (progress.route_nodes or [])] == [
            published_route["node_a"].name,
            published_route["node_b"].name,
            published_route["node_c"].name,
        ]

    async def test_progress_without_split_uses_single_batch(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """未拆分：进度直接来自根批次自身。"""
        user = await _get_or_create_user(db_session)
        item, batch = await _make_plan_batch(db_session, published_route, user)
        await _activate(db_session, batch, published_route, user)
        await _run_node(db_session, batch, published_route["node_a"])

        from app.modules.production.service.planning_service import _compute_item_batch_progress
        progress = await _compute_item_batch_progress(db_session, batch)
        assert progress is not None
        assert progress.batch_no == batch.batch_no
        assert progress.latest_stage == published_route["node_a"].name
        assert progress.latest_stage_status == "completed"


    async def test_progress_full_route_single_batch(
        self, db_session: AsyncSession, published_route: dict,
    ) -> None:
        """单批沿用走完全路线（工段交接不拆分）：进度推进到最后一个节点。"""
        user = await _get_or_create_user(db_session)
        item, batch = await _make_plan_batch(db_session, published_route, user)
        await _activate(db_session, batch, published_route, user)
        await _run_node(db_session, batch, published_route["node_a"])
        await _run_node(db_session, batch, published_route["node_b"])
        await _run_node(db_session, batch, published_route["node_c"])

        from app.modules.production.service.planning_service import _compute_item_batch_progress
        progress = await _compute_item_batch_progress(db_session, batch)
        assert progress is not None
        assert progress.batch_no == batch.batch_no
        assert progress.latest_stage == published_route["node_c"].name
        assert progress.latest_stage_status == "completed"
