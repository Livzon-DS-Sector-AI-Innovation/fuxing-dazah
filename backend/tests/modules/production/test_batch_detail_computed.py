"""批次详情返回计算字段汇总区 + 当前用户可操作标志。

覆盖业务场景：
- 详情响应带 computed_fields（C1=30.0）
- 引用字段未填时 value 为 None
- can_backfill / can_complete 按批次归属判定（工段负责人可见补录/完成批次）
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import NodeAssignment, StageAssignment
from app.modules.production.schemas import ComputedFieldIn
from app.modules.production.service import batch_service
from app.platform.identity.models import User
from tests.modules.production.conftest import rand_code
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


async def _no_submit(user_id: str, db: object) -> set[str]:
    """batch_service 名字空间的权限读取：无任何权限（非 submit 持有者）。"""
    return set()


async def _grant_submit(user_id: str, db: object) -> set[str]:
    """batch_service 名字空间的权限读取：batch:submit 管理员通行证。"""
    return {"production:batch:submit"}


class TestBatchDetailOperateFlags:
    """can_backfill（每执行）/ can_complete（批次级）：与 backfill /
    complete_batch 的 service 层授权同口径，前端据此显示按钮。

    权限读取在 batch_service 名字空间（conftest 的 client 只 patch 了
    deps 层），各用例显式 monkeypatch 控制 submit 权限。
    """

    async def _detail(self, client: AsyncClient, batch_id: str) -> dict[str, Any]:
        resp = await client.get(f"/api/v1/production/batches/{batch_id}")
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]

    async def test_stage_owner_ownerless_and_own_batch(
        self, client: AsyncClient, db_session: AsyncSession,
        test_user: User, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 工段负责人：无主批次（共享可操作）与自己归属的批次都能补录/完成
        monkeypatch.setattr(batch_service, "get_user_permissions", _no_submit)
        ctx = await _make_route_ctx(db_session)
        db_session.add(StageAssignment(
            user_id=test_user.id, route_id=ctx["route"].id, stage_name="工段一",
        ))
        batches = []
        ownerless = await _make_batch(db_session, ctx)
        await _add_execution(db_session, ownerless.id, ctx["node_g1"].id)
        batches.append(ownerless)
        own = await _make_batch(db_session, ctx)
        own.owner_user_id = test_user.id
        await _add_execution(db_session, own.id, ctx["node_g1"].id)
        batches.append(own)
        await db_session.flush()

        for batch in batches:
            data = await self._detail(client, str(batch.id))
            assert data["can_complete"] is True
            assert [e["can_backfill"] for e in data["executions"]] == [True]

    async def test_stage_owner_others_batch_readonly(
        self, client: AsyncClient, db_session: AsyncSession,
        test_user: User, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 他人归属批次：工段身份不豁免（同工段多负责人各自认领批次）
        monkeypatch.setattr(batch_service, "get_user_permissions", _no_submit)
        ctx = await _make_route_ctx(db_session)
        other = User(name="其他负责人", employee_no=rand_code("U"))
        db_session.add(other)
        batch = await _make_batch(db_session, ctx)
        batch.owner_user_id = other.id
        await _add_execution(db_session, batch.id, ctx["node_g1"].id)
        db_session.add(StageAssignment(
            user_id=test_user.id, route_id=ctx["route"].id, stage_name="工段一",
        ))
        await db_session.flush()

        data = await self._detail(client, str(batch.id))
        assert data["can_complete"] is False
        assert [e["can_backfill"] for e in data["executions"]] == [False]

    async def test_node_owner_exempts_others_batch(
        self, client: AsyncClient, db_session: AsyncSession,
        test_user: User, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 工序负责人（NodeAssignment）：唯一能豁免他人批次归属隔离的身份
        monkeypatch.setattr(batch_service, "get_user_permissions", _no_submit)
        ctx = await _make_route_ctx(db_session)
        other = User(name="其他负责人", employee_no=rand_code("U"))
        db_session.add(other)
        batch = await _make_batch(db_session, ctx)
        batch.owner_user_id = other.id
        await _add_execution(db_session, batch.id, ctx["node_g1"].id)
        db_session.add(NodeAssignment(
            user_id=test_user.id, node_id=ctx["node_g1"].id,
            route_id=ctx["route"].id, assigned_by=test_user.id,
        ))
        await db_session.flush()

        data = await self._detail(client, str(batch.id))
        assert data["can_complete"] is True
        assert [e["can_backfill"] for e in data["executions"]] == [True]

    async def test_execution_owner_single_execution(
        self, client: AsyncClient, db_session: AsyncSession,
        test_user: User, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 单次执行负责人：可补录自己那一次执行，但完成批次不放行
        monkeypatch.setattr(batch_service, "get_user_permissions", _no_submit)
        ctx = await _make_route_ctx(db_session)
        other = User(name="其他负责人", employee_no=rand_code("U"))
        db_session.add(other)
        batch = await _make_batch(db_session, ctx)
        batch.owner_user_id = other.id
        ex = await _add_execution(db_session, batch.id, ctx["node_g1"].id)
        ex.owner_id = test_user.id
        await db_session.flush()

        data = await self._detail(client, str(batch.id))
        assert data["can_complete"] is False
        assert [e["can_backfill"] for e in data["executions"]] == [True]

    async def test_submit_permission_grants_all(
        self, client: AsyncClient, db_session: AsyncSession,
        test_user: User, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # batch:submit 管理员通行证：无任何工段/工序身份也全 True
        monkeypatch.setattr(batch_service, "get_user_permissions", _grant_submit)
        ctx = await _make_route_ctx(db_session)
        other = User(name="其他负责人", employee_no=rand_code("U"))
        db_session.add(other)
        batch = await _make_batch(db_session, ctx)
        batch.owner_user_id = other.id
        await _add_execution(db_session, batch.id, ctx["node_g1"].id)
        await db_session.flush()

        data = await self._detail(client, str(batch.id))
        assert data["can_complete"] is True
        assert [e["can_backfill"] for e in data["executions"]] == [True]

    async def test_completed_batch_blocks_backfill(
        self, client: AsyncClient, db_session: AsyncSession,
        test_user: User, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 批次已结束：对所有人（含 submit 持有者）禁止补录，完成按钮也消失
        monkeypatch.setattr(batch_service, "get_user_permissions", _grant_submit)
        ctx = await _make_route_ctx(db_session)
        batch = await _make_batch(db_session, ctx)
        await _add_execution(db_session, batch.id, ctx["node_g1"].id)
        batch.status = "completed"
        await db_session.flush()

        data = await self._detail(client, str(batch.id))
        assert data["can_complete"] is False
        assert [e["can_backfill"] for e in data["executions"]] == [False]

    async def test_in_progress_execution_not_backfillable(
        self, client: AsyncClient, db_session: AsyncSession,
        test_user: User, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 进行中的执行不能补录（仅已结束的工序可补录）
        monkeypatch.setattr(batch_service, "get_user_permissions", _no_submit)
        ctx = await _make_route_ctx(db_session)
        batch = await _make_batch(db_session, ctx)
        batch.owner_user_id = test_user.id
        await _add_execution(
            db_session, batch.id, ctx["node_g1"].id, status="in_progress",
        )
        db_session.add(StageAssignment(
            user_id=test_user.id, route_id=ctx["route"].id, stage_name="工段一",
        ))
        await db_session.flush()

        data = await self._detail(client, str(batch.id))
        assert [e["can_backfill"] for e in data["executions"]] == [False]
