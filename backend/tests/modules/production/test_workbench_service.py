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

import pytest
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
    route_service,
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


async def _get_or_create_user_named(db: AsyncSession, employee_no: str) -> User:
    """按工号获取或创建用户（同一测试内需要多个不同用户时使用）。"""
    from sqlalchemy import select

    stmt = select(User).where(
        User.employee_no == employee_no, User.is_deleted == False  # noqa: E712
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name=f"测试-{employee_no}", employee_no=employee_no)
    db.add(user)
    await db.flush()
    return user


class TestBatchOwnerIsolation:
    """多负责人批次归属隔离：操作即归属 + 软隔离（all 仅读）+ 共享认领池。"""

    @pytest.fixture(autouse=True)
    def _mock_perms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """mock 权限码查询：避免 Redis 连接跨测试事件循环报 Event loop is closed。"""
        from app.modules.production.service import execution_service as es

        async def fake(user_id: str, db: AsyncSession) -> set[str]:
            return set()

        monkeypatch.setattr(es, "get_user_permissions", fake)

    async def _make_owner(
        self, db: AsyncSession, employee_no: str, route_id: uuid.UUID, stage_name: str,
    ) -> User:
        user = await _get_or_create_user_named(db, employee_no)
        await assignment_service.create_stage_assignment(
            db,
            user_id=user.id,
            stage_name=stage_name,
            route_id=route_id,
            created_by=user.id,
        )
        return user

    async def _make_batch(
        self, db: AsyncSession, published_route: dict[str, Any],
    ) -> Any:
        return await batch_service.create_batch(
            db,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
            ),
            user=None,
        )

    async def test_start_claims_unowned_batch(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """无主批次：谁先开始归谁。"""
        from sqlalchemy import select

        from app.modules.production.models import Batch

        user_a = await self._make_owner(db_session, "OWN-A", published_route["route"].id, "发酵")
        batch = await self._make_batch(db_session, published_route)
        await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=user_a,
        )
        refreshed = (
            await db_session.execute(select(Batch).where(Batch.id == batch.id))
        ).scalar_one()
        assert refreshed.owner_user_id == user_a.id
        assert refreshed.owner_name == user_a.name

    async def test_mine_hides_other_owner_and_all_readonly(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """A 认领批次后：B 的 mine 视图不可见；all 视图可见但仅读。"""
        route_id = published_route["route"].id
        user_a = await self._make_owner(db_session, "OWN-A", route_id, "发酵")
        user_b = await self._make_owner(db_session, "OWN-B", route_id, "发酵")
        batch = await self._make_batch(db_session, published_route)
        await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=user_a,
        )
        mine_b = await workbench_service.query_workbench(db_session, user_b.id)
        assert all(it.batch_id != batch.id for it in mine_b.items)

        all_b = await workbench_service.query_workbench(
            db_session, user_b.id, view_mode="all",
        )
        others = [it for it in all_b.items if it.batch_id == batch.id]
        assert len(others) >= 1
        assert all(not it.can_operate for it in others)
        assert all(it.batch_owner_name == user_a.name for it in others)

    async def test_unowned_batch_visible_to_both(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """无主批次对同工段所有负责人可见可操作（共享认领）。"""
        route_id = published_route["route"].id
        user_a = await self._make_owner(db_session, "OWN-A", route_id, "发酵")
        user_b = await self._make_owner(db_session, "OWN-B", route_id, "发酵")
        batch = await self._make_batch(db_session, published_route)
        for user in (user_a, user_b):
            result = await workbench_service.query_workbench(db_session, user.id)
            starts = [it for it in result.items if it.batch_id == batch.id]
            assert len(starts) >= 1
            assert all(it.can_operate for it in starts)

    async def test_other_owner_cannot_start(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """归属他人的批次：开始工序被拒绝。"""
        from app.core.exceptions import ForbiddenException

        route_id = published_route["route"].id
        user_a = await self._make_owner(db_session, "OWN-A", route_id, "发酵")
        user_b = await self._make_owner(db_session, "OWN-B", route_id, "发酵")
        batch = await self._make_batch(db_session, published_route)
        ex = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=user_a,
        )
        # A 完成后释放节点，B 再开始时才会走到归属校验（而非「已有进行中执行」）
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=user_a,
        )
        with pytest.raises(ForbiddenException):
            await execution_service.start_execution(
                db_session, batch.id,
                ExecutionStartIn(
                    node_id=published_route["node_a"].id,
                    deviation_reason="测试偏离",
                ),
                user=user_b,
            )

    async def test_node_owner_can_start_other_owner_batch(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """归属他人的批次：工序级负责人（NodeAssignment）可开始自己负责的工序。"""
        route_id = published_route["route"].id
        user_a = await self._make_owner(db_session, "OWN-A", route_id, "发酵")
        node_owner = await _get_or_create_user_named(db_session, "NODE-OWN")
        await assignment_service.create_node_assignment(
            db_session,
            user_id=node_owner.id,
            node_id=published_route["node_b"].id,
            route_id=route_id,
            assigned_by=node_owner.id,
        )
        batch = await self._make_batch(db_session, published_route)
        # A 开始 node_a 认领批次并完成，释放来路
        ex = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=user_a,
        )
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=user_a,
        )
        # 工序级负责人跨归属开始自己负责的工序 → 成功
        ex2 = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                owner_id=node_owner.id,
                owner_name=node_owner.name,
                field_values=[FieldValueIn(field_key="temp", value=25)],
            ),
            user=node_owner,
        )
        assert ex2.status == "in_progress"
        assert ex2.owner_id == node_owner.id

    async def test_pending_receive_not_filtered_by_owner(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """待接收是共享认领池：上游批次即使归属他人，下游工段负责人仍可见可接收。"""
        route_id = published_route["route"].id
        user_up = await self._make_owner(db_session, "OWN-UP", route_id, "发酵")
        user_down = await self._make_owner(db_session, "OWN-DOWN", route_id, "提炼")
        parent = await self._make_batch(db_session, published_route)
        ex = await execution_service.start_execution(
            db_session, parent.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=user_up,
        )
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=user_up,
        )
        mine_down = await workbench_service.query_workbench(db_session, user_down.id)
        receives = [
            it for it in mine_down.items
            if it.type == "pending_receive" and it.batch_id == parent.id
        ]
        assert len(receives) >= 1
        assert all(it.can_operate for it in receives)

    async def test_derive_child_owned_by_receiver(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """接收（derive）创建的子批次归属接收人。"""
        from sqlalchemy import select

        from app.modules.production.models import Batch
        from app.modules.production.schemas import DeriveIn

        route_id = published_route["route"].id
        # 发酵工段用于执行 node_a，提炼工段用于边界接收（新规则：接收工段负责人）
        user_up = await self._make_owner(db_session, "OWN-UP", route_id, "发酵")
        await self._make_owner(db_session, "OWN-UP", route_id, "提炼")
        parent = await self._make_batch(db_session, published_route)
        ex = await execution_service.start_execution(
            db_session, parent.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=user_up,
        )
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=user_up,
        )
        children = await batch_service.derive_batches(
            db_session, parent.id,
            DeriveIn(
                edge_id=published_route["edge_ab"].id,
                children=[ChildBatchIn(batch_no=rand_code("C"), quantity=1.0)],
            ),
            user=user_up,
        )
        child = (
            await db_session.execute(select(Batch).where(Batch.id == children[0].id))
        ).scalar_one()
        assert child.owner_user_id == user_up.id
        assert child.owner_name == user_up.name


