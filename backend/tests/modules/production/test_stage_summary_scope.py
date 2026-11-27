"""数据汇总口径缺陷的行为测试。

覆盖三个已确认的缺陷（先红后绿）：
- 权限锚定只认当前路线代表节点：授权加在前身路线（克隆之后）时，
  看新版本路线整个工序家族被过滤空，页面只剩"已合并历史版本批次"提示条；
- 默认批次窗口不带路线过滤：全系统最新 500 个批次被无关路线挤满后，
  前身路线的历史批次掉出窗口，合并结果凭空清空；
- merged_routes 无条件返回：与是否真的合并进数据无关，
  空结果也显示"已合并历史版本批次"，误导排查方向。
"""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import Batch, NodeAssignment
from app.modules.production.schemas import (
    EdgeIn,
    FieldDefIn,
    NodeIn,
    ProductCreate,
    RouteCreate,
    RouteGraphIn,
)
from app.modules.production.service import route_service
from app.platform.identity.models import User
from tests.modules.production.conftest import rand_code
from tests.modules.production.test_analytics_api import _fill_fields
from tests.modules.production.test_computed_service import _make_batch, _make_route_ctx
from tests.modules.production.test_route_lineage import (
    _clone_published,
    _fill_g1,
    _node,
)

_T1 = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
_T2 = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)


async def _lineage_with_batches(db: AsyncSession) -> dict[str, object]:
    """A 发布并跑一单（G1 填值）→ 复刻发布 B 再跑一单；返回两代路线与批次。"""
    ctx = await _make_route_ctx(db, publish=True)
    ba = await _make_batch(db, ctx)
    await _fill_g1(db, ctx["route"].id, ba, {"A1": 10.0}, _T1)
    route_b = await _clone_published(db, ctx["route"].id, ctx["product"])
    bb = await _make_batch(db, {"product": ctx["product"], "route": route_b})
    await _fill_g1(db, route_b.id, bb, {"A1": 30.0}, _T2)
    return {"ctx": ctx, "route_b": route_b, "ba": ba, "bb": bb}


