"""全链路溯源业务测试：沿 batch_links 双向递归 + 跨路线物料链双向有限递归。

覆盖业务场景：
- 向上溯源：从合并后的子批次向上穿透两层到根批次，汇总所有谱系边
- 向下溯源：从根批次向下穿透两层到合并后的子批次，带执行摘要
- 跨路线物料溯源：A 路线批次投料消耗 B 路线批次产出 → 双向可见，物料边带类型与数量
- 物料链多级递归、防环、批次边界谱系并入、混装断点、中止执行排除
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production import repository as repo
from app.modules.production.models import BatchIntermediateConsumption
from app.modules.production.schemas import (
    BatchCreate,
    ChildBatchIn,
    DeriveIn,
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldValueIn,
    IntermediateConsumptionIn,
    IntermediateOutputIn,
    IntermediateTypeCreate,
    MergeIn,
    MergeParentIn,
    ProductCreate,
    RouteCreate,
)
from app.modules.production.service import (
    batch_service,
    execution_service,
    intermediate_service,
    route_service,
    trace_service,
)
from tests.modules.production.conftest import build_graph_in, rand_code


async def _build_lineage(db: AsyncSession, ctx: dict[str, Any]) -> dict[str, Any]:
    """构建谱系：root --derive(边界边)--> c1, c2 --merge(偏离)--> merged。

    子批次先各自完成入口工序 B（merge 要求父批次非 pending）。
    """
    root = await batch_service.create_batch(
        db,
        BatchCreate(
            batch_no=rand_code("ROOT"),
            product_id=ctx["product"].id,
            route_id=ctx["route"].id,
        ),
        user=None,
    )
    ex = await execution_service.start_execution(
        db, root.id, ExecutionStartIn(node_id=ctx["node_a"].id), user=None,
    )
    await execution_service.complete_execution(
        db, ex.id, ExecutionCompleteIn(), user=None,
    )
    children = await batch_service.derive_batches(
        db,
        root.id,
        DeriveIn(
            edge_id=ctx["edge_ab"].id,
            children=[
                ChildBatchIn(batch_no=rand_code("C1"), quantity=40),
                ChildBatchIn(batch_no=rand_code("C2"), quantity=60),
            ],
        ),
        user=None,
    )
    for child in children:
        ex_c = await execution_service.start_execution(
            db,
            child.id,
            ExecutionStartIn(
                node_id=ctx["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
            ),
            user=None,
        )
        await execution_service.complete_execution(
            db,
            ex_c.id,
            ExecutionCompleteIn(
                field_values=[FieldValueIn(field_key="yield_qty", value=30)],
            ),
            user=None,
        )
    merged = await batch_service.merge_batches(
        db,
        MergeIn(
            parents=[
                MergeParentIn(batch_id=children[0].id),
                MergeParentIn(batch_id=children[1].id),
            ],
            deviation_reason="测试合并",
            batch_no=rand_code("M"),
        ),
        user=None,
    )
    return {"root": root, "children": children, "merged": merged}


async def test_trace_upstream_from_merged(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """从合并后的子批次向上溯源：可穿透两层到 root，包含全部 4 条谱系边。"""
    lineage = await _build_lineage(db_session, published_route)
    trace = await trace_service.get_trace(db_session, lineage["merged"].id)
    batch_ids = {b.id for b in trace.batches}
    assert lineage["root"].id in batch_ids
    assert len(trace.links) == 4  # root->c1, root->c2, c1->m, c2->m
    assert all(link.link_type == "lineage" for link in trace.links)


async def test_trace_downstream_from_root(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """从根批次向下溯源：可穿透两层到 merged，root 含 1 条执行摘要。"""
    lineage = await _build_lineage(db_session, published_route)
    trace = await trace_service.get_trace(db_session, lineage["root"].id)
    batch_ids = {b.id for b in trace.batches}
    assert lineage["merged"].id in batch_ids
    root_batch = next(b for b in trace.batches if b.id == lineage["root"].id)
    assert len(root_batch.executions) == 1


# ── 跨路线物料链 ──


async def _make_im_type(db: AsyncSession) -> Any:
    """创建真实中间体类型（产出/消耗的类型校验需要）。"""
    return await intermediate_service.create_intermediate_type(
        db,
        IntermediateTypeCreate(code=rand_code("IM"), name=rand_code("物料")),
        None,
    )


async def _make_published_route(db: AsyncSession) -> dict[str, Any]:
    """新建并发布一条独立路线（不同产品），模拟另一条工艺路径。"""
    product = await route_service.create_product(
        db,
        ProductCreate(
            product_name=rand_code("产品B"), product_code=rand_code("PB"),
        ),
        user=None,
    )
    route = await route_service.create_route(
        db, RouteCreate(product_id=product.id, route_name=rand_code("工艺B")), user=None,
    )
    await route_service.save_graph(db, route.id, build_graph_in(), user=None)
    route = await route_service.publish_route(db, route.id, user=None)
    graph = await route_service.get_graph(db, route.id)
    nodes = {n.node_code: n for n in graph.nodes}
    edge_ab = next(
        e
        for e in graph.edges
        if e.from_node_id == nodes["A"].id and e.to_node_id == nodes["B"].id
    )
    return {
        "product": product,
        "route": route,
        "node_a": nodes["A"],
        "node_b": nodes["B"],
        "node_c": nodes["C"],
        "edge_ab": edge_ab,
    }


async def _produce(
    db: AsyncSession, ctx: dict[str, Any], im_type: Any,
    quantity: float = 100, batch_no_prefix: str = "B",
) -> tuple[Any, Any]:
    """在指定路线创建批次，完成首工序并产出中间体，返回 (batch, output_id)。"""
    batch = await batch_service.create_batch(
        db,
        BatchCreate(
            batch_no=rand_code(batch_no_prefix),
            product_id=ctx["product"].id,
            route_id=ctx["route"].id,
        ),
        user=None,
    )
    ex = await execution_service.start_execution(
        db, batch.id, ExecutionStartIn(node_id=ctx["node_a"].id), user=None,
    )
    await execution_service.complete_execution(
        db,
        ex.id,
        ExecutionCompleteIn(
            intermediate_outputs=[
                IntermediateOutputIn(
                    intermediate_type_id=im_type.id, quantity=quantity, unit="kg",
                ),
            ],
        ),
        user=None,
    )
    outputs = await repo.get_intermediate_outputs_by_batch(db, batch.id)
    assert outputs
    return batch, outputs[-1].id


async def _consume(
    db: AsyncSession, ctx: dict[str, Any], batch: Any, output_id: uuid.UUID,
    im_type: Any, quantity: float = 30,
) -> Any:
    """批次在指定路线开始工序并精确消耗某产出，默认首工序（入口节点）。"""
    return await execution_service.start_execution(
        db,
        batch.id,
        ExecutionStartIn(
            node_id=ctx["node_a"].id,
            intermediate_consumptions=[
                IntermediateConsumptionIn(
                    intermediate_type_id=im_type.id,
                    output_id=output_id,
                    quantity=quantity,
                    unit="kg",
                ),
            ],
        ),
        user=None,
    )


async def test_trace_cross_route_material_source(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """A 路线批次投料消耗 B 路线批次产出 → trace(A) 含 B 与物料边。"""
    im_type = await _make_im_type(db_session)
    ctx_b = await _make_published_route(db_session)
    batch_b, output_id = await _produce(db_session, ctx_b, im_type, quantity=100)

    batch_a = await batch_service.create_batch(
        db_session,
        BatchCreate(
            batch_no=rand_code("A"),
            product_id=published_route["product"].id,
            route_id=published_route["route"].id,
        ),
        user=None,
    )
    await _consume(db_session, published_route, batch_a, output_id, im_type, quantity=30)

    trace = await trace_service.get_trace(db_session, batch_a.id)
    batch_ids = {b.id for b in trace.batches}
    assert batch_b.id in batch_ids
    material = [link for link in trace.links if link.link_type == "material"]
    assert len(material) == 1
    link = material[0]
    assert link.parent_batch_id == batch_b.id
    assert link.child_batch_id == batch_a.id
    assert link.intermediate_type_id == im_type.id
    assert link.intermediate_type_name == im_type.name
    assert link.quantity == 30
    assert link.unit == "kg"


async def test_trace_cross_route_material_destination(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """反向：trace(B) 可见消耗了其产出的 A 批次（物料去向）。"""
    im_type = await _make_im_type(db_session)
    ctx_b = await _make_published_route(db_session)
    batch_b, output_id = await _produce(db_session, ctx_b, im_type, quantity=100)

    batch_a = await batch_service.create_batch(
        db_session,
        BatchCreate(
            batch_no=rand_code("A"),
            product_id=published_route["product"].id,
            route_id=published_route["route"].id,
        ),
        user=None,
    )
    await _consume(db_session, published_route, batch_a, output_id, im_type, quantity=30)

    trace = await trace_service.get_trace(db_session, batch_b.id)
    batch_ids = {b.id for b in trace.batches}
    assert batch_a.id in batch_ids
    material = [link for link in trace.links if link.link_type == "material"]
    assert len(material) == 1
    assert material[0].parent_batch_id == batch_b.id
    assert material[0].child_batch_id == batch_a.id


async def test_trace_material_chain_recursive(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """物料链多级递归：A 消耗 B 产出、B 消耗 C 产出 → trace(A) 含 B、C 两层。"""
    im_x = await _make_im_type(db_session)
    im_y = await _make_im_type(db_session)
    ctx_b = await _make_published_route(db_session)
    ctx_c = await _make_published_route(db_session)

    batch_c, output_c = await _produce(db_session, ctx_c, im_y, quantity=200)
    # B：开始首工序消耗 C 的产出，结束时产出 X
    batch_b = await batch_service.create_batch(
        db_session,
        BatchCreate(
            batch_no=rand_code("B"),
            product_id=ctx_b["product"].id,
            route_id=ctx_b["route"].id,
        ),
        user=None,
    )
    ex_b = await execution_service.start_execution(
        db_session,
        batch_b.id,
        ExecutionStartIn(
            node_id=ctx_b["node_a"].id,
            intermediate_consumptions=[
                IntermediateConsumptionIn(
                    intermediate_type_id=im_y.id,
                    output_id=output_c,
                    quantity=50,
                    unit="kg",
                ),
            ],
        ),
        user=None,
    )
    await execution_service.complete_execution(
        db_session,
        ex_b.id,
        ExecutionCompleteIn(
            intermediate_outputs=[
                IntermediateOutputIn(
                    intermediate_type_id=im_x.id, quantity=80, unit="kg",
                ),
            ],
        ),
        user=None,
    )
    outputs_b = await repo.get_intermediate_outputs_by_batch(db_session, batch_b.id)
    output_b = outputs_b[-1].id

    batch_a = await batch_service.create_batch(
        db_session,
        BatchCreate(
            batch_no=rand_code("A"),
            product_id=published_route["product"].id,
            route_id=published_route["route"].id,
        ),
        user=None,
    )
    await _consume(db_session, published_route, batch_a, output_b, im_x, quantity=20)

    trace = await trace_service.get_trace(db_session, batch_a.id)
    batch_ids = {b.id for b in trace.batches}
    assert batch_b.id in batch_ids
    assert batch_c.id in batch_ids
    material = [link for link in trace.links if link.link_type == "material"]
    pairs = {(link.parent_batch_id, link.child_batch_id) for link in material}
    assert (batch_b.id, batch_a.id) in pairs
    assert (batch_c.id, batch_b.id) in pairs


async def test_trace_material_cycle_guard(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """物料链防环：A、B 互吃产出 → 两批各出现一次，不无限递归。"""
    im_x = await _make_im_type(db_session)
    im_y = await _make_im_type(db_session)
    ctx_b = await _make_published_route(db_session)

    # A 产出 X、B 产出 Y
    batch_a = await batch_service.create_batch(
        db_session,
        BatchCreate(
            batch_no=rand_code("A"),
            product_id=published_route["product"].id,
            route_id=published_route["route"].id,
        ),
        user=None,
    )
    ex_a1 = await execution_service.start_execution(
        db_session, batch_a.id,
        ExecutionStartIn(node_id=published_route["node_a"].id), user=None,
    )
    await execution_service.complete_execution(
        db_session,
        ex_a1.id,
        ExecutionCompleteIn(
            intermediate_outputs=[
                IntermediateOutputIn(
                    intermediate_type_id=im_x.id, quantity=100, unit="kg",
                ),
            ],
        ),
        user=None,
    )
    output_a = (await repo.get_intermediate_outputs_by_batch(db_session, batch_a.id))[-1].id

    batch_b = await batch_service.create_batch(
        db_session,
        BatchCreate(
            batch_no=rand_code("B"),
            product_id=ctx_b["product"].id,
            route_id=ctx_b["route"].id,
        ),
        user=None,
    )
    ex_b1 = await execution_service.start_execution(
        db_session, batch_b.id,
        ExecutionStartIn(node_id=ctx_b["node_a"].id), user=None,
    )
    await execution_service.complete_execution(
        db_session,
        ex_b1.id,
        ExecutionCompleteIn(
            intermediate_outputs=[
                IntermediateOutputIn(
                    intermediate_type_id=im_y.id, quantity=100, unit="kg",
                ),
            ],
        ),
        user=None,
    )
    output_b = (await repo.get_intermediate_outputs_by_batch(db_session, batch_b.id))[-1].id

    # 互吃：A 消耗 B 产出、B 消耗 A 产出。
    # 各自第二次执行落在 node_b（前道 node_a 已完成属合法流转，node_b 有必填字段 temp）
    for ctx, batch, output_id, im_type in [
        (published_route, batch_a, output_b, im_y),
        (ctx_b, batch_b, output_a, im_x),
    ]:
        await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=ctx["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
                intermediate_consumptions=[
                    IntermediateConsumptionIn(
                        intermediate_type_id=im_type.id,
                        output_id=output_id,
                        quantity=10,
                        unit="kg",
                    ),
                ],
            ),
            user=None,
        )

    trace = await trace_service.get_trace(db_session, batch_a.id)
    batch_ids = {b.id for b in trace.batches}
    assert batch_b.id in batch_ids
    material = [link for link in trace.links if link.link_type == "material"]
    pairs = {(link.parent_batch_id, link.child_batch_id) for link in material}
    assert pairs == {(batch_b.id, batch_a.id), (batch_a.id, batch_b.id)}


async def test_trace_material_no_family_expansion(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """物料链命中的批次只展示批次本身，不展开其谱系家族。

    root_b --边界--> b2，b2 产出 X；A 消耗 X。trace(A) 应显示 b2（投料来源）
    本身，而 b2 的前序 root_b 与 A 无直接关系，不应出现，也不应带入
    b2 家族的谱系边（需看 b2 谱系时点击该节点重新溯源）。
    """
    im_type = await _make_im_type(db_session)
    ctx_b = await _make_published_route(db_session)

    root_b, _ = await _produce(db_session, ctx_b, im_type, quantity=0.1)
    # 边界边分裂：root_b → b2，b2 完成入口工序并产出
    children = await batch_service.derive_batches(
        db_session,
        root_b.id,
        DeriveIn(
            edge_id=ctx_b["edge_ab"].id,
            children=[ChildBatchIn(batch_no=rand_code("B2"), quantity=50)],
        ),
        user=None,
    )
    b2 = children[0]
    ex_b2 = await execution_service.start_execution(
        db_session, b2.id,
        ExecutionStartIn(
            node_id=ctx_b["node_b"].id,
            field_values=[FieldValueIn(field_key="temp", value=25)],
        ),
        user=None,
    )
    await execution_service.complete_execution(
        db_session,
        ex_b2.id,
        ExecutionCompleteIn(
            intermediate_outputs=[
                IntermediateOutputIn(
                    intermediate_type_id=im_type.id, quantity=60, unit="kg",
                ),
            ],
        ),
        user=None,
    )
    output_b2 = (await repo.get_intermediate_outputs_by_batch(db_session, b2.id))[-1].id

    batch_a = await batch_service.create_batch(
        db_session,
        BatchCreate(
            batch_no=rand_code("A"),
            product_id=published_route["product"].id,
            route_id=published_route["route"].id,
        ),
        user=None,
    )
    await _consume(db_session, published_route, batch_a, output_b2, im_type, quantity=20)

    trace = await trace_service.get_trace(db_session, batch_a.id)
    batch_ids = {b.id for b in trace.batches}
    assert b2.id in batch_ids
    assert root_b.id not in batch_ids  # 不展开投料来源的谱系家族
    lineage_pairs = {
        (link.parent_batch_id, link.child_batch_id)
        for link in trace.links if link.link_type == "lineage"
    }
    assert not lineage_pairs  # A 无自身谱系，也不应带入 b2 家族的谱系边
    material = [link for link in trace.links if link.link_type == "material"]
    assert len(material) == 1
    assert material[0].parent_batch_id == b2.id


async def test_trace_material_destination_family_not_expanded(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """去向批次的其他前序不混入溯源图（对应 TEST003-FJ → TEST004-TL4 场景）。

    A 产出 X；B 路线 root_d --边界--> d2，d2 首工序消耗 A 的 X。
    trace(A) 应显示 d2（物料去向）本身，d2 的前序 root_d 与 A 无直接关系，
    不应出现，也不应带入 d2 家族的谱系边。
    """
    im_type = await _make_im_type(db_session)
    ctx_b = await _make_published_route(db_session)

    # 目标批次 A：完成首工序并产出 X
    batch_a = await batch_service.create_batch(
        db_session,
        BatchCreate(
            batch_no=rand_code("A"),
            product_id=published_route["product"].id,
            route_id=published_route["route"].id,
        ),
        user=None,
    )
    ex_a = await execution_service.start_execution(
        db_session, batch_a.id,
        ExecutionStartIn(node_id=published_route["node_a"].id), user=None,
    )
    await execution_service.complete_execution(
        db_session,
        ex_a.id,
        ExecutionCompleteIn(
            intermediate_outputs=[
                IntermediateOutputIn(
                    intermediate_type_id=im_type.id, quantity=100, unit="kg",
                ),
            ],
        ),
        user=None,
    )
    output_a = (await repo.get_intermediate_outputs_by_batch(db_session, batch_a.id))[-1].id

    # 去向批次：root_d --边界--> d2，d2 首工序消耗 A 的产出
    root_d = await batch_service.create_batch(
        db_session,
        BatchCreate(
            batch_no=rand_code("RD"),
            product_id=ctx_b["product"].id,
            route_id=ctx_b["route"].id,
        ),
        user=None,
    )
    ex_d = await execution_service.start_execution(
        db_session, root_d.id,
        ExecutionStartIn(node_id=ctx_b["node_a"].id), user=None,
    )
    await execution_service.complete_execution(
        db_session, ex_d.id, ExecutionCompleteIn(), user=None,
    )
    d2 = (
        await batch_service.derive_batches(
            db_session,
            root_d.id,
            DeriveIn(
                edge_id=ctx_b["edge_ab"].id,
                children=[ChildBatchIn(batch_no=rand_code("D2"), quantity=50)],
            ),
            user=None,
        )
    )[0]
    await execution_service.start_execution(
        db_session,
        d2.id,
        ExecutionStartIn(
            node_id=ctx_b["node_b"].id,
            field_values=[FieldValueIn(field_key="temp", value=25)],
            intermediate_consumptions=[
                IntermediateConsumptionIn(
                    intermediate_type_id=im_type.id,
                    output_id=output_a,
                    quantity=30,
                    unit="kg",
                ),
            ],
        ),
        user=None,
    )

    trace = await trace_service.get_trace(db_session, batch_a.id)
    batch_ids = {b.id for b in trace.batches}
    assert d2.id in batch_ids        # 物料去向可见
    assert root_d.id not in batch_ids  # 去向批次的其他前序不出现
    material = [link for link in trace.links if link.link_type == "material"]
    assert len(material) == 1
    assert material[0].parent_batch_id == batch_a.id
    assert material[0].child_batch_id == d2.id
    lineage_pairs = {
        (link.parent_batch_id, link.child_batch_id)
        for link in trace.links if link.link_type == "lineage"
    }
    assert not lineage_pairs  # 不带入 d2 家族的谱系边


async def test_trace_material_ignores_container_consumption(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """混装消耗（无 output_id）不产生物料边 —— 刻意溯源断点。"""
    im_type = await _make_im_type(db_session)
    batch_a = await batch_service.create_batch(
        db_session,
        BatchCreate(
            batch_no=rand_code("A"),
            product_id=published_route["product"].id,
            route_id=published_route["route"].id,
        ),
        user=None,
    )
    db_session.add(
        BatchIntermediateConsumption(
            batch_id=batch_a.id,
            execution_id=uuid.uuid4(),
            node_id=published_route["node_a"].id,
            intermediate_type_id=im_type.id,
            output_id=None,
            container_id=uuid.uuid4(),
            quantity=5,
            unit="kg",
        )
    )
    await db_session.flush()

    trace = await trace_service.get_trace(db_session, batch_a.id)
    assert not [link for link in trace.links if link.link_type == "material"]


async def test_trace_material_excludes_aborted_execution(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """中止执行的消耗不产生物料边。"""
    im_type = await _make_im_type(db_session)
    ctx_b = await _make_published_route(db_session)
    batch_b, output_id = await _produce(db_session, ctx_b, im_type, quantity=100)

    batch_a = await batch_service.create_batch(
        db_session,
        BatchCreate(
            batch_no=rand_code("A"),
            product_id=published_route["product"].id,
            route_id=published_route["route"].id,
        ),
        user=None,
    )
    ex_a = await _consume(db_session, published_route, batch_a, output_id, im_type, quantity=30)
    await execution_service.abort_execution(db_session, ex_a.id, user=None)

    trace = await trace_service.get_trace(db_session, batch_a.id)
    batch_ids = {b.id for b in trace.batches}
    assert batch_b.id not in batch_ids
    assert not [link for link in trace.links if link.link_type == "material"]


async def test_trace_material_no_sibling_expansion(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """兄弟批次不被拉入溯源图：只显示谱系前后序 + 物料来源链，不展开家族成员的物料关系。

    场景：A 路线 root 分裂出 c1、c2，c1、c2 都消耗 B 路线的同一批产出。
    追踪 c1 时应看到 B（投料来源）与 root（前序），c2 既不是 c1 的前后序
    也不是 c1 的投料来源，不应出现。
    """
    im_type = await _make_im_type(db_session)
    ctx_b = await _make_published_route(db_session)
    batch_b, output_id = await _produce(db_session, ctx_b, im_type, quantity=100)

    root_a = await batch_service.create_batch(
        db_session,
        BatchCreate(
            batch_no=rand_code("RA"),
            product_id=published_route["product"].id,
            route_id=published_route["route"].id,
        ),
        user=None,
    )
    ex_root = await execution_service.start_execution(
        db_session, root_a.id,
        ExecutionStartIn(node_id=published_route["node_a"].id), user=None,
    )
    await execution_service.complete_execution(
        db_session, ex_root.id, ExecutionCompleteIn(), user=None,
    )
    children = await batch_service.derive_batches(
        db_session,
        root_a.id,
        DeriveIn(
            edge_id=published_route["edge_ab"].id,
            children=[
                ChildBatchIn(batch_no=rand_code("C1"), quantity=40),
                ChildBatchIn(batch_no=rand_code("C2"), quantity=60),
            ],
        ),
        user=None,
    )
    c1, c2 = children
    for c in children:
        await execution_service.start_execution(
            db_session,
            c.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
                intermediate_consumptions=[
                    IntermediateConsumptionIn(
                        intermediate_type_id=im_type.id,
                        output_id=output_id,
                        quantity=10,
                        unit="kg",
                    ),
                ],
            ),
            user=None,
        )

    trace = await trace_service.get_trace(db_session, c1.id)
    batch_ids = {b.id for b in trace.batches}
    assert batch_b.id in batch_ids      # 投料来源可见
    assert root_a.id in batch_ids       # 谱系前序可见
    assert c2.id not in batch_ids       # 兄弟批次不出现
