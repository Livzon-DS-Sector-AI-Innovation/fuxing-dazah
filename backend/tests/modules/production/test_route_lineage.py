"""工艺路线血缘端到端测试。

覆盖场景：
- copy_route 写入路线级 + 节点级血缘；save_graph 编辑（同 node_code）后血缘保留
- 工段汇总沿血缘合并前身路线批次：列挂在当前路线代表节点下、旧版独有字段保留
- A→B→C 版本链：看 C 含全部、看 B 不含 C、看 A 仅自身
- 计算字段跨版本：复刻不带计算字段，前身批次按自身路线展开后映射到当前列
- 字段趋势沿血缘合并前身批次点；存量（仅路线级血缘）按 node_code 兜底对齐
- 权限锚定代表节点：当前路线有分配即可见前身历史批次
- 未发布的复刻（draft）不进汇总，与原 exclude_draft_route 口径一致
"""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import ProcessRoute, StageAssignment
from app.modules.production.repository import route as route_repo
from app.modules.production.schemas import (
    ComputedFieldIn,
    EdgeIn,
    FieldDefIn,
    NodeIn,
    RouteGraphIn,
)
from app.modules.production.service import route_service
from app.platform.identity.models import User
from tests.modules.production.conftest import rand_code
from tests.modules.production.test_analytics_api import _fill_fields
from tests.modules.production.test_computed_service import _make_batch, _make_route_ctx

_T1 = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
_T2 = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)
_T3 = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)


def _g1_graph(fields_g1: list[FieldDefIn]) -> RouteGraphIn:
    """G1(工段一)→G2(工段二) 两节点图，G1 字段可定制。"""
    return RouteGraphIn(
        nodes=[
            NodeIn(
                node_code="G1", name="工序一", stage_name="工段一", sort_order=1,
                fields=fields_g1,
            ),
            NodeIn(
                node_code="G2", name="工序二", stage_name="工段二", sort_order=2,
                fields=[
                    FieldDefIn(
                        field_key="A2", field_label="产出量", phase="end",
                        data_type="numeric",
                    ),
                ],
            ),
        ],
        edges=[EdgeIn(from_node_code="G1", to_node_code="G2", is_batch_boundary=True)],
        computed_fields=[],
    )


# B 版本 G1 的字段：保留 A1、删 B1、新增 C1
_B_FIELDS = [
    FieldDefIn(field_key="A1", field_label="投料量", phase="end", data_type="numeric", sort_order=1),
    FieldDefIn(field_key="C1", field_label="新增量", phase="end", data_type="numeric", sort_order=2),
]


async def _node(db: AsyncSession, route_id: uuid.UUID, node_code: str):
    graph = await route_service.get_graph(db, route_id)
    return next(n for n in graph.nodes if n.node_code == node_code)


async def _clone_published(
    db: AsyncSession, source_route_id: uuid.UUID, product,
) -> ProcessRoute:
    """复刻为发布路线（不编辑图，结构与源一致）。"""
    clone = await route_service.copy_route(
        db, source_route_id, rand_code("V"), user=None,
    )
    await route_service.publish_route(db, clone.id, user=None)
    return clone


async def _fill_g1(
    db: AsyncSession, route_id: uuid.UUID, batch, fields: dict[str, float], at: datetime,
) -> None:
    node = await _node(db, route_id, "G1")
    await _fill_fields(db, batch.id, node.id, fields, at)


