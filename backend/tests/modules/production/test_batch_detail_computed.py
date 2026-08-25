"""批次详情返回计算字段汇总区。

覆盖业务场景：
- 详情响应带 computed_fields（C1=30.0）
- 引用字段未填时 value 为 None
"""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.schemas import ComputedFieldIn
from tests.modules.production.test_computed_service import (
    _add_execution,
    _make_batch,
    _make_route_ctx,
)


async def _detail_computed_fields(client: AsyncClient, batch_id: str) -> list[dict[str, Any]]:
    resp = await client.get(f"/api/v1/production/batches/{batch_id}")
    assert resp.status_code == 200, resp.text
    data: list[dict[str, Any]] = resp.json()["data"]["computed_fields"]
    return data


class TestBatchDetailComputed:
    async def test_detail_includes_computed_fields(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        # 构造路线：G1 有 A1/B1 numeric 字段 + 计算字段 C1={G1.A1}+{G1.B1}
        # 构造批次完成 G1（A1=10, B1=20）
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

        computed = await _detail_computed_fields(client, str(batch.id))
        assert computed == [
            {"field_key": "C1", "field_label": "总投料", "unit": None, "value": 30.0},
        ]

    async def test_detail_computed_none_when_missing(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        # A1 未填 → value 为 None
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

        computed = await _detail_computed_fields(client, str(batch.id))
        assert computed == [
            {"field_key": "C1", "field_label": "总投料", "unit": None, "value": None},
        ]