class TestReceiveSuggestion:
    """接收建议子批次号：根批号 + 目标工段尾缀（覆盖式）。"""

    @pytest.fixture(autouse=True)
    def _mock_perms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """mock 权限码查询：避免 Redis 连接跨测试事件循环报 Event loop is closed。"""
        from app.modules.production.service import execution_service as es

        async def fake(user_id: str, db: AsyncSession) -> set[str]:
            return set()

        monkeypatch.setattr(es, "get_user_permissions", fake)

    async def _make_downstream_owner(
        self, db: AsyncSession, route_id: uuid.UUID,
    ) -> uuid.UUID:
        """分配提炼工段负责人，返回 user_id。"""
        user_id = uuid.uuid4()
        await assignment_service.create_stage_assignment(
            db, user_id=user_id, stage_name="提炼",
            route_id=route_id, created_by=user_id,
        )
        return user_id

    async def _complete_node_a(
        self, db: AsyncSession, batch: Any, published_route: dict[str, Any],
    ) -> None:
        ex = await execution_service.start_execution(
            db, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        await execution_service.complete_execution(
            db, ex.id, ExecutionCompleteIn(), user=None,
        )

    async def test_suggested_batch_no_with_suffix(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """单父接收卡片：建议批号 = 根批号 + 目标工段尾缀。"""
        route_id = published_route["route"].id
        user_id = await self._make_downstream_owner(db_session, route_id)
        await assignment_service.set_stage_suffix(
            db_session, user_id=user_id, route_id=route_id,
            stage_name="提炼", suffix="-T1",
        )
        batch_no = rand_code("ROOT")
        batch = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=batch_no,
                product_id=published_route["product"].id,
                route_id=route_id,
            ),
            user=None,
        )
        await self._complete_node_a(db_session, batch, published_route)

        result = await workbench_service.query_workbench(db_session, user_id)
        receives = [
            it for it in result.items
            if it.type == "pending_receive" and it.batch_id == batch.id
        ]
        assert len(receives) == 1
        assert receives[0].suggested_batch_no == f"{batch_no}-T1"

    async def test_no_suffix_returns_none(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """未配置尾缀时，建议批号为空。"""
        route_id = published_route["route"].id
        user_id = await self._make_downstream_owner(db_session, route_id)
        batch = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=route_id,
            ),
            user=None,
        )
        await self._complete_node_a(db_session, batch, published_route)

        result = await workbench_service.query_workbench(db_session, user_id)
        receives = [
            it for it in result.items
            if it.type == "pending_receive" and it.batch_id == batch.id
        ]
        assert len(receives) == 1
        assert receives[0].suggested_batch_no is None

    async def test_suggested_uses_root_batch_no_across_chain(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """多级链条：建议批号取谱系根批号（覆盖式，不带父层尾缀）。"""
        from app.modules.production.models import BatchLink

        route_id = published_route["route"].id
        user_id = await self._make_downstream_owner(db_session, route_id)
        await assignment_service.set_stage_suffix(
            db_session, user_id=user_id, route_id=route_id,
            stage_name="提炼", suffix="-T2",
        )
        root = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("ROOT"),
                product_id=published_route["product"].id,
                route_id=route_id,
            ),
            user=None,
        )
        mid = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=f"{root.batch_no}-T1",
                product_id=published_route["product"].id,
                route_id=route_id,
            ),
            user=None,
        )
        db_session.add(BatchLink(
            parent_batch_id=root.id, child_batch_id=mid.id,
            edge_id=None, is_deviation=True,
        ))
        await db_session.flush()
        await self._complete_node_a(db_session, mid, published_route)

        result = await workbench_service.query_workbench(db_session, user_id)
        receives = [
            it for it in result.items
            if it.type == "pending_receive" and it.batch_id == mid.id
        ]
        assert len(receives) == 1
        # 覆盖式：根批号 + 当前工段尾缀，而非 父批号 + 尾缀
        assert receives[0].suggested_batch_no == f"{root.batch_no}-T2"

    async def test_merge_card_has_no_suggestion(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """合并接收卡片不生成建议批号（合并仍手填）。"""
        from app.modules.production.schemas import (
            EdgeIn,
            NodeIn,
            ProductCreate,
            RouteCreate,
            RouteGraphIn,
        )

        product = await route_service.create_product(
            db_session,
            ProductCreate(
                product_name=rand_code("合并产品"), product_code=rand_code("MP"),
            ),
            user=None,
        )
        route = await route_service.create_route(
            db_session,
            RouteCreate(product_id=product.id, route_name="合并V1"),
            user=None,
        )
        await route_service.save_graph(
            db_session, route.id,
            RouteGraphIn(
                nodes=[
                    NodeIn(node_code="A1", name="发酵一", stage_name="发酵", sort_order=1),
                    NodeIn(node_code="A2", name="发酵二", stage_name="发酵", sort_order=2),
                    NodeIn(node_code="B", name="提炼", stage_name="提炼", sort_order=3),
                ],
                edges=[
                    EdgeIn(from_node_code="A1", to_node_code="B", is_batch_boundary=True),
                    EdgeIn(from_node_code="A2", to_node_code="B", is_batch_boundary=True),
                ],
            ),
            user=None,
        )
        await route_service.publish_route(db_session, route.id, user=None)
        graph = await route_service.get_graph(db_session, route.id)
        nodes = {n.node_code: n for n in graph.nodes}

        user_id = await self._make_downstream_owner(db_session, route.id)
        await assignment_service.set_stage_suffix(
            db_session, user_id=user_id, route_id=route.id,
            stage_name="提炼", suffix="-M1",
        )
        batches = []
        for code, no in (("A1", rand_code("P1")), ("A2", rand_code("P2"))):
            b = await batch_service.create_batch(
                db_session,
                BatchCreate(batch_no=no, product_id=product.id, route_id=route.id),
                user=None,
            )
            ex = await execution_service.start_execution(
                db_session, b.id,
                ExecutionStartIn(node_id=nodes[code].id),
                user=None,
            )
            await execution_service.complete_execution(
                db_session, ex.id, ExecutionCompleteIn(), user=None,
            )
            batches.append(b)

        result = await workbench_service.query_workbench(db_session, user_id)
        receives = [
            it for it in result.items
            if it.type == "pending_receive"
            and set(it.parent_batch_ids) == {b.id for b in batches}
        ]
        assert len(receives) == 1
        assert receives[0].suggested_batch_no is None


class TestExecutionOwnerWorkbench:
    """单次执行负责人（开始工序时指定的 owner）的工作台可见性。

    无工段/工序身份的执行负责人：能看到自己进行中执行的待结束卡片
    （can_operate=True，批次归属他人也可见），不出现开始/接收类卡片。
    """

    async def test_owner_sees_pending_complete_for_others_batch(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        user_id = uuid.uuid4()  # 无任何工段/工序身份
        batch = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
            ),
            user=None,
        )
        batch.owner_user_id = uuid.uuid4()  # 批次归属他人
        ex = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=published_route["node_a"].id,
                owner_id=user_id,
                owner_name="执行人",
            ),
            user=None,
        )
        result = await workbench_service.query_workbench(db_session, user_id)
        completes = [it for it in result.items if it.type == "pending_complete"]
        assert len(completes) == 1
        assert completes[0].execution_id == ex.id
        assert completes[0].can_operate is True
        # 执行负责人不能开始任何工序，也不出现开始/接收卡片
        assert not [it for it in result.items if it.type == "pending_start"]
        assert not [it for it in result.items if it.type == "pending_receive"]

    async def test_owner_card_gone_after_complete(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """执行结束后卡片消失：单次执行负责人的权限随执行结束自然到期。"""
        user_id = uuid.uuid4()
        batch = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
            ),
            user=None,
        )
        batch.owner_user_id = uuid.uuid4()
        ex = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=published_route["node_a"].id,
                owner_id=user_id,
                owner_name="执行人",
            ),
            user=None,
        )
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=None,
        )
        result = await workbench_service.query_workbench(db_session, user_id)
        assert result.items == []
