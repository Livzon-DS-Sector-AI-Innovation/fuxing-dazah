"""computed_service 展开与谱系聚合。

覆盖业务场景：
- 展开：同节点多字段求和、链式引用拓扑序、跨工序引用、
  引用缺失为 None、回流取最新 completed 执行、父批次回退、无计算字段返回空
- 聚合：普通字段求和（缺失跳过）、子批计算字段求和、
  无子批返回 None、多级子批全部纳入
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import (
    Batch,
    BatchLink,
    NodeExecution,
    NodeFieldValue,
)
from app.modules.production.schemas import (
    ComputedFieldIn,
    ComputedFieldValueOut,
    EdgeIn,
    FieldDefIn,
    NodeIn,
    ProductCreate,
    RouteCreate,
    RouteGraphIn,
)
from app.modules.production.service import computed_service, route_service
from tests.modules.production.conftest import rand_code


async def _make_route_ctx(
    db: AsyncSession,
    computed_fields: list[ComputedFieldIn] | None = None,
    publish: bool = False,
) -> dict[str, Any]:
    """构建路线 G1→G2：G1 有数值字段 A1/B1，G2 有数值字段 A2，可挂计算字段。

    publish=True 时发布路线（数据汇总只覆盖非草稿路线）。
    """
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
                    FieldDefIn(field_key="A1", field_label="投料量", phase="end", data_type="numeric"),
                    FieldDefIn(field_key="B1", field_label="补料量", phase="end", data_type="numeric"),
                ],
            ),
            NodeIn(
                node_code="G2",
                name="工序二",
                stage_name="工段二",
                sort_order=2,
                fields=[
                    FieldDefIn(field_key="A2", field_label="产出量", phase="end", data_type="numeric"),
                ],
            ),
        ],
        edges=[EdgeIn(from_node_code="G1", to_node_code="G2", is_batch_boundary=True)],
        computed_fields=computed_fields or [],
    )
    await route_service.save_graph(db, route.id, graph, user=None)
    if publish:
        await route_service.publish_route(db, route.id, user=None)
    graph_out = await route_service.get_graph(db, route.id)
    nodes = {n.node_code: n for n in graph_out.nodes}
    return {"product": product, "route": route, "node_g1": nodes["G1"], "node_g2": nodes["G2"]}


async def _make_batch(db: AsyncSession, ctx: dict[str, Any]) -> Batch:
    batch = Batch(
        batch_no=rand_code("B"),
        product_id=ctx["product"].id,
        route_id=ctx["route"].id,
        status="in_progress",
    )
    db.add(batch)
    await db.flush()
    return batch


async def _add_execution(
    db: AsyncSession,
    batch_id: uuid.UUID,
    node_id: uuid.UUID,
    *,
    seq: int = 1,
    status: str = "completed",
    finished_at: datetime | None = None,
    field_values: dict[str, float | None] | None = None,
) -> NodeExecution:
    """手造一次节点执行及字段值，精确控制 seq / 完成时间 / 数值。"""
    ex = NodeExecution(
        batch_id=batch_id,
        node_id=node_id,
        execution_seq=seq,
        status=status,
        started_at=datetime.now(UTC),
        finished_at=(
            finished_at
            if finished_at is not None
            else (datetime.now(UTC) if status == "completed" else None)
        ),
    )
    db.add(ex)
    await db.flush()
    for key, val in (field_values or {}).items():
        db.add(
            NodeFieldValue(
                execution_id=ex.id,
                field_def_id=uuid.uuid4(),
                field_key=key,
                field_label=key,
                phase="end",
                value_numeric=val,
            )
        )
    await db.flush()
    return ex


async def _link(db: AsyncSession, parent_id: uuid.UUID, child_id: uuid.UUID) -> None:
    db.add(BatchLink(parent_batch_id=parent_id, child_batch_id=child_id))
    await db.flush()


def _result_map(results: list[ComputedFieldValueOut]) -> dict[str, float | None]:
    return {r.field_key: r.value for r in results}


class TestExpandComputedFields:
    async def test_same_node_two_fields(
        self, db_session: AsyncSession,
    ) -> None:
        # G1.A1=10, G1.B1=20, C1={G1.A1}+{G1.B1} → 30
        ctx = await _make_route_ctx(
            db_session,
            computed_fields=[
                ComputedFieldIn(
                    node_code="G1", field_key="C1", field_label="总投料",
                    formula="{G1.A1}+{G1.B1}",
                ),
            ],
        )
        batch = await _make_batch(db_session, ctx)
        await _add_execution(
            db_session, batch.id, ctx["node_g1"].id,
            field_values={"A1": 10, "B1": 20},
        )
        results = await computed_service.expand_computed_fields(db_session, batch)
        assert _result_map(results) == {"C1": 30}
        assert results[0].field_label == "总投料"

    async def test_chain_ref(self, db_session: AsyncSession) -> None:
        # C1={G1.A1}*2; C2={G1.C1}+5 → 25（拓扑序：C1 先于 C2）
        ctx = await _make_route_ctx(
            db_session,
            computed_fields=[
                ComputedFieldIn(
                    node_code="G1", field_key="C1", field_label="折干",
                    formula="{G1.A1}*2", sort_order=1,
                ),
                ComputedFieldIn(
                    node_code="G1", field_key="C2", field_label="加成",
                    formula="{G1.C1}+5", sort_order=2,
                ),
            ],
        )
        batch = await _make_batch(db_session, ctx)
        await _add_execution(
            db_session, batch.id, ctx["node_g1"].id, field_values={"A1": 10},
        )
        results = await computed_service.expand_computed_fields(db_session, batch)
        assert _result_map(results) == {"C1": 20, "C2": 25}
        assert [r.field_key for r in results] == ["C1", "C2"]

    async def test_cross_node_ref(self, db_session: AsyncSession) -> None:
        # G2.A2=100（前工序已完成）, C2={G1.A1}+{G2.A2} → 110
        ctx = await _make_route_ctx(
            db_session,
            computed_fields=[
                ComputedFieldIn(
                    node_code="G2", field_key="C2", field_label="合计",
                    formula="{G1.A1}+{G2.A2}",
                ),
            ],
        )
        batch = await _make_batch(db_session, ctx)
        await _add_execution(
            db_session, batch.id, ctx["node_g1"].id, field_values={"A1": 10},
        )
        await _add_execution(
            db_session, batch.id, ctx["node_g2"].id, field_values={"A2": 100},
        )
        results = await computed_service.expand_computed_fields(db_session, batch)
        assert _result_map(results) == {"C2": 110}

    async def test_missing_ref_is_none(self, db_session: AsyncSession) -> None:
        # A1 未填 → C1 为 None
        ctx = await _make_route_ctx(
            db_session,
            computed_fields=[
                ComputedFieldIn(
                    node_code="G1", field_key="C1", field_label="总投料",
                    formula="{G1.A1}+{G1.B1}",
                ),
            ],
        )
        batch = await _make_batch(db_session, ctx)
        await _add_execution(
            db_session, batch.id, ctx["node_g1"].id, field_values={"B1": 20},
        )
        results = await computed_service.expand_computed_fields(db_session, batch)
        assert _result_map(results) == {"C1": None}

    async def test_rework_uses_latest_completed(
        self, db_session: AsyncSession,
    ) -> None:
        # 同节点 execution_seq 1 值 10、seq 2 值 20 → C1 用 20
        ctx = await _make_route_ctx(
            db_session,
            computed_fields=[
                ComputedFieldIn(
                    node_code="G1", field_key="C1", field_label="总投料",
                    formula="{G1.A1}",
                ),
            ],
        )
        batch = await _make_batch(db_session, ctx)
        await _add_execution(
            db_session, batch.id, ctx["node_g1"].id, seq=1,
            finished_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
            field_values={"A1": 10},
        )
        await _add_execution(
            db_session, batch.id, ctx["node_g1"].id, seq=2,
            finished_at=datetime(2026, 8, 2, 10, 0, tzinfo=UTC),
            field_values={"A1": 20},
        )
        results = await computed_service.expand_computed_fields(db_session, batch)
        assert _result_map(results) == {"C1": 20}

    async def test_fallback_to_parent_batch(
        self, db_session: AsyncSession,
    ) -> None:
        # 父批次 G2.A2=100，子批次无 G2 执行 → 子批次 C2 引用 G2.A2 取到 100
        ctx = await _make_route_ctx(
            db_session,
            computed_fields=[
                ComputedFieldIn(
                    node_code="G2", field_key="C2", field_label="父值引用",
                    formula="{G2.A2}",
                ),
            ],
        )
        parent = await _make_batch(db_session, ctx)
        await _add_execution(
            db_session, parent.id, ctx["node_g2"].id, field_values={"A2": 100},
        )
        child = await _make_batch(db_session, ctx)
        await _link(db_session, parent.id, child.id)
        results = await computed_service.expand_computed_fields(db_session, child)
        assert _result_map(results) == {"C2": 100}

    async def test_no_computed_fields_returns_empty(
        self, db_session: AsyncSession,
    ) -> None:
        # 路线无计算字段 → []
        ctx = await _make_route_ctx(db_session)
        batch = await _make_batch(db_session, ctx)
        await _add_execution(
            db_session, batch.id, ctx["node_g1"].id, field_values={"A1": 10},
        )
        results = await computed_service.expand_computed_fields(db_session, batch)
        assert results == []


class TestAggregateChildren:
    async def test_sum_children_field(self, db_session: AsyncSession) -> None:
        # 父 D 子 d1(5) d2(7) d3(None) → sum=12
        ctx = await _make_route_ctx(db_session)
        parent = await _make_batch(db_session, ctx)
        children = [await _make_batch(db_session, ctx) for _ in range(3)]
        for child in children:
            await _link(db_session, parent.id, child.id)
        await _add_execution(
            db_session, children[0].id, ctx["node_g2"].id, field_values={"A2": 5},
        )
        await _add_execution(
            db_session, children[1].id, ctx["node_g2"].id, field_values={"A2": 7},
        )
        await _add_execution(
            db_session, children[2].id, ctx["node_g2"].id, field_values={},
        )
        total = await computed_service.aggregate_children_field(
            db_session, parent.id, "A2", "G2",
        )
        assert total == 12

    async def test_sum_children_computed_field(
        self, db_session: AsyncSession,
    ) -> None:
        # 子批 C1 分别为 3、4 → sum=7
        ctx = await _make_route_ctx(
            db_session,
            computed_fields=[
                ComputedFieldIn(
                    node_code="G1", field_key="C1", field_label="总投料",
                    formula="{G1.A1}",
                ),
            ],
        )
        parent = await _make_batch(db_session, ctx)
        children = [await _make_batch(db_session, ctx) for _ in range(2)]
        for child in children:
            await _link(db_session, parent.id, child.id)
        await _add_execution(
            db_session, children[0].id, ctx["node_g1"].id, field_values={"A1": 3},
        )
        await _add_execution(
            db_session, children[1].id, ctx["node_g1"].id, field_values={"A1": 4},
        )
        total = await computed_service.aggregate_children_field(
            db_session, parent.id, "C1", None,
        )
        assert total == 7

    async def test_no_children_returns_none(
        self, db_session: AsyncSession,
    ) -> None:
        # 无子批次 → None
        ctx = await _make_route_ctx(db_session)
        parent = await _make_batch(db_session, ctx)
        total = await computed_service.aggregate_children_field(
            db_session, parent.id, "A2", "G2",
        )
        assert total is None

    async def test_multilevel_children_included(
        self, db_session: AsyncSession,
    ) -> None:
        # D→d1→e1，sum 含 e1
        ctx = await _make_route_ctx(db_session)
        parent = await _make_batch(db_session, ctx)
        d1 = await _make_batch(db_session, ctx)
        e1 = await _make_batch(db_session, ctx)
        await _link(db_session, parent.id, d1.id)
        await _link(db_session, d1.id, e1.id)
        await _add_execution(
            db_session, d1.id, ctx["node_g2"].id, field_values={"A2": 8},
        )
        await _add_execution(
            db_session, e1.id, ctx["node_g2"].id, field_values={"A2": 9},
        )
        total = await computed_service.aggregate_children_field(
            db_session, parent.id, "A2", "G2",
        )
        assert total == 17