class TestStageSummaryScopeFixes:
    async def test_permission_extends_from_ancestor_assignment(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        """授权只加在前身路线 A 的节点上（克隆在前、分配在后），看 B 仍可见该工序。

        copy_route 只复制克隆那一刻的授权快照，之后加在 A 上的分配不会落到 B；
        权限锚定必须按节点家族判定（任一成员有授权即可见），否则版本升级后
        原工序负责人的汇总视图直接清空。
        """
        setup = await _lineage_with_batches(db_session)
        ctx, route_b, ba, bb = (
            setup["ctx"], setup["route_b"], setup["ba"], setup["bb"],
        )
        a_g1 = await _node(db_session, ctx["route"].id, "G1")
        db_session.add(
            NodeAssignment(
                user_id=test_user.id, node_id=a_g1.id,
                route_id=ctx["route"].id, assigned_by=test_user.id,
            )
        )
        await db_session.flush()

        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(route_b.id)},  # view_all 默认 false
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert {c["node_code"] for c in data["columns"]} == {"G1"}
        assert {r["batch_no"] for r in data["rows"]} == {ba.batch_no, bb.batch_no}

    async def test_window_scoped_to_lineage_routes(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """无关路线灌满全局 500 批次窗口后，B 视角的前身历史批次不丢失。"""
        setup = await _lineage_with_batches(db_session)
        route_b, ba, bb = setup["route_b"], setup["ba"], setup["bb"]

        # 另一产品灌 510 个更新的批次（仅占全局窗口，无任何执行记录）
        other = await route_service.create_product(
            db_session,
            ProductCreate(product_name=rand_code("占位产品"), product_code=rand_code("P")),
            user=None,
        )
        other_route = await route_service.create_route(
            db_session, RouteCreate(product_id=other.id, route_name=rand_code("占位路线")),
            user=None,
        )
        stamp = datetime.now(UTC) + timedelta(minutes=1)
        await db_session.execute(
            Batch.__table__.insert(),
            [
                {
                    "id": uuid.uuid4(), "batch_no": rand_code("W"),
                    "product_id": other.id, "route_id": other_route.id,
                    "status": "pending", "creation_type": "direct",
                    "created_at": stamp, "updated_at": stamp,
                }
                for _ in range(510)
            ],
        )
        await db_session.flush()

        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(route_b.id), "view_all": "true"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert {r["batch_no"] for r in data["rows"]} == {ba.batch_no, bb.batch_no}

    async def test_merged_routes_only_when_ancestor_rows_present(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """前身路线的批次一条都进不了汇总行时，不返回 merged_routes。"""
        ctx = await _make_route_ctx(db_session, publish=True)
        await _make_batch(db_session, ctx)  # A 的批次停在半路：无 completed 执行
        route_b = await _clone_published(db_session, ctx["route"].id, ctx["product"])
        bb = await _make_batch(db_session, {"product": ctx["product"], "route": route_b})
        await _fill_g1(db_session, route_b.id, bb, {"A1": 30.0}, _T2)

        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(route_b.id), "view_all": "true"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert {r["batch_no"] for r in data["rows"]} == {bb.batch_no}
        assert data["merged_routes"] == []

    async def test_no_visible_family_omits_merged_routes(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        """权限过滤后一个工序都不剩时，不配"已合并历史版本批次"提示。"""
        setup = await _lineage_with_batches(db_session)
        route_b = setup["route_b"]

        # 用户有授权但在完全无关的路线节点上（保证 allowed 非空但不覆盖 B 家族）
        unrelated = await _make_route_ctx(db_session)
        unrelated_g1 = await _node(db_session, unrelated["route"].id, "G1")
        db_session.add(
            NodeAssignment(
                user_id=test_user.id, node_id=unrelated_g1.id,
                route_id=unrelated["route"].id, assigned_by=test_user.id,
            )
        )
        await db_session.flush()

        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(route_b.id)},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["columns"] == []
        assert data["rows"] == []
        assert data["merged_routes"] == []

    async def test_field_trend_ignores_ancestor_field_retyped_non_numeric(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """前身数值字段在当前版本改成文本：旧值不进系列，也不算「已合并」。"""
        ctx = await _make_route_ctx(db_session, publish=True)
        ba = await _make_batch(db_session, ctx)
        # 前身批次只填 B1（当前版本会把 B1 改成文本），A1 留空
        await _fill_g1(db_session, ctx["route"].id, ba, {"B1": 5.0}, _T1)

        route_b = await route_service.copy_route(
            db_session, ctx["route"].id, rand_code("V"), user=None,
        )
        await route_service.save_graph(
            db_session, route_b.id,
            RouteGraphIn(
                nodes=[
                    NodeIn(
                        node_code="G1", name="工序一", stage_name="工段一", sort_order=1,
                        fields=[
                            FieldDefIn(field_key="A1", field_label="投料量", phase="end", data_type="numeric"),
                            FieldDefIn(field_key="B1", field_label="补料量", phase="end", data_type="text"),
                        ],
                    ),
                    NodeIn(
                        node_code="G2", name="工序二", stage_name="工段二", sort_order=2,
                        fields=[
                            FieldDefIn(field_key="A2", field_label="产出量", phase="end", data_type="numeric"),
                        ],
                    ),
                ],
                edges=[EdgeIn(from_node_code="G1", to_node_code="G2", is_batch_boundary=True)],
                computed_fields=[],
            ),
            user=None,
        )
        await route_service.publish_route(db_session, route_b.id, user=None)

        bb = await _make_batch(db_session, {"product": ctx["product"], "route": route_b})
        await _fill_g1(db_session, route_b.id, bb, {"A1": 30.0}, _T2)

        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={"route_id": str(route_b.id), "node_code": "G1"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert [s["field_key"] for s in data["series"]] == ["A1"]
        assert [p["batch_no"] for p in data["series"][0]["data_points"]] == [bb.batch_no]
        assert data["merged_routes"] == []

    async def test_field_trend_merged_routes_only_when_points_merged(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """字段趋势：前身路线无数据点时不显示已合并提示（同款误导口径）。"""
        ctx = await _make_route_ctx(db_session, publish=True)
        await _make_batch(db_session, ctx)  # A 的批次没有 G2 执行
        route_b = await _clone_published(db_session, ctx["route"].id, ctx["product"])
        b_g2 = await _node(db_session, route_b.id, "G2")
        bb = await _make_batch(db_session, {"product": ctx["product"], "route": route_b})
        await _fill_fields(db_session, bb.id, b_g2.id, {"A2": 7.0}, _T2)

        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={"route_id": str(route_b.id), "node_code": "G2"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        points = data["series"][0]["data_points"]
        assert [p["batch_no"] for p in points] == [bb.batch_no]
        assert data["merged_routes"] == []
