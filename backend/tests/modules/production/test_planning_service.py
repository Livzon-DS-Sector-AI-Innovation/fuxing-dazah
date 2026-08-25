"""计划中枢业务逻辑测试。

覆盖业务场景：
- 需求（Demand）：自动编号生成、编号唯一、更新/确认/取消的状态限制、软删除、详情含分配
- 计划单（PlanOrder）：自动编号生成、草稿路线拒绝、仅 draft 可编辑、
  确认需至少一个计划项、下达需全部排程且生成批次、关闭状态限制、软删除
- 计划项（PlanItem）：继承计划单产品/路线、批号唯一、仅 draft/scheduled 可编辑、
  排程时间校验与设备冲突告警、单独分配生成批次
- 需求分配（DemandAllocation）：仅 confirmed/partial 可分配、超量拒绝、状态重算
- 计划单变更（change_plan_order）：仅 released 可变更、删除项联动批次报废、
  生产中批次禁止删除、变更日志写入
- 追溯树与排程视图
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.production import repository as repo
from app.modules.production.models import Batch
from app.modules.production.schemas import (
    DemandAllocationCreate,
    DemandCreate,
    DemandUpdate,
    PlanItemCreate,
    PlanItemScheduleIn,
    PlanOrderCreate,
    PlanOrderUpdate,
)
from app.modules.production.schemas.planning import (
    PlanItemChangeItem,
    PlanOrderChangeRequest,
)
from app.modules.production.service import planning_service
from app.platform.identity.models import User
from tests.modules.production.conftest import rand_code


async def _make_demand(
    db: AsyncSession, ctx: dict[str, Any], user: User | None = None,
    quantity: float = 100,
) -> Any:
    """创建一条已确认或 pending 的需求。"""
    return await planning_service.create_demand(
        db,
        DemandCreate(
            product_id=ctx["product"].id,
            product_name=ctx["product"].product_name,
            demanded_quantity=quantity,
            unit="kg",
            demand_date=datetime.now(UTC).date(),
            priority="high",
        ),
        user=user,
    )


async def _make_order(
    db: AsyncSession, ctx: dict[str, Any], user: User | None = None,
) -> Any:
    """创建计划单（draft）。"""
    return await planning_service.create_plan_order(
        db,
        PlanOrderCreate(
            order_no=rand_code("PO"),
            title="测试计划单",
            product_id=ctx["product"].id,
            route_id=ctx["route"].id,
            priority="medium",
        ),
        user=user,
    )


async def _make_item(
    db: AsyncSession, order: Any, ctx: dict[str, Any], user: User | None = None,
) -> Any:
    """向计划单添加计划项。"""
    return await planning_service.create_plan_item(
        db,
        order.id,
        PlanItemCreate(
            product_id=ctx["product"].id,
            product_name=ctx["product"].product_name,
            route_id=ctx["route"].id,
            planned_quantity=50,
            unit="kg",
            batch_no=rand_code("ITM"),
            priority="medium",
        ),
        user=user,
    )


async def _make_items(
    db: AsyncSession, order: Any, ctx: dict[str, Any], batch_nos: list[str],
    user: User | None = None,
) -> list[Any]:
    """连续添加批号依次为 ``batch_nos`` 的计划项（删除/补位类测试共用）。"""
    items = []
    for no in batch_nos:
        items.append(await planning_service.create_plan_item(
            db,
            order.id,
            PlanItemCreate(
                product_id=ctx["product"].id,
                product_name="中间体A",
                route_id=ctx["route"].id,
                batch_no=no,
            ),
            user=user,
        ))
    return items


async def _schedule_item(
    db: AsyncSession, item: Any, user: User | None = None,
) -> None:
    """排程计划项（设置起止时间，置为 scheduled）。"""
    now = datetime.now(UTC)
    await planning_service.schedule_plan_item(
        db,
        item.id,
        PlanItemScheduleIn(planned_start=now, planned_end=now + timedelta(hours=8)),
        user=user,
    )


# ═══════════════════════════════════════════
# Demand
# ═══════════════════════════════════════════

class TestDemand:
    async def test_create_auto_generates_demand_no(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """demand_no 留空时自动生成 DM-YYYYMMDD 前缀的编号。"""
        demand = await _make_demand(db_session, published_route)
        assert demand.demand_no.startswith("DM-")
        assert demand.status == "pending"

    async def test_create_duplicate_demand_no_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """重复需求编号创建抛出 DuplicateException。"""
        no = rand_code("DM")
        await planning_service.create_demand(
            db_session,
            DemandCreate(
                demand_no=no,
                product_id=published_route["product"].id,
                product_name="X",
                demanded_quantity=10,
                unit="kg",
                demand_date=datetime.now(UTC).date(),
            ),
            user=None,
        )
        with pytest.raises(DuplicateException):
            await planning_service.create_demand(
                db_session,
                DemandCreate(
                    demand_no=no,
                    product_id=published_route["product"].id,
                    product_name="X",
                    demanded_quantity=10,
                    unit="kg",
                    demand_date=datetime.now(UTC).date(),
                ),
                user=None,
            )

    async def test_update_only_when_pending_or_confirmed(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """pending 状态可编辑；取消后不可再编辑。"""
        demand = await _make_demand(db_session, published_route, test_user)
        updated = await planning_service.update_demand(
            db_session, demand.id,
            DemandUpdate(product_name="改名", remark="备注"),
            test_user,
        )
        assert updated.product_name == "改名"

        await planning_service.cancel_demand(db_session, demand.id, test_user)
        with pytest.raises(AppException, match="可编辑"):
            await planning_service.update_demand(
                db_session, demand.id, DemandUpdate(remark="x"), test_user,
            )

    async def test_confirm_only_from_pending(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """pending → confirmed；重复确认拒绝。"""
        demand = await _make_demand(db_session, published_route, test_user)
        confirmed = await planning_service.confirm_demand(
            db_session, demand.id, test_user,
        )
        assert confirmed.status == "confirmed"
        with pytest.raises(AppException, match="仅 pending"):
            await planning_service.confirm_demand(db_session, demand.id, test_user)

    async def test_cancel_rejects_cancelled_twice(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """取消后再次取消拒绝。"""
        demand = await _make_demand(db_session, published_route, test_user)
        await planning_service.cancel_demand(db_session, demand.id, test_user)
        with pytest.raises(AppException, match="不能取消"):
            await planning_service.cancel_demand(db_session, demand.id, test_user)

    async def test_delete_soft_and_detail_not_found(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """软删除需求后详情查询抛 NotFoundException。"""
        demand = await _make_demand(db_session, published_route, test_user)
        await planning_service.delete_demand(db_session, demand.id, test_user)
        with pytest.raises(NotFoundException):
            await planning_service.get_demand_detail(db_session, demand.id)

    async def test_detail_fills_allocation_fields(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """需求详情返回关联的计划项分配，含计划单号/项序号。"""
        demand = await _make_demand(db_session, published_route, test_user)
        await planning_service.confirm_demand(db_session, demand.id, test_user)
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        await planning_service.confirm_plan_order(db_session, order.id, test_user)
        await planning_service.release_plan_order(db_session, order.id, test_user)

        await planning_service.create_demand_allocation(
            db_session, demand.id,
            DemandAllocationCreate(plan_item_id=item.id, allocated_quantity=40),
            test_user,
        )
        detail = await planning_service.get_demand_detail(db_session, demand.id)
        assert len(detail.allocations) == 1
        alloc = detail.allocations[0]
        assert alloc.plan_order_no == order.order_no
        assert alloc.item_no == item.item_no
        assert detail.remaining_quantity == 60


# ═══════════════════════════════════════════
# PlanOrder
# ═══════════════════════════════════════════

class TestPlanOrder:
    async def test_create_rejects_draft_route(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """草稿路线上不能创建计划单。"""
        draft_route = await repo.get_route(db_session, published_route["route"].id)
        # 复制一条草稿路线：新建路线未发布即为 draft
        from app.modules.production.schemas import ProductCreate, RouteCreate
        from app.modules.production.service import route_service

        product = await route_service.create_product(
            db_session, ProductCreate(product_name=rand_code("产品")), user=None,
        )
        draft = await route_service.create_route(
            db_session, RouteCreate(product_id=product.id, route_name="草稿V1"),
            user=None,
        )
        assert draft_route is not None and draft.status == "draft"
        with pytest.raises(AppException, match="草稿"):
            await planning_service.create_plan_order(
                db_session,
                PlanOrderCreate(
                    order_no=rand_code("PO"),
                    title="x",
                    product_id=product.id,
                    route_id=draft.id,
                ),
                user=None,
            )

    async def test_create_duplicate_order_no_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """重复计划单号创建抛出 DuplicateException。"""
        no = rand_code("PO")
        await planning_service.create_plan_order(
            db_session,
            PlanOrderCreate(
                order_no=no, title="x",
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
            ),
            user=test_user,
        )
        with pytest.raises(DuplicateException):
            await planning_service.create_plan_order(
                db_session,
                PlanOrderCreate(
                    order_no=no, title="y",
                    product_id=published_route["product"].id,
                    route_id=published_route["route"].id,
                ),
                user=test_user,
            )

    async def test_update_only_in_draft(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """draft 可编辑标题；确认后不可编辑。"""
        order = await _make_order(db_session, published_route, test_user)
        updated = await planning_service.update_plan_order(
            db_session, order.id, PlanOrderUpdate(title="新标题"), test_user,
        )
        assert updated.title == "新标题"

        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        await planning_service.confirm_plan_order(db_session, order.id, test_user)
        with pytest.raises(AppException, match="仅 draft"):
            await planning_service.update_plan_order(
                db_session, order.id, PlanOrderUpdate(title="x"), test_user,
            )

    async def test_confirm_requires_items(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """无计划项的计划单不能确认。"""
        order = await _make_order(db_session, published_route, test_user)
        with pytest.raises(AppException, match="无计划项"):
            await planning_service.confirm_plan_order(db_session, order.id, test_user)

    async def test_confirm_increments_plan_version(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """确认后 plan_version 从 1 变为 2。"""
        order = await _make_order(db_session, published_route, test_user)
        assert order.plan_version == 1
        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        confirmed = await planning_service.confirm_plan_order(
            db_session, order.id, test_user,
        )
        assert confirmed.status == "confirmed"
        assert confirmed.plan_version == 2

    async def test_release_requires_all_items_scheduled(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """存在未排程计划项时下达被拒。"""
        order = await _make_order(db_session, published_route, test_user)
        await _make_item(db_session, order, published_route, test_user)
        await planning_service.confirm_plan_order(db_session, order.id, test_user)
        with pytest.raises(AppException, match="未排程"):
            await planning_service.release_plan_order(db_session, order.id, test_user)

    async def test_release_generates_batches_and_allocations(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """下达后每个计划项生成 scheduled 批次和分配，计划项置 allocated。"""
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        await planning_service.confirm_plan_order(db_session, order.id, test_user)
        released = await planning_service.release_plan_order(
            db_session, order.id, test_user,
        )
        assert released.status == "released"

        allocs = await repo.get_plan_allocations_by_item(db_session, item.id)
        assert len(allocs) == 1
        batch = await repo.get_batch(db_session, allocs[0].batch_id)
        assert batch is not None
        assert batch.status == "scheduled"
        assert batch.creation_type == "plan"
        refreshed_item = await repo.get_plan_item(db_session, item.id)
        assert refreshed_item is not None and refreshed_item.status == "allocated"

    async def test_close_status_restrictions(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """draft 计划单不能关闭；released 可以关闭。"""
        order = await _make_order(db_session, published_route, test_user)
        with pytest.raises(AppException, match="可关闭"):
            await planning_service.close_plan_order(db_session, order.id, test_user)

        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        await planning_service.confirm_plan_order(db_session, order.id, test_user)
        await planning_service.release_plan_order(db_session, order.id, test_user)
        closed = await planning_service.close_plan_order(
            db_session, order.id, test_user,
        )
        assert closed.status == "closed"

    async def test_delete_soft(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """软删除计划单后详情查询抛 NotFoundException。"""
        order = await _make_order(db_session, published_route, test_user)
        await planning_service.delete_plan_order(db_session, order.id, test_user)
        with pytest.raises(NotFoundException):
            await planning_service.get_plan_order_detail(db_session, order.id)


# ═══════════════════════════════════════════
# PlanItem
# ═══════════════════════════════════════════

class TestPlanItem:
    async def test_create_inherits_order_defaults(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """未指定路线时继承计划单的路线，item_no 自动递增。"""
        order = await _make_order(db_session, published_route, test_user)
        item = await planning_service.create_plan_item(
            db_session,
            order.id,
            PlanItemCreate(
                product_id=order.product_id,
                product_name="中间体A",
                batch_no=rand_code("ITM"),
                priority="medium",
            ),
            user=test_user,
        )
        assert item.product_id == order.product_id
        assert item.route_id == order.route_id
        assert item.item_no == 1

    async def test_create_rejects_duplicate_batch_no(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """计划项批号与已有批次重复时拒绝。"""
        order = await _make_order(db_session, published_route, test_user)
        batch_no = rand_code("B")
        db_session.add(
            Batch(
                batch_no=batch_no,
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
                status="pending",
            )
        )
        await db_session.flush()
        with pytest.raises(DuplicateException):
            await planning_service.create_plan_item(
                db_session,
                order.id,
                PlanItemCreate(
                    product_id=published_route["product"].id,
                    product_name="X",
                    route_id=published_route["route"].id,
                    batch_no=batch_no,
                ),
                user=test_user,
            )

    async def test_update_only_when_draft_or_scheduled(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """排程后可编辑；分配后不可编辑。"""
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        from app.modules.production.schemas import PlanItemUpdate

        updated = await planning_service.update_plan_item(
            db_session, item.id, PlanItemUpdate(planned_quantity=80), test_user,
        )
        assert updated.planned_quantity == 80

        await planning_service.allocate_plan_item(db_session, item.id, test_user)
        with pytest.raises(AppException, match="可编辑"):
            await planning_service.update_plan_item(
                db_session, item.id, PlanItemUpdate(remark="x"), test_user,
            )

    async def test_schedule_requires_valid_time_range(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """开始时间晚于结束时间时排程被拒。"""
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        now = datetime.now(UTC)
        with pytest.raises(AppException, match="早于"):
            await planning_service.schedule_plan_item(
                db_session, item.id,
                PlanItemScheduleIn(planned_start=now + timedelta(hours=8), planned_end=now),
                user=test_user,
            )

    async def test_schedule_warns_equipment_conflict(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """同一设备同一时间段已有排程时返回告警但不阻断。"""
        order = await _make_order(db_session, published_route, test_user)
        item1 = await _make_item(db_session, order, published_route, test_user)
        item2 = await _make_item(db_session, order, published_route, test_user)
        now = datetime.now(UTC)
        await planning_service.schedule_plan_item(
            db_session, item1.id,
            PlanItemScheduleIn(
                planned_start=now, planned_end=now + timedelta(hours=8),
                equipment_id="EQ-1",
            ),
            user=test_user,
        )
        item2, warnings = await planning_service.schedule_plan_item(
            db_session, item2.id,
            PlanItemScheduleIn(
                planned_start=now + timedelta(hours=1),
                planned_end=now + timedelta(hours=9),
                equipment_id="EQ-1",
            ),
            user=test_user,
        )
        assert item2.status == "scheduled"
        assert len(warnings) == 1
        assert warnings[0]["item_no"] == item1.item_no

    async def test_allocate_generates_batch(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """单独分配计划项生成 scheduled 批次，计划项置 allocated。"""
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        allocated = await planning_service.allocate_plan_item(
            db_session, item.id, test_user,
        )
        assert allocated.status == "allocated"
        allocs = await repo.get_plan_allocations_by_item(db_session, item.id)
        assert len(allocs) == 1
        batch = await repo.get_batch(db_session, allocs[0].batch_id)
        assert batch is not None and batch.status == "scheduled"

    async def test_allocate_requires_scheduled(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """未排程的计划项不能单独分配。"""
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        with pytest.raises(AppException, match="仅 scheduled"):
            await planning_service.allocate_plan_item(db_session, item.id, test_user)

    async def test_delete_soft(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """软删除计划项后不可再查询到。"""
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        await planning_service.delete_plan_item(db_session, item.id, test_user)
        assert await repo.get_plan_item(db_session, item.id) is None

    async def test_delete_with_shift_backfills_following_batch_nos(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """删除并补位：后续计划项批号数字前移，删除项之前的批号不动。"""
        order = await _make_order(db_session, published_route, test_user)
        items = await _make_items(
            db_session, order, published_route, ["TS-1", "TS-2", "TS-3", "TS-4"], test_user,
        )
        result = await planning_service.delete_plan_item(
            db_session, items[1].id, test_user, shift=True,
        )
        remaining = await repo.list_plan_items(db_session, order.id)
        assert [i.batch_no for i in remaining] == ["TS-1", "TS-2", "TS-3"]
        assert result["shifted"] == [
            {"item_id": str(items[2].id), "batch_no": "TS-2"},
            {"item_id": str(items[3].id), "batch_no": "TS-3"},
        ]
        assert result["skipped"] == []

    async def test_delete_with_shift_skips_occupied_target(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """补位目标批号被真实批次占用时跳过该项，删除仍生效。"""
        order = await _make_order(db_session, published_route, test_user)
        items = await _make_items(
            db_session, order, published_route, ["CF-1", "CF-2", "CF-3"], test_user,
        )
        db_session.add(
            Batch(
                batch_no="CF-2",
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
                status="pending",
            )
        )
        await db_session.flush()
        result = await planning_service.delete_plan_item(
            db_session, items[1].id, test_user, shift=True,
        )
        remaining = await repo.list_plan_items(db_session, order.id)
        assert [i.batch_no for i in remaining] == ["CF-1", "CF-3"]
        assert result["shifted"] == []
        assert result["skipped"] == [{"item_id": str(items[2].id), "batch_no": "CF-3"}]

    async def test_delete_with_shift_leaves_non_numeric_batch_nos(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """批号无数字段时补位不改变任何批号。"""
        order = await _make_order(db_session, published_route, test_user)
        items = await _make_items(
            db_session, order, published_route, ["NF-A", "NF-B", "NF-C"], test_user,
        )
        result = await planning_service.delete_plan_item(
            db_session, items[0].id, test_user, shift=True,
        )
        remaining = await repo.list_plan_items(db_session, order.id)
        assert [i.batch_no for i in remaining] == ["NF-B", "NF-C"]
        assert result["shifted"] == []
        assert result["skipped"] == []

    async def test_delete_with_shift_skips_batch_no_held_by_other_order(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """补位目标批号被其他计划单的计划项占用时跳过，不产生跨单重复批号。"""
        order = await _make_order(db_session, published_route, test_user)
        items = await _make_items(
            db_session, order, published_route, ["XO-1", "XO-3"], test_user,
        )
        other_order = await _make_order(db_session, published_route, test_user)
        await _make_items(
            db_session, other_order, published_route, ["XO-2"], test_user,
        )
        result = await planning_service.delete_plan_item(
            db_session, items[0].id, test_user, shift=True,
        )
        remaining = await repo.list_plan_items(db_session, order.id)
        assert [i.batch_no for i in remaining] == ["XO-3"]
        assert result["shifted"] == []
        assert result["skipped"] == [{"item_id": str(items[1].id), "batch_no": "XO-3"}]

    async def test_delete_with_shift_reorders_out_of_order_items(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """后续项批号顺序与列表顺序相反时，多轮补位仍全部前移（不误报占用）。"""
        order = await _make_order(db_session, published_route, test_user)
        items = await _make_items(
            db_session, order, published_route, ["TS-3", "TS-5", "TS-4"], test_user,
        )
        result = await planning_service.delete_plan_item(
            db_session, items[0].id, test_user, shift=True,
        )
        remaining = await repo.list_plan_items(db_session, order.id)
        assert [i.batch_no for i in remaining] == ["TS-4", "TS-3"]
        assert {r["item_id"]: r["batch_no"] for r in result["shifted"]} == {
            str(items[1].id): "TS-4",
            str(items[2].id): "TS-3",
        }
        assert result["skipped"] == []


# ═══════════════════════════════════════════
# DemandAllocation
# ═══════════════════════════════════════════

class TestDemandAllocation:
    async def test_allocate_requires_confirmed_demand(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """pending 状态的需求不能分配计划项。"""
        demand = await _make_demand(db_session, published_route, test_user)
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        with pytest.raises(AppException, match="可分配"):
            await planning_service.create_demand_allocation(
                db_session, demand.id,
                DemandAllocationCreate(plan_item_id=item.id, allocated_quantity=10),
                test_user,
            )

    async def test_allocate_exceeding_quantity_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """累计分配量超出需求总量时拒绝。"""
        demand = await _make_demand(
            db_session, published_route, test_user, quantity=100,
        )
        await planning_service.confirm_demand(db_session, demand.id, test_user)
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        await planning_service.create_demand_allocation(
            db_session, demand.id,
            DemandAllocationCreate(plan_item_id=item.id, allocated_quantity=90),
            test_user,
        )
        with pytest.raises(AppException, match="超出需求总量"):
            await planning_service.create_demand_allocation(
                db_session, demand.id,
                DemandAllocationCreate(plan_item_id=item.id, allocated_quantity=20),
                test_user,
            )

    async def test_allocate_recalculates_status_to_partial(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """分配后需求状态从 confirmed 变为 partial，分配量累计。"""
        demand = await _make_demand(
            db_session, published_route, test_user, quantity=100,
        )
        await planning_service.confirm_demand(db_session, demand.id, test_user)
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        await planning_service.create_demand_allocation(
            db_session, demand.id,
            DemandAllocationCreate(plan_item_id=item.id, allocated_quantity=60),
            test_user,
        )
        refreshed = await repo.get_demand(db_session, demand.id)
        assert refreshed is not None
        assert refreshed.allocated_quantity == 60
        assert refreshed.status == "partial"

    async def test_remove_allocation_recalculates_back_to_confirmed(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """解除全部关联后需求状态回到 confirmed。"""
        demand = await _make_demand(
            db_session, published_route, test_user, quantity=100,
        )
        await planning_service.confirm_demand(db_session, demand.id, test_user)
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        alloc = await planning_service.create_demand_allocation(
            db_session, demand.id,
            DemandAllocationCreate(plan_item_id=item.id, allocated_quantity=50),
            test_user,
        )
        await planning_service.delete_demand_allocation(
            db_session, alloc.id, test_user,
        )
        refreshed = await repo.get_demand(db_session, demand.id)
        assert refreshed is not None
        assert refreshed.allocated_quantity == 0
        assert refreshed.status == "confirmed"


# ═══════════════════════════════════════════
# 计划单变更
# ═══════════════════════════════════════════

class TestChangePlanOrder:
    async def _released_order(
        self, db_session: AsyncSession, ctx: dict[str, Any], user: User,
    ) -> tuple[Any, Any]:
        """下达完成的计划单，返回 (order, item)。"""
        order = await _make_order(db_session, ctx, user)
        item = await _make_item(db_session, order, ctx, user)
        await _schedule_item(db_session, item, user)
        await planning_service.confirm_plan_order(db_session, order.id, user)
        await planning_service.release_plan_order(db_session, order.id, user)
        return order, item

    async def test_change_requires_released(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """仅 released 状态的计划单可变更。"""
        order = await _make_order(db_session, published_route, test_user)
        with pytest.raises(AppException, match="仅 released"):
            await planning_service.change_plan_order(
                db_session, order.id,
                PlanOrderChangeRequest(change_reason="测试"), test_user,
            )

    async def test_change_deletes_item_and_cancels_batch(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """变更删除计划项：对应批次报废、计划项软删、版本号递增。"""
        order, item = await self._released_order(
            db_session, published_route, test_user,
        )
        version_before = order.plan_version
        allocs = await repo.get_plan_allocations_by_item(db_session, item.id)
        batch_id = allocs[0].batch_id

        changed = await planning_service.change_plan_order(
            db_session, order.id,
            PlanOrderChangeRequest(
                change_reason="取消一个批次",
                items_delete=[item.id],
            ),
            test_user,
        )
        assert changed.plan_version == version_before + 1
        batch = await repo.get_batch(db_session, batch_id)
        assert batch is not None and batch.status == "cancelled"
        assert await repo.get_plan_item(db_session, item.id) is None
        detail = await planning_service.get_plan_order_detail(db_session, order.id)
        assert len(detail.change_logs) == 1
        assert detail.change_logs[0].change_reason == "取消一个批次"

    async def test_change_adds_item_with_new_batch(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """变更新增计划项：生成新批次且新计划项可见。"""
        order, _ = await self._released_order(
            db_session, published_route, test_user,
        )
        items_before = await repo.list_plan_items(db_session, order.id)
        await planning_service.change_plan_order(
            db_session, order.id,
            PlanOrderChangeRequest(
                change_reason="追加一个批次",
                items_upsert=[PlanItemChangeItem(
                    product_id=published_route["product"].id,
                    product_name="追加品",
                    route_id=published_route["route"].id,
                    batch_no=rand_code("ITM"),
                    planned_quantity=30,
                )],
            ),
            test_user,
        )
        items_after = await repo.list_plan_items(db_session, order.id)
        assert len(items_after) == len(items_before) + 1
        new_item = max(items_after, key=lambda i: i.item_no)
        allocs = await repo.get_plan_allocations_by_item(db_session, new_item.id)
        assert len(allocs) == 1
        batch = await repo.get_batch(db_session, allocs[0].batch_id)
        assert batch is not None and batch.status == "scheduled"

    async def test_change_delete_blocks_batch_in_production(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """对应批次已进入生产（非 scheduled/cancelled）时删除计划项被拒。"""
        order, item = await self._released_order(
            db_session, published_route, test_user,
        )
        allocs = await repo.get_plan_allocations_by_item(db_session, item.id)
        batch = await repo.get_batch(db_session, allocs[0].batch_id)
        assert batch is not None
        batch.status = "in_progress"
        await db_session.flush()
        with pytest.raises(AppException, match="已进入生产"):
            await planning_service.change_plan_order(
                db_session, order.id,
                PlanOrderChangeRequest(
                    change_reason="尝试删除",
                    items_delete=[item.id],
                ),
                test_user,
            )

    async def test_change_quantity_updates_batch(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """变更修改计划数量：批次和分配的 quantity 同步更新。"""
        order, item = await self._released_order(
            db_session, published_route, test_user,
        )
        await planning_service.change_plan_order(
            db_session, order.id,
            PlanOrderChangeRequest(
                change_reason="调整数量",
                items_upsert=[PlanItemChangeItem(id=item.id, planned_quantity=99)],
            ),
            test_user,
        )
        allocs = await repo.get_plan_allocations_by_item(db_session, item.id)
        batch = await repo.get_batch(db_session, allocs[0].batch_id)
        assert batch is not None and batch.quantity == 99
        assert allocs[0].allocated_quantity == 99


# ═══════════════════════════════════════════
# 追溯与排程视图
# ═══════════════════════════════════════════

class TestTraceAndScheduleView:
    async def test_demand_trace_three_level_tree(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """追溯树：需求 → 计划项 → 批次 三层结构。"""
        demand = await _make_demand(
            db_session, published_route, test_user, quantity=100,
        )
        await planning_service.confirm_demand(db_session, demand.id, test_user)
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        await planning_service.confirm_plan_order(db_session, order.id, test_user)
        await planning_service.release_plan_order(db_session, order.id, test_user)
        await planning_service.create_demand_allocation(
            db_session, demand.id,
            DemandAllocationCreate(plan_item_id=item.id, allocated_quantity=50),
            test_user,
        )

        tree = await planning_service.get_demand_trace(db_session, demand.id)
        assert tree.type == "demand"
        assert tree.id == demand.id
        assert len(tree.children) == 1
        item_node = tree.children[0]
        assert item_node.type == "plan_item"
        assert item_node.id == item.id
        assert len(item_node.children) == 1
        batch_node = item_node.children[0]
        assert batch_node.type == "batch"
        assert batch_node.status == "scheduled"

    async def test_demand_trace_nonexistent_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """追溯不存在的需求抛 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await planning_service.get_demand_trace(db_session, uuid.uuid4())

    async def test_schedule_view_lists_scheduled_items(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """排程视图返回已排程计划项，含订单与设备信息。"""
        order = await _make_order(db_session, published_route, test_user)
        item = await _make_item(db_session, order, published_route, test_user)
        await _schedule_item(db_session, item, test_user)
        view = await planning_service.get_schedule_view(
            db_session, None, None, None,
        )
        assert len(view) >= 1
        matched = [v for v in view if v.item_id == item.id]
        assert len(matched) == 1
        assert matched[0].order_no == order.order_no
        assert matched[0].order_status == "draft"
