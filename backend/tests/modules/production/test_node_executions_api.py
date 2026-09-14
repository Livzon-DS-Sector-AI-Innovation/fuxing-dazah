"""工序视角跨批次执行记录查询测试。

覆盖业务场景：
- 跨批次列出某节点的全部执行记录，含批号和异常字段计数
- 按状态过滤（aborted 无结果）
- 查询不存在的节点抛出 NotFoundException
- 子批次字段谱系求和端点 children-aggregate
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.production.schemas import (
    BatchCreate,
    ComputedFieldIn,
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldValueIn,
)
from app.modules.production.service import batch_service, execution_service
from tests.modules.production.conftest import rand_code
from tests.modules.production.test_computed_service import (
    _add_execution,
    _link,
    _make_batch,
    _make_route_ctx,
)


async def _run_node_b(db: AsyncSession, ctx: dict[str, Any]) -> None:
    """辅助：新建批次并完成 node_b 的一次执行（temp=99 超限→1 个异常字段）。"""
    batch = await batch_service.create_batch(
        db,
        BatchCreate(
            batch_no=rand_code("B"),
            product_id=ctx["product"].id,
            route_id=ctx["route"].id,
        ),
        user=None,
    )
    ex_a = await execution_service.start_execution(
        db, batch.id, ExecutionStartIn(node_id=ctx["node_a"].id), user=None,
    )
    await execution_service.complete_execution(
        db, ex_a.id, ExecutionCompleteIn(), user=None,
    )
    ex_b = await execution_service.start_execution(
        db,
        batch.id,
        ExecutionStartIn(
            node_id=ctx["node_b"].id,
            field_values=[FieldValueIn(field_key="temp", value=99)],
        ),
        user=None,
    )
    await execution_service.complete_execution(
        db,
        ex_b.id,
        ExecutionCompleteIn(
            field_values=[FieldValueIn(field_key="yield_qty", value=10)],
        ),
        user=None,
    )


async def test_list_by_node_across_batches(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """node_b 上两次执行（两个批次），列表返回 2 条，均含批号和 1 个异常字段。"""
    await _run_node_b(db_session, published_route)
    await _run_node_b(db_session, published_route)
    items, total = await execution_service.list_node_executions(
        db_session, published_route["node_b"].id, None, 1, 20,
    )
    assert total == 2
    assert len(items) == 2
    assert all(i.batch_no for i in items)
    assert all(i.abnormal_count == 1 for i in items)


async def test_status_filter_and_unknown_node(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """按 aborted 状态过滤返回 0 条；不存在的节点查询抛出 NotFoundException。"""
    await _run_node_b(db_session, published_route)
    items, total = await execution_service.list_node_executions(
        db_session, published_route["node_b"].id, "aborted", 1, 20,
    )
    assert total == 0
    with pytest.raises(AppException):
        await execution_service.list_node_executions(
            db_session, uuid.uuid4(), None, 1, 20,
        )


class TestChildrenAggregate:
    async def test_sum_children(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """父批次 + 两个子批次（谱系 link），子批各有 completed 执行填 A2 → sum=12。"""
        ctx = await _make_route_ctx(db_session)
        parent = await _make_batch(db_session, ctx)
        children = [await _make_batch(db_session, ctx) for _ in range(2)]
        for child in children:
            await _link(db_session, parent.id, child.id)
        await _add_execution(
            db_session, children[0].id, ctx["node_g2"].id, field_values={"A2": 5},
        )
        await _add_execution(
            db_session, children[1].id, ctx["node_g2"].id, field_values={"A2": 7},
        )
        resp = await client.get(
            f"/api/v1/production/batches/{parent.id}/children-aggregate",
            params={"field_key": "A2", "node_code": "G2"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == {
            "field_key": "A2", "node_code": "G2", "sum": 12.0,
        }

    async def test_sum_children_computed(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """field_key=C1 不传 node_code → 对各子批 expand 后求和（3+4=7）。"""
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
        resp = await client.get(
            f"/api/v1/production/batches/{parent.id}/children-aggregate",
            params={"field_key": "C1"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == {
            "field_key": "C1", "node_code": None, "sum": 7.0,
        }

    async def test_no_children(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """无子批次 → sum 为 None。"""
        ctx = await _make_route_ctx(db_session)
        parent = await _make_batch(db_session, ctx)
        resp = await client.get(
            f"/api/v1/production/batches/{parent.id}/children-aggregate",
            params={"field_key": "A2", "node_code": "G2"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == {
            "field_key": "A2", "node_code": "G2", "sum": None,
        }


class TestAmendEndpoint:
    """PATCH /executions/{id} 修改工序填报数据：独立权限门禁与正常路径。"""

    async def _make_completed_execution(
        self, db: AsyncSession, ctx: dict[str, Any],
    ) -> uuid.UUID:
        """辅助：完成 A 后开始并结束 B，返回 B 的执行 id。"""
        batch = await batch_service.create_batch(
            db,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=ctx["product"].id,
                route_id=ctx["route"].id,
            ),
            user=None,
        )
        ex_a = await execution_service.start_execution(
            db, batch.id, ExecutionStartIn(node_id=ctx["node_a"].id), user=None,
        )
        await execution_service.complete_execution(
            db, ex_a.id, ExecutionCompleteIn(), user=None,
        )
        ex_b = await execution_service.start_execution(
            db,
            batch.id,
            ExecutionStartIn(
                node_id=ctx["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
            ),
            user=None,
        )
        await execution_service.complete_execution(
            db, ex_b.id, ExecutionCompleteIn(), user=None,
        )
        return ex_b.id

    async def test_patch_without_amend_permission_rejected(
        self, client: AsyncClient, db_session: AsyncSession,
        published_route: dict[str, Any],
    ) -> None:
        """client fixture 仅授予 read 权限 → 403。"""
        ex_id = await self._make_completed_execution(db_session, published_route)
        resp = await client.patch(
            f"/api/v1/production/executions/{ex_id}",
            json={"field_values": [{"field_key": "temp", "value": 26}]},
        )
        assert resp.status_code == 403, resp.text

    async def test_patch_with_amend_permission_succeeds(
        self, client: AsyncClient, db_session: AsyncSession,
        published_route: dict[str, Any],
    ) -> None:
        """HTTP 层与 service 层同时授予 amend 权限 → 200，字段就地更新。"""
        from unittest.mock import patch

        ex_id = await self._make_completed_execution(db_session, published_route)

        async def _grant_amend(_uid: str, _db: object) -> set[str]:
            return {"production:batch:read", "production:batch:amend"}

        with (
            patch(
                "app.platform.permission.deps.get_user_permissions",
                new=_grant_amend,
            ),
            patch.object(
                execution_service, "get_user_permissions", _grant_amend,
            ),
        ):
            resp = await client.patch(
                f"/api/v1/production/executions/{ex_id}",
                json={"field_values": [{"field_key": "temp", "value": 26}]},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["id"] == str(ex_id)
        # 响应与 start/complete 端点同构（field_values 由详情接口另行组装），
        # 字段更新从 DB 验证
        from app.modules.production import repository as prod_repo

        values = await prod_repo.get_field_values_by_executions(
            db_session, [ex_id],
        )
        row = next(v for v in values if v.field_key == "temp")
        assert row.value_numeric == 26