class TestRouteLineage:
    async def test_copy_route_records_lineage(
        self, db_session: AsyncSession,
    ) -> None:
        """复刻写入路线级血缘，且每个克隆节点的 origin 指向源节点。"""
        ctx = await _make_route_ctx(db_session)
        clone = await route_service.copy_route(
            db_session, ctx["route"].id, rand_code("V"), user=None,
        )
        assert clone.origin_route_id == ctx["route"].id
        source_by_code = {
            n.node_code: n
            for n in await route_repo.get_route_nodes(db_session, ctx["route"].id)
        }
        for n in await route_repo.get_route_nodes(db_session, clone.id):
            assert n.origin_node_id == source_by_code[n.node_code].id

    async def test_save_graph_preserves_node_lineage(
        self, db_session: AsyncSession,
    ) -> None:
        """复刻草稿编辑（同 node_code 整图重建）后，节点血缘指针保留。"""
        ctx = await _make_route_ctx(db_session)
        clone = await route_service.copy_route(
            db_session, ctx["route"].id, rand_code("V"), user=None,
        )
        await route_service.save_graph(
            db_session, clone.id, _g1_graph(_B_FIELDS), user=None,
        )
        source_by_code = {
            n.node_code: n
            for n in await route_repo.get_route_nodes(db_session, ctx["route"].id)
        }
        for n in await route_repo.get_route_nodes(db_session, clone.id):
            assert n.origin_node_id == source_by_code[n.node_code].id

    async def test_stage_summary_merges_lineage_batches(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """A 跑批次 → 复刻 B（删 B1 增 C1）发布再跑 → 查 B 含两代批次，列挂 B 节点。"""
        ctx = await _make_route_ctx(db_session, publish=True)
        bA = await _make_batch(db_session, ctx)
        await _fill_g1(db_session, ctx["route"].id, bA, {"A1": 10.0, "B1": 20.0}, _T1)

        route_b = await route_service.copy_route(
            db_session, ctx["route"].id, rand_code("V"), user=None,
        )
        await route_service.save_graph(
            db_session, route_b.id, _g1_graph(_B_FIELDS), user=None,
        )
        await route_service.publish_route(db_session, route_b.id, user=None)
        b_g1 = await _node(db_session, route_b.id, "G1")
        bB = await _make_batch(db_session, {"product": ctx["product"], "route": route_b})
        await _fill_g1(db_session, route_b.id, bB, {"A1": 30.0, "C1": 40.0}, _T2)

        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(route_b.id), "view_all": "true"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["merged_routes"] == [ctx["route"].route_name]
        rows = {r["batch_no"]: r for r in data["rows"]}
        assert set(rows) == {bA.batch_no, bB.batch_no}
        # G1 家族列：当前版本字段在前（A1、C1），旧版独有字段保留在后（B1）
        g1_cols = [c for c in data["columns"] if c["node_code"] == "G1"]
        assert [c["field_key"] for c in g1_cols] == ["A1", "C1", "B1"]
        assert all(c["node_id"] == str(b_g1.id) for c in g1_cols)
        # A 时代批次的值映射到 B 的列；B 删掉的字段值不丢、新字段列为空
        assert rows[bA.batch_no]["values"][f"{b_g1.id}.A1"] == 10.0
        assert rows[bA.batch_no]["values"][f"{b_g1.id}.B1"] == 20.0
        assert f"{b_g1.id}.C1" not in rows[bA.batch_no]["values"]
        assert rows[bB.batch_no]["values"][f"{b_g1.id}.A1"] == 30.0
        assert rows[bB.batch_no]["values"][f"{b_g1.id}.C1"] == 40.0

    async def test_stage_summary_chain_three_versions(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """A→B→C 链：看 C 含三批、看 B 不含 C 的批次、看 A 仅自身、A 无合并提示。"""
        ctx = await _make_route_ctx(db_session, publish=True)
        bA = await _make_batch(db_session, ctx)
        await _fill_g1(db_session, ctx["route"].id, bA, {"A1": 1.0}, _T1)

        route_b = await _clone_published(db_session, ctx["route"].id, ctx["product"])
        bB = await _make_batch(db_session, {"product": ctx["product"], "route": route_b})
        await _fill_g1(db_session, route_b.id, bB, {"A1": 2.0}, _T2)

        route_c = await _clone_published(db_session, route_b.id, ctx["product"])
        bC = await _make_batch(db_session, {"product": ctx["product"], "route": route_c})
        await _fill_g1(db_session, route_c.id, bC, {"A1": 3.0}, _T3)

        async def view(route_id: uuid.UUID) -> tuple[set[str], list[str]]:
            resp = await client.get(
                "/api/v1/production/analytics/stage-summary",
                params={"route_id": str(route_id), "view_all": "true"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            return {r["batch_no"] for r in data["rows"]}, data["merged_routes"]

        nos, merged = await view(route_c.id)
        assert nos == {bA.batch_no, bB.batch_no, bC.batch_no}
        assert merged == [ctx["route"].route_name, route_b.route_name]
        nos, merged = await view(route_b.id)
        assert nos == {bA.batch_no, bB.batch_no}
        assert merged == [ctx["route"].route_name]
        nos, merged = await view(ctx["route"].id)
        assert nos == {bA.batch_no}
        assert merged == []

    async def test_stage_summary_computed_from_ancestor_routes(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """复刻不带计算字段：A 批次按 A 路线公式展开后映射到 B 的代表列，B 批次为空。"""
        ctx = await _make_route_ctx(
            db_session,
            publish=True,
            computed_fields=[
                ComputedFieldIn(
                    node_code="G1", field_key="C1", field_label="总投料",
                    formula="{G1.A1}+{G1.B1}",
                ),
            ],
        )
        bA = await _make_batch(db_session, ctx)
        await _fill_g1(db_session, ctx["route"].id, bA, {"A1": 10.0, "B1": 20.0}, _T1)

        route_b = await _clone_published(db_session, ctx["route"].id, ctx["product"])
        b_g1 = await _node(db_session, route_b.id, "G1")
        bB = await _make_batch(db_session, {"product": ctx["product"], "route": route_b})
        await _fill_g1(db_session, route_b.id, bB, {"A1": 1.0, "B1": 2.0}, _T2)

        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(route_b.id), "view_all": "true"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        computed_cols = [c for c in data["columns"] if c["kind"] == "computed"]
        assert [c["field_key"] for c in computed_cols] == ["C1"]
        assert computed_cols[0]["node_id"] == str(b_g1.id)
        rows = {r["batch_no"]: r for r in data["rows"]}
        assert rows[bA.batch_no]["computed"][f"{b_g1.id}.C1"] == 30.0
        assert rows[bB.batch_no]["computed"] == {}

    async def test_field_trend_merges_lineage(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """字段趋势查 B 的 G2：series 含 A、B 两代批次的点，按填写时间排序。"""
        ctx = await _make_route_ctx(db_session, publish=True)
        bA = await _make_batch(db_session, ctx)
        await _fill_fields(
            db_session, bA.id, ctx["node_g2"].id, {"A2": 5.0}, _T1,
        )
        route_b = await _clone_published(db_session, ctx["route"].id, ctx["product"])
        b_g2 = await _node(db_session, route_b.id, "G2")
        bB = await _make_batch(db_session, {"product": ctx["product"], "route": route_b})
        await _fill_fields(db_session, bB.id, b_g2.id, {"A2": 7.0}, _T2)

        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={"route_id": str(route_b.id), "node_code": "G2"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["merged_routes"] == [ctx["route"].route_name]
        assert [s["field_key"] for s in data["series"]] == ["A2"]
        points = data["series"][0]["data_points"]
        assert [p["batch_no"] for p in points] == [bA.batch_no, bB.batch_no]
        assert [p["value"] for p in points] == [5.0, 7.0]

    async def test_lineage_code_fallback_without_node_pointers(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """存量回填场景：仅路线级血缘、节点无指针 → 按 node_code 兜底对齐。"""
        ctx = await _make_route_ctx(db_session, publish=True)
        bA = await _make_batch(db_session, ctx)
        await _fill_fields(
            db_session, bA.id, ctx["node_g2"].id, {"A2": 5.0}, _T1,
        )
        route_b = await _clone_published(db_session, ctx["route"].id, ctx["product"])
        # 模拟只回填了 origin_route_id、节点级指针缺失
        for n in await route_repo.get_route_nodes(db_session, route_b.id):
            n.origin_node_id = None
        await db_session.flush()
        b_g2 = await _node(db_session, route_b.id, "G2")
        bB = await _make_batch(db_session, {"product": ctx["product"], "route": route_b})
        await _fill_fields(db_session, bB.id, b_g2.id, {"A2": 7.0}, _T2)

        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={"route_id": str(route_b.id), "node_code": "G2"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["merged_routes"] == [ctx["route"].route_name]
        points = data["series"][0]["data_points"]
        assert [p["batch_no"] for p in points] == [bA.batch_no, bB.batch_no]

    async def test_stage_summary_permission_extends_to_lineage(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        """权限锚定代表节点：仅在 B 上有工段分配的负责人，看 B 也能看到 A 的历史批次。"""
        ctx = await _make_route_ctx(db_session, publish=True)
        bA = await _make_batch(db_session, ctx)
        await _fill_g1(db_session, ctx["route"].id, bA, {"A1": 10.0}, _T1)

        route_b = await _clone_published(db_session, ctx["route"].id, ctx["product"])
        bB = await _make_batch(db_session, {"product": ctx["product"], "route": route_b})
        await _fill_g1(db_session, route_b.id, bB, {"A1": 30.0}, _T2)
        # 只在 B 上分配工段一（A 上无任何分配）
        db_session.add(
            StageAssignment(
                user_id=test_user.id, stage_name="工段一", route_id=route_b.id,
            )
        )
        await db_session.flush()

        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(route_b.id)},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        # 两代批次都在；无分配的 G2 家族不出现
        rows = {r["batch_no"]: r for r in data["rows"]}
        assert set(rows) == {bA.batch_no, bB.batch_no}
        assert {c["node_code"] for c in data["columns"]} == {"G1"}

    async def test_stage_summary_draft_clone_still_empty(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """未发布的复刻（draft）不进汇总，与原 exclude_draft_route 口径一致。"""
        ctx = await _make_route_ctx(db_session, publish=True)
        bA = await _make_batch(db_session, ctx)
        await _fill_g1(db_session, ctx["route"].id, bA, {"A1": 1.0}, _T1)
        route_b = await route_service.copy_route(
            db_session, ctx["route"].id, rand_code("V"), user=None,
        )

        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(route_b.id), "view_all": "true"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["columns"] == []
        assert data["rows"] == []
        assert data["merged_routes"] == []
