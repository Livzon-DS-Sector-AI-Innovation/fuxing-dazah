"""字段趋势端点测试。

覆盖场景：
- 同路线同节点多批次完成，各填字段 → 按 filled_at 升序返回 batch_no/value
- 无数据 → []
- 字段不存在 → []
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


async def _fill_field(
    db: AsyncSession,
    batch_id: uuid.UUID,
    node_id: uuid.UUID,
    field_key: str,
    value: float,
    filled_at: datetime,
) -> None:
    """手造一次完成执行并填写字段，精确控制填写时间。"""
    ex = await _add_execution(db, batch_id, node_id, field_values={field_key: value})
    fv = (
        await db.execute(
            select(NodeFieldValue).where(NodeFieldValue.execution_id == ex.id)
        )
    ).scalar_one()
    fv.filled_at = filled_at
    await db.flush()


class TestFieldTrend:
    async def test_field_trend_returns_time_series(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """同路线同节点两个批次完成并填 A2 → 按 filled_at 升序返回 batch_no/value。"""
        ctx = await _make_route_ctx(db_session)
        b1 = await _make_batch(db_session, ctx)
        b2 = await _make_batch(db_session, ctx)
        # 故意乱序填写：b2 先填（08:00）、b1 后填（10:00），验证按填写时间升序
        await _fill_field(
            db_session, b2.id, ctx["node_g2"].id, "A2", 7.0,
            datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
        )
        await _fill_field(
            db_session, b1.id, ctx["node_g2"].id, "A2", 5.0,
            datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        )
        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={
                "route_id": str(ctx["route"].id),
                "node_code": "G2",
                "field_key": "A2",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert [d["batch_no"] for d in data] == [b2.batch_no, b1.batch_no]
        assert [d["value"] for d in data] == [7.0, 5.0]
        times = [datetime.fromisoformat(d["filled_at"]) for d in data]
        assert times == [
            datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
            datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        ]

    async def test_field_trend_empty(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """无任何执行 → []。"""
        ctx = await _make_route_ctx(db_session)
        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={
                "route_id": str(ctx["route"].id),
                "node_code": "G2",
                "field_key": "A2",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == []

    async def test_field_trend_unknown_field_returns_empty(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """字段不存在 → []。"""
        ctx = await _make_route_ctx(db_session)
        b1 = await _make_batch(db_session, ctx)
        await _fill_field(
            db_session, b1.id, ctx["node_g2"].id, "A2", 5.0,
            datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        )
        resp = await client.get(
            "/api/v1/production/analytics/field-trend",
            params={
                "route_id": str(ctx["route"].id),
                "node_code": "G2",
                "field_key": "NOPE",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == []


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
