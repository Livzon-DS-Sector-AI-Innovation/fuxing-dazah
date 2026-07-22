"""工作台待办查询与接收并开始执行测试。

覆盖业务场景：
- 未分配权限的用户查询工作台返回空
- 工段负责人视角：pending_start（起点节点可开始）、pending_receive（边界边完成可接收）、
  pending_complete（进行中执行可完成）、assigned_routes 结构
- 工序负责人视角：pending_start
- 接收并开始：单父批次 derive + 可选立即开始执行
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.schemas import (
    BatchCreate,
    ChildBatchIn,
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldValueIn,
    ReceiveAndStartIn,
)
from app.modules.production.service import (
    assignment_service,
    batch_service,
    execution_service,
    workbench_service,
)
from app.platform.identity.models import User
from tests.modules.production.conftest import rand_code


async def _get_or_create_user(db: AsyncSession) -> User:
    """获取已有测试用户，若无则创建。"""
    from sqlalchemy import select

    stmt = select(User).where(User.is_deleted == False).limit(1)  # noqa: E712
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name="测试用户", employee_no="TEST001")
    db.add(user)
    await db.flush()
    return user


class TestWorkbenchQuery:
    async def test_empty_for_user_without_assignments(
        self, db_session: AsyncSession,
    ) -> None:
        """未分配任何权限的用户查询工作台，items 为空。"""
        result = await workbench_service.query_workbench(
            db_session, uuid.uuid4(),
        )
        assert result.role == "node_owner"
        assert result.items == []

    async def test_stage_owner_sees_pending_start(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """工段负责人能看到其工段内起点节点的 pending_start 待办。"""
        user_id = uuid.uuid4()
        route_id = published_route["route"].id
        await assignment_service.create_stage_assignment(
            db_session,
            user_id=user_id,
            stage_name="发酵",  # node_a 的工段
            route_id=route_id,
            created_by=user_id,
        )
        await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=route_id,
            ),
            user=None,
        )
        result = await workbench_service.query_workbench(db_session, user_id)
        assert result.role == "stage_owner"
        pending_starts = [it for it in result.items if it.type == "pending_start"]
        assert len(pending_starts) >= 1
        assert pending_starts[0].node_id == published_route["node_a"].id

    async def test_node_owner_sees_pending_start(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """工序负责人能看到其负责节点的 pending_start 待办。"""
        user_id = uuid.uuid4()
        node_id = published_route["node_a"].id
        route_id = published_route["route"].id
        await assignment_service.create_node_assignment(
            db_session,
            user_id=user_id,
            node_id=node_id,
            route_id=route_id,
            assigned_by=user_id,
        )
        await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=route_id,
            ),
            user=None,
        )
        result = await workbench_service.query_workbench(db_session, user_id)
        assert result.role == "node_owner"
        pending_starts = [it for it in result.items if it.type == "pending_start"]
        assert len(pending_starts) >= 1

    async def test_pending_receive_after_boundary_complete(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """边界边起点工序完成后，下游工段负责人能看到 pending_receive。"""
        user_id = uuid.uuid4()
        route_id = published_route["route"].id
        await assignment_service.create_stage_assignment(
            db_session,
            user_id=user_id,
            stage_name="提炼",
            route_id=route_id,
            created_by=user_id,
        )
        batch = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=route_id,
            ),
            user=None,
        )
        ex = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=None,
        )
        result = await workbench_service.query_workbench(db_session, user_id)
        receives = [it for it in result.items if it.type == "pending_receive"]
        assert len(receives) >= 1

    async def test_pending_complete_for_in_progress_execution(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """工段内有进行中的执行时产生 pending_complete 待办，且 is_last_in_stage 为 True。"""
        user_id = uuid.uuid4()
        route_id = published_route["route"].id
        await assignment_service.create_stage_assignment(
            db_session,
            user_id=user_id,
            stage_name="发酵",
            route_id=route_id,
            created_by=user_id,
        )
        batch = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=route_id,
            ),
            user=None,
        )
        await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        result = await workbench_service.query_workbench(db_session, user_id)
        completes = [it for it in result.items if it.type == "pending_complete"]
        assert len(completes) >= 1
        assert completes[0].is_last_in_stage is True

    async def test_assigned_routes_structure(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """assigned_routes 返回路线及工段/节点结构信息。"""
        user_id = uuid.uuid4()
        route_id = published_route["route"].id
        await assignment_service.create_stage_assignment(
            db_session,
            user_id=user_id,
            stage_name="发酵",
            route_id=route_id,
            created_by=user_id,
        )
        result = await workbench_service.query_workbench(db_session, user_id)
        assert len(result.assigned_routes) >= 1
        route_info = result.assigned_routes[0]
        assert route_info.route_id == route_id
        assert len(route_info.stages) >= 1


class TestReceiveAndStart:
    async def test_receive_single_parent(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """单父批次 derive：完成 A 后通过边界边 derive 子批次。"""
        user = await _get_or_create_user(db_session)
        route_id = published_route["route"].id
        await assignment_service.create_stage_assignment(
            db_session,
            user_id=user.id,
            stage_name="发酵",
            route_id=route_id,
            created_by=user.id,
        )
        parent = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("P"),
                product_id=published_route["product"].id,
                route_id=route_id,
            ),
            user=None,
        )
        ex = await execution_service.start_execution(
            db_session, parent.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=None,
        )
        child_no = rand_code("C")
        result = await workbench_service.receive_and_start(
            db_session,
            ReceiveAndStartIn(
                parent_batch_ids=[parent.id],
                edge_id=published_route["edge_ab"].id,
                children=[ChildBatchIn(batch_no=child_no)],
            ),
            user=user,
        )
        assert len(result["children"]) == 1
        assert result["children"][0]["batch_no"] == child_no

    async def test_receive_and_start_execution(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """接收后立即开始：derive 子批次并自动在 B 节点开始执行。"""
        user = await _get_or_create_user(db_session)
        route_id = published_route["route"].id
        await assignment_service.create_stage_assignment(
            db_session,
            user_id=user.id,
            stage_name="发酵",
            route_id=route_id,
            created_by=user.id,
        )
        await assignment_service.create_stage_assignment(
            db_session,
            user_id=user.id,
            stage_name="提炼",
            route_id=route_id,
            created_by=user.id,
        )
        parent = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("P"),
                product_id=published_route["product"].id,
                route_id=route_id,
            ),
            user=None,
        )
        ex = await execution_service.start_execution(
            db_session, parent.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=None,
        )
        child_no = rand_code("C")
        result = await workbench_service.receive_and_start(
            db_session,
            ReceiveAndStartIn(
                parent_batch_ids=[parent.id],
                edge_id=published_route["edge_ab"].id,
                children=[ChildBatchIn(batch_no=child_no)],
                start_execution=True,
                execution=ExecutionStartIn(
                    node_id=published_route["node_b"].id,
                    field_values=[FieldValueIn(field_key="temp", value=25)],
                ),
            ),
            user=user,
        )
        assert result["execution"] is not None
        assert result["execution"]["status"] == "in_progress"
