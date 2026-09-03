"""字段趋势端点测试。

覆盖场景：
- 节点下多个数值字段分别成序列，字段内按 filled_at 升序
- 某批某字段未填 → 该字段序列少一个点（其余字段不受影响）
- 字段定义存在但从未填报 / 无执行 / 节点不存在 → 不进序列
- 回流：同批同节点多条 completed 执行 → 取 finished_at 最新一次的值
- 非数值字段即使有值也不进序列
"""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.modules.production.models import NodeFieldValue, StageAssignment
from app.modules.production.schemas import (
    ComputedFieldIn,
    FieldDefIn,
    NodeIn,
    ProductCreate,
    RouteCreate,
    RouteGraphIn,
)
from app.modules.production.service import route_service
from app.platform.identity.models import User
from tests.modules.production.conftest import rand_code
from tests.modules.production.test_computed_service import (
    _add_execution,
    _link,
    _make_batch,
    _make_route_ctx,
)


async def _fill_fields(
    db: AsyncSession,
    batch_id: uuid.UUID,
    node_id: uuid.UUID,
    field_values: dict[str, float],
    filled_at: datetime,
    *,
    seq: int = 1,
    finished_at: datetime | None = None,
) -> None:
    """手造一次完成执行并填写多个字段，精确控制执行完成时间与填写时间。"""
    ex = await _add_execution(
        db, batch_id, node_id,
        seq=seq, finished_at=finished_at, field_values=field_values,
    )
    rows = (
        await db.execute(
            select(NodeFieldValue).where(NodeFieldValue.execution_id == ex.id)
        )
    ).scalars().all()
    for fv in rows:
        fv.filled_at = filled_at
    await db.flush()
    return ex


