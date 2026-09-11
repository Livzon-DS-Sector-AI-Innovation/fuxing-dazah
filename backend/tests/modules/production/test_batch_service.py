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

from app.core.exceptions import (
    AppException,
    DuplicateException,
    ForbiddenException,
)
from app.modules.production import repository as repo
from app.modules.production.models import (
    Batch,
    NodeExecution,
    PlanAllocation,
    PlanItem,
    PlanOrder,
    StageAssignment,
)
from app.modules.production.schemas import (
    BatchCreate,
    BatchNoUpdateIn,
    BatchOwnerTransferIn,
    ChildBatchIn,
    DeriveIn,
    MergeIn,
    MergeParentIn,
)
from app.modules.production.service import batch_service
from app.platform.identity.models import User
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


async def _make_plan_item(
    db: AsyncSession, ctx: dict[str, Any], batch_no: str | None,
    batch: Batch | None = None,
) -> PlanItem:
    """辅助：直接构造计划单 + 计划项（可选挂分配到批次），绕过 planning_service。"""
    order = PlanOrder(order_no=rand_code("PO"), title="t")
    db.add(order)
    await db.flush()
    item = PlanItem(
        plan_order_id=order.id,
        item_no=1,
        product_id=ctx["product"].id,
        product_name=ctx["product"].product_name,
        route_id=ctx["route"].id,
        batch_no=batch_no,
    )
    db.add(item)
    await db.flush()
    if batch is not None:
        db.add(PlanAllocation(plan_item_id=item.id, batch_id=batch.id))
        await db.flush()
    return item


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

    async def test_create_blocked_by_plan_item_reservation(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """新建批次号已被（草稿）计划项预分配 → 拒绝，防下达时静默改号。"""
        reserved = rand_code("RESV")
        await _make_plan_item(db_session, published_route, reserved)
        with pytest.raises(DuplicateException):
            await batch_service.create_batch(
                db_session,
                BatchCreate(
                    batch_no=reserved,
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


class TestBoundaryPermission:
    """批次边界接收权限：to 工段负责人可通过，from 工段负责人拒绝。"""

    async def _make_user(self, db: AsyncSession, name: str) -> User:
        user = User(name=name, employee_no=rand_code("E"))
        db.add(user)
        await db.flush()
        return user

    async def _grant_stage(
        self, db: AsyncSession, user_id: uuid.UUID,
        route_id: uuid.UUID, stage_name: str,
    ) -> None:
        db.add(StageAssignment(user_id=user_id, route_id=route_id, stage_name=stage_name))
        await db.flush()

    async def _ready_parent(
        self, db: AsyncSession, published_route: dict[str, Any]
    ) -> Batch:
        """父批次 in_progress 且边界边起点工序已完成，满足派生前提。"""
        parent = await _make_batch(db, published_route)
        await _set_in_progress(db, parent)
        await _insert_completed_execution(db, parent, published_route["node_a"].id)
        return parent

    async def test_derive_allowed_for_to_stage_owner(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """接收工段（to_node 所在工段）负责人可派生子批次。"""
        user = await self._make_user(db_session, "提炼负责人")
        await self._grant_stage(
            db_session, user.id, published_route["route"].id, "提炼"
        )
        parent = await self._ready_parent(db_session, published_route)
        children = await batch_service.derive_batches(
            db_session,
            parent.id,
            DeriveIn(
                edge_id=published_route["edge_ab"].id,
                children=[ChildBatchIn(batch_no=rand_code("B"))],
            ),
            user=user,
        )
        assert len(children) == 1

    async def test_derive_rejected_for_from_stage_owner(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """起点工段（from_node 所在工段）负责人不能派生后续工段批次。"""
        user = await self._make_user(db_session, "发酵负责人")
        await self._grant_stage(
            db_session, user.id, published_route["route"].id, "发酵"
        )
        parent = await self._ready_parent(db_session, published_route)
        with pytest.raises(ForbiddenException):
            await batch_service.derive_batches(
                db_session,
                parent.id,
                DeriveIn(
                    edge_id=published_route["edge_ab"].id,
                    children=[ChildBatchIn(batch_no=rand_code("B"))],
                ),
                user=user,
            )

    async def test_derive_rejected_for_unassigned_user(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """无任何工段/工序分配的用户派生被拒。"""
        user = await self._make_user(db_session, "无关用户")
        parent = await self._ready_parent(db_session, published_route)
        with pytest.raises(ForbiddenException):
            await batch_service.derive_batches(
                db_session,
                parent.id,
                DeriveIn(
                    edge_id=published_route["edge_ab"].id,
                    children=[ChildBatchIn(batch_no=rand_code("B"))],
                ),
                user=user,
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

    async def test_list_batches_filter_by_route_id(
        self, db_session: AsyncSession
    ) -> None:
        """按工艺路线过滤批次列表时只返回该路线下的批次。"""
        from app.modules.production import repository as repo
        from app.modules.production.models import Batch as BatchModel

        product_id = uuid.uuid4()
        route_a = uuid.uuid4()
        route_b = uuid.uuid4()
        base = uuid.uuid4().hex[:8]
        for i, route_id in enumerate((route_a, route_b, route_a)):
            db_session.add(
                BatchModel(
                    batch_no=f"{base}-{i}",
                    product_id=product_id,
                    route_id=route_id,
                )
            )
        await db_session.flush()
        items, total = await repo.list_batches(
            db_session, product_id, None, None, route_id=route_a,
            page=1, page_size=20, order_by="batch_no", order="asc",
        )
        assert total == 2
        assert [b.batch_no for b in items] == [f"{base}-0", f"{base}-2"]


class TestTransferOwner:
    """转移批次负责人：submit 权限硬校验、终态拒绝、字段更新与审计、清空负责人。"""

    @pytest.fixture(autouse=True)
    def _mock_permissions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """默认授予 batch:submit；无权限用例自行覆盖。"""

        async def fake_perms(_uid: str, _db: AsyncSession) -> set[str]:
            return {"production:batch:submit"}

        monkeypatch.setattr(batch_service, "get_user_permissions", fake_perms)

    async def _make_user(self, db: AsyncSession, label: str = "用户") -> User:
        user = User(name=f"{label}-{rand_code('U')}", employee_no=rand_code("EMP"))
        db.add(user)
        await db.flush()
        return user

    async def _make_owned_batch(
        self, db: AsyncSession, ctx: dict[str, Any], owner: User,
    ) -> Batch:
        """创建带负责人的 pending 批次（create_batch 不设负责人，此处直接指定）。"""
        batch = await _make_batch(db, ctx)
        batch.owner_user_id = owner.id
        batch.owner_name = owner.name
        await db.flush()
        return batch

    async def test_transfer_without_permission_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch, test_user: User,
    ) -> None:
        """无 batch:submit 权限（如仅工段负责人）→ 403。"""

        async def no_perms(_uid: str, _db: AsyncSession) -> set[str]:
            return set()

        monkeypatch.setattr(batch_service, "get_user_permissions", no_perms)
        batch = await self._make_owned_batch(db_session, published_route, test_user)
        new_owner = await self._make_user(db_session, "新负责人")
        with pytest.raises(ForbiddenException, match="batch:submit"):
            await batch_service.transfer_batch_owner(
                db_session, batch.id,
                BatchOwnerTransferIn(owner_user_id=new_owner.id),
                user=test_user,
            )

    async def test_transfer_rejects_anonymous_user(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """user=None 拒绝。"""
        batch = await self._make_owned_batch(db_session, published_route, test_user)
        with pytest.raises(ForbiddenException, match="未登录"):
            await batch_service.transfer_batch_owner(
                db_session, batch.id,
                BatchOwnerTransferIn(owner_user_id=uuid.uuid4()),
                user=None,
            )

    async def test_transfer_updates_owner_and_records_audit(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """转移成功：owner 两字段更新，审计记录新旧负责人。"""
        from sqlalchemy import select

        from app.platform.audit.models import AuditLog

        batch = await self._make_owned_batch(db_session, published_route, test_user)
        new_owner = await self._make_user(db_session, "新负责人")
        updated = await batch_service.transfer_batch_owner(
            db_session, batch.id,
            BatchOwnerTransferIn(owner_user_id=new_owner.id),
            user=test_user,
        )
        assert updated.owner_user_id == new_owner.id
        assert updated.owner_name == new_owner.name
        # 序列化回归守护：API 层用 BatchOut 序列化 service 返回值。若 service
        # 直接返回 flush 后的原对象（updated_at 被 onupdate 置为过期），此处会以
        # get_attribute_error / MissingGreenlet 失败（2026-09-07 线上报过的坑）
        from app.modules.production.schemas import BatchOut

        out = BatchOut.model_validate(updated).model_dump(mode="json")
        assert out["owner_user_id"] == str(new_owner.id)
        assert out["owner_name"] == new_owner.name
        from app.modules.production import repository as prod_repo

        refreshed = await prod_repo.get_batch(db_session, batch.id)
        assert refreshed is not None
        assert refreshed.owner_user_id == new_owner.id
        log = (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "production.batch.transfer_owner",
                    AuditLog.resource_id == batch.id,
                )
            )
        ).scalar_one()
        assert log.old_value == {
            "owner_user_id": str(test_user.id), "owner_name": test_user.name,
        }
        assert log.new_value == {
            "owner_user_id": str(new_owner.id), "owner_name": new_owner.name,
        }

    async def test_transfer_rejected_for_terminal_batch(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """completed / cancelled 批次不可转移。"""
        batch = await self._make_owned_batch(db_session, published_route, test_user)
        new_owner = await self._make_user(db_session, "新负责人")
        for terminal in ("completed", "cancelled"):
            batch.status = terminal
            await db_session.flush()
            with pytest.raises(AppException, match="不能转移负责人"):
                await batch_service.transfer_batch_owner(
                    db_session, batch.id,
                    BatchOwnerTransferIn(owner_user_id=new_owner.id),
                    user=test_user,
                )

    async def test_transfer_same_owner_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """转移给当前负责人 → 拒绝（无变化）。"""
        batch = await self._make_owned_batch(db_session, published_route, test_user)
        with pytest.raises(AppException, match="负责人未变化"):
            await batch_service.transfer_batch_owner(
                db_session, batch.id,
                BatchOwnerTransferIn(owner_user_id=test_user.id),
                user=test_user,
            )

    async def test_transfer_unknown_user_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """目标用户不存在 → 404。"""
        from app.core.exceptions import NotFoundException

        batch = await self._make_owned_batch(db_session, published_route, test_user)
        with pytest.raises(NotFoundException):
            await batch_service.transfer_batch_owner(
                db_session, batch.id,
                BatchOwnerTransferIn(owner_user_id=uuid.uuid4()),
                user=test_user,
            )

    async def test_clear_owner_sets_shared_state(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """owner_user_id=None 清空负责人（恢复无主共享）。"""
        batch = await self._make_owned_batch(db_session, published_route, test_user)
        updated = await batch_service.transfer_batch_owner(
            db_session, batch.id, BatchOwnerTransferIn(owner_user_id=None),
            user=test_user,
        )
        assert updated.owner_user_id is None
        assert updated.owner_name is None
        # 已无主再清空 → 拒绝
        with pytest.raises(AppException, match="负责人未变化"):
            await batch_service.transfer_batch_owner(
                db_session, batch.id, BatchOwnerTransferIn(owner_user_id=None),
                user=test_user,
            )


class TestRenameBatchNo:
    """修改批次号：submit 权限、不限批次状态、重复/未变化拒绝、审计与序列化守护。"""

    @pytest.fixture(autouse=True)
    def _mock_permissions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """默认授予 batch:submit；无权限用例自行覆盖。"""

        async def fake_perms(_uid: str, _db: AsyncSession) -> set[str]:
            return {"production:batch:submit"}

        monkeypatch.setattr(batch_service, "get_user_permissions", fake_perms)

    async def test_rename_without_permission_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch, test_user: User,
    ) -> None:
        """无 batch:submit 权限 → 403。"""

        async def no_perms(_uid: str, _db: AsyncSession) -> set[str]:
            return set()

        monkeypatch.setattr(batch_service, "get_user_permissions", no_perms)
        batch = await _make_batch(db_session, published_route)
        with pytest.raises(ForbiddenException, match="batch:submit"):
            await batch_service.rename_batch_no(
                db_session, batch.id,
                BatchNoUpdateIn(batch_no=rand_code("NEW")),
                user=test_user,
            )

    async def test_rename_rejects_anonymous_user(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """user=None 拒绝。"""
        batch = await _make_batch(db_session, published_route)
        with pytest.raises(ForbiddenException, match="未登录"):
            await batch_service.rename_batch_no(
                db_session, batch.id,
                BatchNoUpdateIn(batch_no=rand_code("NEW")),
                user=None,
            )

    async def test_rename_updates_no_and_records_audit(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """改名成功：字段更新、审计记原/新批号，返回值可直接被 BatchOut 序列化。"""
        from sqlalchemy import select

        from app.modules.production.schemas import BatchOut
        from app.platform.audit.models import AuditLog

        batch = await _make_batch(db_session, published_route)
        old_no = batch.batch_no
        new_no = rand_code("NEW")
        updated = await batch_service.rename_batch_no(
            db_session, batch.id, BatchNoUpdateIn(batch_no=new_no), user=test_user,
        )
        assert updated.batch_no == new_no
        # 序列化回归守护（MissingGreenlet 坑，与 transfer 同模式）
        out = BatchOut.model_validate(updated).model_dump(mode="json")
        assert out["batch_no"] == new_no
        log = (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "production.batch.rename_no",
                    AuditLog.resource_id == batch.id,
                )
            )
        ).scalar_one()
        assert log.old_value == {"batch_no": old_no}
        assert log.new_value == {"batch_no": new_no}

    async def test_rename_completed_batch_allowed(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """已完成批次也允许改批号（错误晚发现也要能修正）。"""
        batch = await _make_batch(db_session, published_route)
        batch.status = "completed"
        await db_session.flush()
        new_no = rand_code("NEW")
        updated = await batch_service.rename_batch_no(
            db_session, batch.id, BatchNoUpdateIn(batch_no=new_no), user=test_user,
        )
        assert updated.status == "completed"
        assert updated.batch_no == new_no

    async def test_rename_unchanged_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """新批号与当前相同 → 拒绝。"""
        batch = await _make_batch(db_session, published_route)
        with pytest.raises(AppException, match="批次号未变化"):
            await batch_service.rename_batch_no(
                db_session, batch.id,
                BatchNoUpdateIn(batch_no=batch.batch_no),
                user=test_user,
            )

    async def test_rename_duplicate_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """新批号与其他未删除批次重复 → 拒绝。"""
        batch = await _make_batch(db_session, published_route)
        other = await _make_batch(db_session, published_route)
        with pytest.raises(DuplicateException):
            await batch_service.rename_batch_no(
                db_session, batch.id,
                BatchNoUpdateIn(batch_no=other.batch_no),
                user=test_user,
            )

    async def test_rename_blocked_by_plan_item_reservation(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """新批号已被草稿计划项预分配 → 拒绝，防下达时静默改号。"""
        batch = await _make_batch(db_session, published_route)
        reserved = rand_code("RESV")
        await _make_plan_item(db_session, published_route, reserved)
        with pytest.raises(DuplicateException):
            await batch_service.rename_batch_no(
                db_session, batch.id,
                BatchNoUpdateIn(batch_no=reserved),
                user=test_user,
            )

    async def test_rename_syncs_allocated_plan_item_batch_no(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """改名后回写计划项批号（计划项种子仍等于旧批号时）。"""
        batch = await _make_batch(db_session, published_route)
        old_no = batch.batch_no
        item = await _make_plan_item(db_session, published_route, old_no, batch)
        new_no = rand_code("NEW")
        await batch_service.rename_batch_no(
            db_session, batch.id, BatchNoUpdateIn(batch_no=new_no), user=test_user,
        )
        refreshed = await repo.get_plan_item(db_session, item.id)
        assert refreshed is not None and refreshed.batch_no == new_no

    async def test_rename_preserves_edited_plan_item_seed(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """计划项种子已被计划员改过（≠旧批号）→ 改名不回写，保留新种子。"""
        batch = await _make_batch(db_session, published_route)
        keep = rand_code("KEEP")
        item = await _make_plan_item(db_session, published_route, keep, batch)
        await batch_service.rename_batch_no(
            db_session, batch.id,
            BatchNoUpdateIn(batch_no=rand_code("NEW")), user=test_user,
        )
        refreshed = await repo.get_plan_item(db_session, item.id)
        assert refreshed is not None and refreshed.batch_no == keep

    async def test_rename_to_own_edited_seed_allowed(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """改名为本批次计划项已改写的种子号 → 放行（自身计划项不参与重复校验）。"""
        batch = await _make_batch(db_session, published_route)
        target = rand_code("TGT")
        item = await _make_plan_item(db_session, published_route, target, batch)
        updated = await batch_service.rename_batch_no(
            db_session, batch.id, BatchNoUpdateIn(batch_no=target), user=test_user,
        )
        assert updated.batch_no == target
        refreshed = await repo.get_plan_item(db_session, item.id)
        assert refreshed is not None and refreshed.batch_no == target

    async def test_rename_whitespace_only_rejected(self) -> None:
        """纯空白批号在 schema 层即被拒绝。"""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BatchNoUpdateIn(batch_no="   ")
