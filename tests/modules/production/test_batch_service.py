"""批次生命周期、分裂/合并谱系写入业务测试。

覆盖业务场景：
- 创建批次：只能在 published 路线上创建、批号唯一、进入 pending 状态
- 批次分裂（derive）：父批次必须是 in_progress/completed；通过边界边需起点工序已完成；
  无边界边必须提供偏离原因；偏离分裂子批次无 entry_node；
  payload 中批号重复拒绝
- 批次合并（merge）：父批次不能重复；多父批次合并为一个子批次
- 批次生命周期：完成需要至少一个已完成工序；报废 pending 批次；重复报废拒绝
- 列表排序：按 batch_no 升序排列
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.production.models import Batch, NodeExecution
from app.modules.production.schemas import (
    BatchCreate,
    ChildBatchIn,
    DeriveIn,
    MergeIn,
    MergeParentIn,
)
from app.modules.production.service import batch_service
from tests.modules.production.conftest import rand_code


async def _make_batch(db: AsyncSession, ctx: dict[str, Any]) -> Batch:
    """辅助：在已发布路线上下文中创建测试批次。"""
    return await batch_service.create_batch(
        db,
        BatchCreate(
            batch_no=rand_code("B"),
            product_id=ctx["product"].id,
            route_id=ctx["route"].id,
            quantity=100,
            unit="kg",
        ),
        user=None,
    )


async def _set_in_progress(db: AsyncSession, batch: Batch) -> None:
    """辅助：直接设置批次状态为 in_progress。"""
    batch.status = "in_progress"
    await db.flush()


async def _insert_completed_execution(
    db: AsyncSession, batch: Batch, node_id: uuid.UUID
) -> None:
    """辅助：直接构造一条 completed 执行记录（绕过 execution_service）。"""
    now = datetime.now(UTC)
    db.add(
        NodeExecution(
            batch_id=batch.id,
            node_id=node_id,
            execution_seq=1,
            status="completed",
            started_at=now,
            finished_at=now,
        )
    )
    await db.flush()


class TestCreateBatch:
    async def test_create_on_published_route(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """在 published 路线上创建批次，状态为 pending 且 entry_node_id 为空。"""
        batch = await _make_batch(db_session, published_route)
        assert batch.status == "pending"
        assert batch.entry_node_id is None

    async def test_duplicate_batch_no_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """重复批号创建时抛出 AppException。"""
        batch = await _make_batch(db_session, published_route)
        with pytest.raises(AppException):
            await batch_service.create_batch(
                db_session,
                BatchCreate(
                    batch_no=batch.batch_no,
                    product_id=published_route["product"].id,
                    route_id=published_route["route"].id,
                ),
                user=None,
            )


class TestDerive:
    async def test_pending_parent_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """pending 状态的父批次不能派生，抛出 AppException。"""
        parent = await _make_batch(db_session, published_route)
        with pytest.raises(AppException):
            await batch_service.derive_batches(
                db_session,
                parent.id,
                DeriveIn(
                    deviation_reason="x",
                    children=[ChildBatchIn(batch_no=rand_code("B"))],
                ),
                user=None,
            )

    async def test_derive_requires_completed_execution_at_from_node(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """通过边界边派生时父批次未完成起点工序则拒绝。"""
        parent = await _make_batch(db_session, published_route)
        await _set_in_progress(db_session, parent)
        with pytest.raises(AppException):
            await batch_service.derive_batches(
                db_session,
                parent.id,
                DeriveIn(
                    edge_id=published_route["edge_ab"].id,
                    children=[ChildBatchIn(batch_no=rand_code("B"))],
                ),
                user=None,
            )

    async def test_derive_without_edge_requires_reason(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """不指定边界边且无偏离原因时派生被拒。"""
        parent = await _make_batch(db_session, published_route)
        await _set_in_progress(db_session, parent)
        with pytest.raises(AppException):
            await batch_service.derive_batches(
                db_session,
                parent.id,
                DeriveIn(children=[ChildBatchIn(batch_no=rand_code("B"))]),
                user=None,
            )

    async def test_derive_via_boundary_edge_sets_entry_node(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """通过批次边界边派生，子批次 entry_node_id 指向边终点。"""
        parent = await _make_batch(db_session, published_route)
        await _set_in_progress(db_session, parent)
        await _insert_completed_execution(
            db_session, parent, published_route["node_a"].id
        )
        children = await batch_service.derive_batches(
            db_session,
            parent.id,
            DeriveIn(
                edge_id=published_route["edge_ab"].id,
                children=[
                    ChildBatchIn(batch_no=rand_code("B"), quantity=40),
                    ChildBatchIn(batch_no=rand_code("B"), quantity=60),
                ],
            ),
            user=None,
        )
        assert len(children) == 2
        assert all(c.status == "pending" for c in children)
        assert all(
            c.entry_node_id == published_route["node_b"].id for c in children
        )

    async def test_derive_deviation_has_no_entry_node(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """偏离派生（仅 deviation_reason 无 edge_id）的子批次 entry_node_id 为 None。"""
        parent = await _make_batch(db_session, published_route)
        await _set_in_progress(db_session, parent)
        children = await batch_service.derive_batches(
            db_session,
            parent.id,
            DeriveIn(
                deviation_reason="现场临时分批",
                children=[ChildBatchIn(batch_no=rand_code("B"))],
            ),
            user=None,
        )
        assert children[0].entry_node_id is None

    async def test_derive_duplicate_child_no_in_payload_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """派生请求中 children 列表含重复批号时抛出 AppException。"""
        parent = await _make_batch(db_session, published_route)
        await _set_in_progress(db_session, parent)
        dup_no = rand_code("B")
        with pytest.raises(AppException):
            await batch_service.derive_batches(
                db_session,
                parent.id,
                DeriveIn(
                    deviation_reason="x",
                    children=[
                        ChildBatchIn(batch_no=dup_no),
                        ChildBatchIn(batch_no=dup_no),
                    ],
                ),
                user=None,
            )


class TestMerge:
    async def test_merge_duplicate_parent_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """合并时父批次列表含重复 ID 抛出 AppException。"""
        p1 = await _make_batch(db_session, published_route)
        await _set_in_progress(db_session, p1)
        with pytest.raises(AppException):
            await batch_service.merge_batches(
                db_session,
                MergeIn(
                    parents=[
                        MergeParentIn(batch_id=p1.id, allocated_qty=50),
                        MergeParentIn(batch_id=p1.id, allocated_qty=50),
                    ],
                    deviation_reason="测试合并",
                    batch_no=rand_code("M"),
                    quantity=100,
                ),
                user=None,
            )

    async def test_merge_creates_single_child(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """两个父批次合并为一个子批次，子批次状态为 pending，批号正确。"""
        p1 = await _make_batch(db_session, published_route)
        p2 = await _make_batch(db_session, published_route)
        await _set_in_progress(db_session, p1)
        await _set_in_progress(db_session, p2)
        merged = await batch_service.merge_batches(
            db_session,
            MergeIn(
                parents=[
                    MergeParentIn(batch_id=p1.id, allocated_qty=50),
                    MergeParentIn(batch_id=p2.id, allocated_qty=50),
                ],
                deviation_reason="测试合并",
                batch_no=rand_code("M"),
                quantity=100,
            ),
            user=None,
        )
        assert merged.status == "pending"
        detail = await batch_service.get_batch_detail(db_session, merged.id)
        assert detail.batch_no == merged.batch_no


class TestLifecycle:
    async def test_complete_requires_completed_execution(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """无已完成工序的 in_progress 批次完成时被拒；完成工序后即可完成。"""
        batch = await _make_batch(db_session, published_route)
        await _set_in_progress(db_session, batch)
        with pytest.raises(AppException):
            await batch_service.complete_batch(db_session, batch.id, user=None)
        await _insert_completed_execution(
            db_session, batch, published_route["node_a"].id
        )
        done = await batch_service.complete_batch(db_session, batch.id, user=None)
        assert done.status == "completed"

    async def test_cancel(self, db_session: AsyncSession, published_route: dict[str, Any]) -> None:
        """pending 批次可直接报废，状态变为 cancelled。"""
        batch = await _make_batch(db_session, published_route)
        cancelled = await batch_service.cancel_batch(db_session, batch.id, user=None)
        assert cancelled.status == "cancelled"

    async def test_cancel_twice_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """已报废的批次再次报废时抛出 AppException。"""
        batch = await _make_batch(db_session, published_route)
        await batch_service.cancel_batch(db_session, batch.id, user=None)
        with pytest.raises(AppException):
            await batch_service.cancel_batch(db_session, batch.id, user=None)


class TestListSort:
    async def test_list_batches_order_by_batch_no_asc(
        self, db_session: AsyncSession
    ) -> None:
        """按批号升序排列批次列表时结果正确排序。"""
        from app.modules.production import repository as repo
        from app.modules.production.models import Batch as BatchModel

        product_id = uuid.uuid4()
        base = uuid.uuid4().hex[:8]
        for suffix in ("b", "a", "c"):
            db_session.add(
                BatchModel(
                    batch_no=f"{base}-{suffix}",
                    product_id=product_id,
                    route_id=uuid.uuid4(),
                )
            )
        await db_session.flush()
        items, total = await repo.list_batches(
            db_session, product_id, None, None,
            page=1, page_size=20, order_by="batch_no", order="asc",
        )
        assert total == 3
        assert [b.batch_no for b in items] == [f"{base}-{s}" for s in ("a", "b", "c")]