class TestFieldTrend:
    async def test_field_trend_multi_field_series(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """节点下两个数值字段分别成序列：A1 两批都有、B1 只有一批（缺失即少点）。"""
        ctx = await _make_route_ctx(db_session)
        b1 = await _make_batch(db_session, ctx)
        b2 = await _make_batch(db_session, ctx)
        # 故意乱序填写：b2 先填（08:00 只填 A1）、b1 后填（10:00 填 A1+B1）
        await _fill_fields(
            db_session, b2.id, ctx["node_g1"].id, {"A1": 7.0},
            datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
        )
        await _fill_fields(
            db_session, b1.id, ctx["node_g1"].id, {"A1": 5.0, "B1": 3.0},
            datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        )
        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={"route_id": str(ctx["route"].id), "node_code": "G1"},
        )
        assert resp.status_code == 200, resp.text
        series = resp.json()["data"]["series"]
        # 序列按字段定义顺序（A1 在前、B1 在后）
        assert [s["field_key"] for s in series] == ["A1", "B1"]
        assert [s["field_label"] for s in series] == ["投料量", "补料量"]
        a1, b1_series = series
        # A1：b2（08:00 先填）在前、b1 在后；B1 只有 b1 一个点
        assert [p["batch_no"] for p in a1["data_points"]] == [b2.batch_no, b1.batch_no]
        assert [p["value"] for p in a1["data_points"]] == [7.0, 5.0]
        assert [p["batch_no"] for p in b1_series["data_points"]] == [b1.batch_no]
        assert [p["value"] for p in b1_series["data_points"]] == [3.0]
        times = [datetime.fromisoformat(p["filled_at"]) for p in a1["data_points"]]
        assert times == [
            datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
            datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        ]

    async def test_field_trend_fields_without_data_excluded(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """字段定义存在但从未填报 → 不进序列（全空字段不出现在图例里）。"""
        ctx = await _make_route_ctx(db_session)
        b1 = await _make_batch(db_session, ctx)
        await _fill_fields(
            db_session, b1.id, ctx["node_g1"].id, {"A1": 5.0},
            datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        )
        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={"route_id": str(ctx["route"].id), "node_code": "G1"},
        )
        assert resp.status_code == 200, resp.text
        assert [s["field_key"] for s in resp.json()["data"]["series"]] == ["A1"]

    async def test_field_trend_empty(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """无任何执行 → series 为空。"""
        ctx = await _make_route_ctx(db_session)
        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={"route_id": str(ctx["route"].id), "node_code": "G1"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["series"] == []

    async def test_field_trend_unknown_node_returns_empty(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """节点不存在 → series 为空。"""
        ctx = await _make_route_ctx(db_session)
        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={"route_id": str(ctx["route"].id), "node_code": "NOPE"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["series"] == []

    async def test_field_trend_rework_uses_latest_completed_execution(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """回流：同批同节点两条 completed 执行 → 取 finished_at 最新一次的字段值。"""
        ctx = await _make_route_ctx(db_session)
        b1 = await _make_batch(db_session, ctx)
        t_older = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
        t_latest = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)
        # 先插最新一次（seq=2）、后插旧一次（seq=1），与工段汇总局域一致
        await _fill_fields(
            db_session, b1.id, ctx["node_g1"].id, {"A1": 20.0, "B1": 2.0},
            datetime(2026, 8, 2, 9, 0, tzinfo=UTC), seq=2, finished_at=t_latest,
        )
        await _fill_fields(
            db_session, b1.id, ctx["node_g1"].id, {"A1": 10.0, "B1": 1.0},
            datetime(2026, 8, 1, 9, 0, tzinfo=UTC), seq=1, finished_at=t_older,
        )
        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={"route_id": str(ctx["route"].id), "node_code": "G1"},
        )
        assert resp.status_code == 200, resp.text
        series = {s["field_key"]: s for s in resp.json()["data"]["series"]}
        assert [p["value"] for p in series["A1"]["data_points"]] == [20.0]
        assert [p["value"] for p in series["B1"]["data_points"]] == [2.0]

    async def test_field_trend_excludes_non_numeric_fields(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """文本字段即使有值也不进趋势序列。"""
        product = await route_service.create_product(
            db_session,
            ProductCreate(product_name=rand_code("文本产品"), product_code=rand_code("P")),
            user=None,
        )
        route = await route_service.create_route(
            db_session, RouteCreate(product_id=product.id, route_name="文本V1"), user=None,
        )
        graph = RouteGraphIn(
            nodes=[
                NodeIn(
                    node_code="G1", name="工序一", stage_name="工段一", sort_order=1,
                    fields=[
                        FieldDefIn(
                            field_key="A1", field_label="投料量", phase="end",
                            data_type="numeric",
                        ),
                        FieldDefIn(
                            field_key="T1", field_label="备注", phase="end",
                            data_type="text",
                        ),
                    ],
                ),
            ],
            edges=[],
            computed_fields=[],
        )
        await route_service.save_graph(db_session, route.id, graph, user=None)
        node = (await route_service.get_graph(db_session, route.id)).nodes[0]
        batch = await _make_batch(
            db_session, {"product": product, "route": route},
        )
        ex = await _fill_fields(
            db_session, batch.id, node.id, {"A1": 5.0},
            datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        )
        db_session.add(
            NodeFieldValue(
                execution_id=ex.id,
                field_def_id=uuid.uuid4(),
                field_key="T1",
                field_label="备注",
                phase="end",
                value_text="正常",
                filled_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
            )
        )
        await db_session.flush()
        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={"route_id": str(route.id), "node_code": "G1"},
        )
        assert resp.status_code == 200, resp.text
        assert [s["field_key"] for s in resp.json()["data"]["series"]] == ["A1"]


class TestStageSummary:
    async def test_stage_summary_flat_matrix(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """两节点两批次完成 → rows 两条，columns 覆盖两节点全部字段（G1 列在前）。"""
        ctx = await _make_route_ctx(db_session, publish=True)
        b1 = await _make_batch(db_session, ctx)
        b2 = await _make_batch(db_session, ctx)
        for batch in (b1, b2):
            await _add_execution(
                db_session, batch.id, ctx["node_g1"].id,
                field_values={"A1": 10, "B1": 20},
            )
            await _add_execution(
                db_session, batch.id, ctx["node_g2"].id, field_values={"A2": 100},
            )
        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(ctx["route"].id), "view_all": "true"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert [c["node_code"] for c in data["columns"]] == ["G1", "G1", "G2"]
        assert {c["field_key"] for c in data["columns"]} == {"A1", "B1", "A2"}
        assert all(c["kind"] == "field" for c in data["columns"])
        assert len(data["rows"]) == 2
        by_no = {r["batch_no"]: r for r in data["rows"]}
        assert by_no[b1.batch_no]["values"][f"{ctx['node_g1'].id}.A1"] == 10.0
        assert by_no[b2.batch_no]["values"][f"{ctx['node_g2'].id}.A2"] == 100.0

    async def test_stage_summary_stage_filter(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """stage_name=工段一 → 只含该工段节点列。"""
        ctx = await _make_route_ctx(db_session, publish=True)
        b1 = await _make_batch(db_session, ctx)
        await _add_execution(
            db_session, b1.id, ctx["node_g1"].id, field_values={"A1": 5},
        )
        await _add_execution(
            db_session, b1.id, ctx["node_g2"].id, field_values={"A2": 50},
        )
        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={
                "route_id": str(ctx["route"].id),
                "stage_name": "工段一",
                "view_all": "true",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert [c["node_code"] for c in data["columns"]] == ["G1", "G1"]
        assert {c["field_key"] for c in data["columns"]} == {"A1", "B1"}
        assert data["rows"][0]["values"] == {f"{ctx['node_g1'].id}.A1": 5.0}

    async def test_stage_summary_includes_computed(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """计算字段 C1 出现在 columns（kind=computed）与 rows[].computed。"""
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
        b1 = await _make_batch(db_session, ctx)
        await _add_execution(
            db_session, b1.id, ctx["node_g1"].id, field_values={"A1": 10, "B1": 20},
        )
        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(ctx["route"].id), "view_all": "true"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        computed_cols = [c for c in data["columns"] if c["kind"] == "computed"]
        assert [c["field_key"] for c in computed_cols] == ["C1"]
        assert computed_cols[0]["node_code"] == "G1"
        assert data["rows"][0]["computed"] == {f"{ctx['node_g1'].id}.C1": 30.0}

    async def test_stage_summary_rework_uses_latest_completed_execution(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """回流：同批同节点两条 completed 执行 → 矩阵与计算字段均取 finished_at 最新值。"""
        ctx = await _make_route_ctx(
            db_session,
            publish=True,
            computed_fields=[
                ComputedFieldIn(
                    node_code="G1", field_key="C1", field_label="投料",
                    formula="{G1.A1}",
                ),
            ],
        )
        b1 = await _make_batch(db_session, ctx)
        t_older = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
        t_latest = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)
        # 先插最新一次（seq=2），后插旧一次（seq=1）：旧实现按行序覆盖会得到 10
        await _add_execution(
            db_session, b1.id, ctx["node_g1"].id, seq=2, finished_at=t_latest,
            field_values={"A1": 20},
        )
        await _add_execution(
            db_session, b1.id, ctx["node_g1"].id, seq=1, finished_at=t_older,
            field_values={"A1": 10},
        )
        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(ctx["route"].id), "view_all": "true"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        row = data["rows"][0]
        assert row["values"][f"{ctx['node_g1'].id}.A1"] == 20.0
        # 计算字段按"最后一次 completed 执行"取数，同页应一致
        assert row["computed"][f"{ctx['node_g1'].id}.C1"] == 20.0

    async def test_stage_summary_permission_scope(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        """默认只返回用户负责工段的数据（含计算字段不泄漏）；view_all=true 返回全部。"""
        ctx = await _make_route_ctx(
            db_session,
            publish=True,
            computed_fields=[
                ComputedFieldIn(
                    node_code="G2", field_key="C2", field_label="合计",
                    formula="{G2.A2}",
                ),
            ],
        )
        b1 = await _make_batch(db_session, ctx)
        await _add_execution(
            db_session, b1.id, ctx["node_g1"].id, field_values={"A1": 5},
        )
        await _add_execution(
            db_session, b1.id, ctx["node_g2"].id, field_values={"A2": 50},
        )
        db_session.add(
            StageAssignment(
                user_id=test_user.id, stage_name="工段一", route_id=ctx["route"].id,
            )
        )
        await db_session.flush()

        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(ctx["route"].id)},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert [c["node_code"] for c in data["columns"]] == ["G1", "G1"]
        assert all(c["kind"] == "field" for c in data["columns"])
        assert data["rows"][0]["values"] == {f"{ctx['node_g1'].id}.A1": 5.0}
        # 用户只负责工段一：G2 展示的计算字段 C2 不得泄漏到 computed
        assert data["rows"][0]["computed"] == {}

        resp_all = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(ctx["route"].id), "view_all": "true"},
        )
        assert resp_all.status_code == 200, resp_all.text
        data_all = resp_all.json()["data"]
        assert {c["node_code"] for c in data_all["columns"]} == {"G1", "G2"}
        assert data_all["rows"][0]["values"][f"{ctx['node_g2'].id}.A2"] == 50.0
        assert data_all["rows"][0]["computed"] == {f"{ctx['node_g2'].id}.C2": 50.0}

    async def test_stage_summary_node_sort_order(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """列按节点 sort_order 排序，而非 node_code 字典序（G2 在前、G1 在后）。"""
        product = await route_service.create_product(
            db_session,
            ProductCreate(product_name=rand_code("排序产品"), product_code=rand_code("P")),
            user=None,
        )
        route = await route_service.create_route(
            db_session, RouteCreate(product_id=product.id, route_name="排序V1"), user=None,
        )
        graph = RouteGraphIn(
            nodes=[
                NodeIn(
                    node_code="G2", name="前工序", stage_name="发酵", sort_order=1,
                    fields=[
                        FieldDefIn(
                            field_key="A2", field_label="量", phase="end",
                            data_type="numeric",
                        ),
                    ],
                ),
                NodeIn(
                    node_code="G1", name="后工序", stage_name="发酵", sort_order=2,
                    fields=[
                        FieldDefIn(
                            field_key="A1", field_label="量", phase="end",
                            data_type="numeric",
                        ),
                    ],
                ),
            ],
            edges=[],
            computed_fields=[],
        )
        await route_service.save_graph(db_session, route.id, graph, user=None)
        # 汇总只覆盖非草稿路线，直接置 published（空边图走 publish 校验会失败）
        route.status = "published"
        await db_session.flush()

        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(route.id), "view_all": "true"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert [c["node_code"] for c in data["columns"]] == ["G2", "G1"]
        assert data["rows"] == []

    async def test_stage_summary_excludes_draft_route(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """草稿路线不在汇总范围（无生产数据），即使 view_all=true 也返回空矩阵。"""
        ctx = await _make_route_ctx(db_session)
        b1 = await _make_batch(db_session, ctx)
        await _add_execution(
            db_session, b1.id, ctx["node_g1"].id, field_values={"A1": 5},
        )
        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={"route_id": str(ctx["route"].id), "view_all": "true"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["columns"] == []
        assert data["rows"] == []

    async def test_stage_summary_date_range_includes_descendants(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """日期范围取"首工序开始时间"落在范围内的批次 + 其全部后序批次。

        b1 在范围内；b2 是 b1 的后序（开始日期超出范围）；b3 超出范围且无谱系。
        → 只返回 b1、b2，不含 b3。
        """
        ctx = await _make_route_ctx(db_session, publish=True)
        b1 = await _make_batch(db_session, ctx)
        b2 = await _make_batch(db_session, ctx)
        b3 = await _make_batch(db_session, ctx)
        b1.first_started_at = datetime(2026, 8, 1, 9, 0, tzinfo=APP_TZ)
        b2.first_started_at = datetime(2026, 8, 10, 9, 0, tzinfo=APP_TZ)
        b3.first_started_at = datetime(2026, 8, 20, 9, 0, tzinfo=APP_TZ)
        await _link(db_session, b1.id, b2.id)
        for batch in (b1, b2, b3):
            await _add_execution(
                db_session, batch.id, ctx["node_g1"].id, field_values={"A1": 5},
            )
        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={
                "route_id": str(ctx["route"].id),
                "view_all": "true",
                "start_date": "2026-08-01",
                "end_date": "2026-08-05",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert {r["batch_no"] for r in data["rows"]} == {b1.batch_no, b2.batch_no}

    async def test_stage_summary_rejects_inverted_date_range(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """start_date 晚于 end_date → 400，而不是静默返回空矩阵。"""
        ctx = await _make_route_ctx(db_session, publish=True)
        resp = await client.get(
            "/api/v1/production/analytics/stage-summary",
            params={
                "route_id": str(ctx["route"].id),
                "view_all": "true",
                "start_date": "2026-08-20",
                "end_date": "2026-08-01",
            },
        )
        assert resp.status_code == 400, resp.text
