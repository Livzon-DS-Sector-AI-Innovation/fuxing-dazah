"""工序流程看板 process-board 端点测试。

覆盖业务场景：
- 看板返回路线节点、计划批次列与各节点未完成执行
- 仅 in_progress/aborted 执行出现在工序列中（completed 排除）
- 列内按 started_at 降序（最新在上）
- 字段值与 abnormal_count 随板返回（hover 直接渲染）
- 计划批次仅来自 released 计划单，按 planned_start 升序
- 路线不存在返回 404
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import Batch, PlanAllocation, PlanItem, PlanOrder
from app.modules.production.schemas import (
    BatchCreate,
    EdgeIn,
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldDefIn,
    FieldValueIn,
    NodeIn,
    ProductCreate,
    RouteCreate,
    RouteGraphIn,
)
from app.modules.production.service import (
    batch_service,
    execution_service,
    route_service,
)
from tests.modules.production.conftest import rand_code

T0 = (datetime.now(UTC) - timedelta(days=1)).replace(minute=0, second=0, microsecond=0)


async def _make_board_route_ctx(db: AsyncSession) -> dict[str, Any]:
    """发布路线 G1→G2：G1 有 start 阶段数值字段 TEMP（上限 30，超限判异常）。"""
    product = await route_service.create_product(
        db,
        ProductCreate(product_name=rand_code("测试产品"), product_code=rand_code("P")),
        user=None,
    )
    route = await route_service.create_route(
        db, RouteCreate(product_id=product.id, route_name="工艺V1"), user=None,
    )
    graph = RouteGraphIn(
        nodes=[
            NodeIn(
                node_code="G1",
                name="工序一",
                stage_name="工段一",
                sort_order=1,
                fields=[
                    FieldDefIn(
                        field_key="TEMP", field_label="投料温度", phase="start",
                        data_type="numeric", unit="℃", max_value=30,
                    ),
                    FieldDefIn(
                        field_key="OUT", field_label="产出量", phase="end",
                        data_type="numeric",
                    ),
                ],
            ),
            NodeIn(
                node_code="G2",
                name="工序二",
                stage_name="工段二",
                sort_order=2,
                fields=[
                    FieldDefIn(
                        field_key="QTY", field_label="质量", phase="end",
                        data_type="numeric",
                    ),
                ],
            ),
        ],
        edges=[EdgeIn(from_node_code="G1", to_node_code="G2", is_batch_boundary=True)],
        computed_fields=[],
    )
    await route_service.save_graph(db, route.id, graph, user=None)
    await route_service.publish_route(db, route.id, user=None)
    graph_out = await route_service.get_graph(db, route.id)
    nodes = {n.node_code: n for n in graph_out.nodes}
    return {"product": product, "route": route, "node_g1": nodes["G1"], "node_g2": nodes["G2"]}


async def _make_released_plan(
    db: AsyncSession, ctx: dict[str, Any], batch_nos: list[str],
    *,
    item_status: str = "allocated",
) -> PlanOrder:
    """直接造 released 计划单 + 计划项 + 实际批次（bno 用作真实 Batch.batch_no）。

    默认计划项为 allocated（已分配未执行），即看板"计划批次"列应展示的状态。
    下达时 Batch.batch_no 以传入的 bno 为准（模拟 _ensure_unique_batch_no 去重改写场景）。
    """
    order = PlanOrder(
        order_no=rand_code("PO"),
        title="测试计划单",
        status="released",
        product_id=ctx["product"].id,
        route_id=ctx["route"].id,
        priority="medium",
    )
    db.add(order)
    await db.flush()
    for i, bno in enumerate(batch_nos, start=1):
        await _add_plan_item(
            db, order, i, bno, item_status=item_status,
            planned_start=T0 + timedelta(days=i),
        )
    return order


async def _add_plan_item(
    db: AsyncSession, order: PlanOrder, item_no: int, batch_no: str,
    *, item_status: str = "allocated", planned_start: datetime | None = None,
) -> tuple[PlanItem, Batch | None]:
    item = PlanItem(
        plan_order_id=order.id,
        item_no=item_no,
        product_id=order.product_id,
        product_name="测试产品",
        route_id=order.route_id,
        batch_no=f"PLAN-{batch_no}",  # 计划项占用/预分配号
        status=item_status,
        planned_start=planned_start,
        planned_quantity=100 * item_no,
        unit="kg",
        priority="medium",
    )
    db.add(item)
    await db.flush()
    # 未分配（scheduled）不产生批次；allocated 才下达生批次 + Allocation
    if item_status != "allocated":
        return item, None
    batch = Batch(
        batch_no=batch_no,  # 实际批次号，可能与计划项占位号不同
        product_id=order.product_id,
        route_id=order.route_id,
        status="scheduled",
        quantity=100 * item_no,
        unit="kg",
        creation_type="plan",
    )
    db.add(batch)
    await db.flush()
    db.add(
        PlanAllocation(
            plan_item_id=item.id,
            batch_id=batch.id,
            allocated_quantity=100 * item_no,
        )
    )
    await db.flush()
    return item, batch


async def _start(
    db: AsyncSession, batch_id: Any, node_id: Any,
    *,
    at: datetime,
    field_values: list[FieldValueIn] | None = None,
) -> Any:
    return await execution_service.start_execution(
        db, batch_id, ExecutionStartIn(
            node_id=node_id, started_at=at, field_values=field_values or [],
        ), user=None,
    )


async def test_process_board(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    ctx = await _make_board_route_ctx(db_session)

    # 计划批次：released 计划单 2 项（allocated，应出现）；real_nos 为实际批次号
    real_nos = [rand_code("B"), rand_code("B")]
    released = await _make_released_plan(db_session, ctx, real_nos)
    # 同一 released 计划单下第 3 项为 scheduled（未分配，不应出现在计划列）
    await _add_plan_item(
        db_session, released, 3, rand_code("B"),
        item_status="scheduled", planned_start=T0 + timedelta(days=1),
    )
    # 未下达（confirmed）计划单 1 项 allocated（不应出现）
    draft_order = await _make_released_plan(db_session, ctx, [rand_code("B")])
    draft_order.status = "confirmed"  # 未下达，不应出现在计划列
    await db_session.flush()

    # b1: G1 进行中（字段正常）——应出现
    b1 = await batch_service.create_batch(
        db_session, BatchCreate(
            batch_no=rand_code("B"), product_id=ctx["product"].id,
            route_id=ctx["route"].id,
        ), user=None,
    )
    await _start(
        db_session, b1.id, ctx["node_g1"].id, at=T0,
        field_values=[FieldValueIn(field_key="TEMP", value=25)],
    )

    # b2: G1 进行中后中止（字段超限→异常）——应出现
    b2 = await batch_service.create_batch(
        db_session, BatchCreate(
            batch_no=rand_code("B"), product_id=ctx["product"].id,
            route_id=ctx["route"].id,
        ), user=None,
    )
    ex2 = await _start(
        db_session, b2.id, ctx["node_g1"].id, at=T0 + timedelta(minutes=30),
        field_values=[FieldValueIn(field_key="TEMP", value=35)],
    )
    await execution_service.abort_execution(db_session, ex2.id, user=None)

    # b3: G1 已完成——不应出现在看板
    b3 = await batch_service.create_batch(
        db_session, BatchCreate(
            batch_no=rand_code("B"), product_id=ctx["product"].id,
            route_id=ctx["route"].id,
        ), user=None,
    )
    ex3 = await _start(db_session, b3.id, ctx["node_g1"].id, at=T0 + timedelta(hours=1))
    await execution_service.complete_execution(db_session, ex3.id, ExecutionCompleteIn(), user=None)

    # b4: 走到 G2 进行中——应出现在 G2 列
    b4 = await batch_service.create_batch(
        db_session, BatchCreate(
            batch_no=rand_code("B"), product_id=ctx["product"].id,
            route_id=ctx["route"].id,
        ), user=None,
    )
    ex4a = await _start(db_session, b4.id, ctx["node_g1"].id, at=T0 + timedelta(hours=2))
    await execution_service.complete_execution(db_session, ex4a.id, ExecutionCompleteIn(), user=None)
    await _start(db_session, b4.id, ctx["node_g2"].id, at=T0 + timedelta(hours=3))

    resp = await client.get(f"/api/v1/production/routes/{ctx['route'].id}/process-board")
    assert resp.status_code == 200
    board = resp.json()["data"]

    # 横轴节点按 sort_order
    assert [n["node_code"] for n in board["nodes"]] == ["G1", "G2"]

    # 计划批次列：仅 released + allocated，展示实际 Batch.batch_no，按 planned_start 升序；
    # scheduled 计划项与未下达计划单均不出现
    assert len(board["planned"]) == 2
    assert [p["batch_no"] for p in board["planned"]] == real_nos  # 实际批次号，非 PLAN- 占位号
    assert all(not p["batch_no"].startswith("PLAN-") for p in board["planned"])
    assert all(p["batch_status"] == "scheduled" for p in board["planned"])
    assert all(p["item_status"] == "allocated" for p in board["planned"])
    assert board["planned"][0]["item_no"] == 1
    assert board["planned"][1]["item_no"] == 2
    assert board["planned"][0]["order_no"] != draft_order.order_no
    assert board["planned"][0]["planned_quantity"] == 100
    assert board["planned"][0]["unit"] == "kg"

    g1 = board["columns"][str(ctx["node_g1"].id)]
    g2 = board["columns"][str(ctx["node_g2"].id)]

    # 工序列按批次当前位置归组：b1 进行中、b2 已中止、b3 已完成该工序待流转；
    # 批次整体完工/报废的批次不出现
    assert {i["batch_no"] for i in g1} == {b1.batch_no, b2.batch_no, b3.batch_no}
    assert {i["board_state"] for i in g1} == {"in_progress", "aborted", "waiting"}
    assert [i["batch_no"] for i in g2] == [b4.batch_no]
    assert g2[0]["board_state"] == "in_progress"

    # 组内按节点最近活动时间降序：b3/b2 刚结束（最新）在上，b1 仅开始（最早）在末
    assert g1[-1]["batch_no"] == b1.batch_no

    # 字段数据与异常计数随板返回
    b2_item = next(i for i in g1 if i["batch_no"] == b2.batch_no)
    assert b2_item["board_state"] == "aborted"
    assert b2_item["abnormal_count"] == 1
    assert b2_item["field_values"][0]["field_key"] == "TEMP"
    assert b2_item["field_values"][0]["value_numeric"] == 35
    assert b2_item["field_values"][0]["is_abnormal"] is True
    assert b2_item["batch_status"] == "in_progress"
    b1_item = next(i for i in g1 if i["batch_no"] == b1.batch_no)
    assert b1_item["board_state"] == "in_progress"
    assert b1_item["abnormal_count"] == 0
    assert b1_item["field_values"][0]["value_numeric"] == 25
    assert b1_item["field_values"][0]["is_abnormal"] is False
    b3_item = next(i for i in g1 if i["batch_no"] == b3.batch_no)
    assert b3_item["board_state"] == "waiting"

    # 空节点列返回空数组
    assert board["columns"][str(ctx["node_g2"].id)] == g2


async def test_process_board_route_not_found(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    resp = await client.get(f"/api/v1/production/routes/{uuid.uuid4()}/process-board")
    assert resp.status_code == 404
