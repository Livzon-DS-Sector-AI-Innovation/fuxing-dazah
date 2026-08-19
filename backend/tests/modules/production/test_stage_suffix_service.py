"""工段批次尾缀配置测试。

覆盖：未分配工段返回空、未配置返回空尾缀、设置与软删复活 upsert、非负责人被拒。
"""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException
from app.modules.production.repository import assignment as repo
from app.modules.production.schemas import ProductCreate, RouteCreate
from app.modules.production.service import assignment_service, route_service


class TestStageSuffix:
    @pytest.fixture(autouse=True)
    def _mock_perms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """mock 权限码查询：避免 Redis 连接跨测试事件循环报 Event loop is closed。"""
        from app.modules.production.service import assignment_service as as_

        async def fake(user_id: str, db: AsyncSession) -> set[str]:
            return set()

        monkeypatch.setattr(as_, "get_user_permissions", fake)

    @pytest.fixture
    async def draft_route(self, db_session: AsyncSession) -> Any:
        """未发布的草稿路线。"""
        code = uuid.uuid4().hex[:8]
        product = await route_service.create_product(
            db_session,
            ProductCreate(product_name=f"测试产品-{code}", product_code=f"P-{code}"),
            user=None,
        )
        return await route_service.create_route(
            db_session, RouteCreate(product_id=product.id, route_name="工艺草稿"), user=None
        )

    async def test_list_empty_without_assignments(
        self, db_session: AsyncSession,
    ) -> None:
        """未分配任何工段的用户，尾缀列表为空。"""
        result = await assignment_service.list_my_stage_suffixes(
            db_session, uuid.uuid4(),
        )
        assert result == []

    async def test_list_unconfigured_returns_empty_suffix(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """已分配工段但未配置尾缀时，返回空尾缀。"""
        user_id = uuid.uuid4()
        route_id = published_route["route"].id
        await assignment_service.create_stage_assignment(
            db_session, user_id=user_id, stage_name="发酵",
            route_id=route_id, created_by=user_id,
        )
        result = await assignment_service.list_my_stage_suffixes(db_session, user_id)
        assert len(result) == 1
        assert result[0].route_id == route_id
        assert result[0].stage_name == "发酵"
        assert result[0].suffix == ""

    async def test_set_and_revive_after_soft_delete(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """软删后重新设置走复活，不新建（避免增删增触发唯一索引）。"""
        user_id = uuid.uuid4()
        route_id = published_route["route"].id
        await assignment_service.create_stage_assignment(
            db_session, user_id=user_id, stage_name="发酵",
            route_id=route_id, created_by=user_id,
        )
        out = await assignment_service.set_stage_suffix(
            db_session, user_id=user_id, route_id=route_id,
            stage_name="发酵", suffix="-F1",
        )
        assert out.suffix == "-F1"

        rows = await repo.list_stage_suffixes(db_session, [route_id])
        assert len(rows) == 1
        rows[0].is_deleted = True
        await db_session.flush()
        assert await repo.list_stage_suffixes(db_session, [route_id]) == []

        out2 = await assignment_service.set_stage_suffix(
            db_session, user_id=user_id, route_id=route_id,
            stage_name="发酵", suffix="-F2",
        )
        assert out2.suffix == "-F2"
        rows = await repo.list_stage_suffixes(db_session, [route_id])
        assert len(rows) == 1
        assert rows[0].suffix == "-F2"

    async def test_list_excludes_non_published_routes(
        self, db_session: AsyncSession, draft_route: Any,
    ) -> None:
        """草稿路线的工段分配不出现在尾缀列表。"""
        user_id = uuid.uuid4()
        await assignment_service.create_stage_assignment(
            db_session, user_id=user_id, stage_name="发酵",
            route_id=draft_route.id, created_by=user_id,
        )
        assert await assignment_service.list_my_stage_suffixes(db_session, user_id) == []

    async def test_set_rejected_on_non_published_route(
        self, db_session: AsyncSession, draft_route: Any,
    ) -> None:
        """草稿路线上的工段负责人设置尾缀被拒。"""
        user_id = uuid.uuid4()
        await assignment_service.create_stage_assignment(
            db_session, user_id=user_id, stage_name="发酵",
            route_id=draft_route.id, created_by=user_id,
        )
        with pytest.raises(ForbiddenException):
            await assignment_service.set_stage_suffix(
                db_session, user_id=user_id, route_id=draft_route.id,
                stage_name="发酵", suffix="-F1",
            )

    async def test_non_owner_forbidden(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """非该工段负责人设置尾缀被拒。"""
        owner_id = uuid.uuid4()
        route_id = published_route["route"].id
        await assignment_service.create_stage_assignment(
            db_session, user_id=owner_id, stage_name="发酵",
            route_id=route_id, created_by=owner_id,
        )
        with pytest.raises(ForbiddenException):
            await assignment_service.set_stage_suffix(
                db_session, user_id=uuid.uuid4(), route_id=route_id,
                stage_name="发酵", suffix="-X",
            )
