"""batch_service 业务规则测试。

注意：本文件不依赖 execution_service（Task 9 才实现）。需要"父批次已完成某工序"
的前置状态时，直接用 ORM 插入 NodeExecution 行构造。
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
    batch.status = "in_progress"
    await db.flush()


async def _insert_completed_execution(
    db: AsyncSession, batch: Batch, node_id: uuid.UUID
) -> None:
    """直接构造一条 completed 执行（绕过 execution_service）。"""
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
        batch = await _make_batch(db_session, published_route)
        assert batch.status == "pending"
        assert batch.entry_node_id is None

    async def test_duplicate_batch_no_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
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
        parent = await _make_batch(db_session, published_route)  # pending
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
        parent = await _make_batch(db_session, published_route)
        await _set_in_progress(db_session, parent)
        # 父批次在边界边 from_node（发酵A）上没有 completed 执行 → 拒绝
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
        batch = await _make_batch(db_session, published_route)
        cancelled = await batch_service.cancel_batch(db_session, batch.id, user=None)
        assert cancelled.status == "cancelled"

    async def test_cancel_twice_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        batch = await _make_batch(db_session, published_route)
        await batch_service.cancel_batch(db_session, batch.id, user=None)
        with pytest.raises(AppException):
            await batch_service.cancel_batch(db_session, batch.id, user=None)


class TestListSort:
    async def test_list_batches_order_by_batch_no_asc(
        self, db_session: AsyncSession
    ) -> None:
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
