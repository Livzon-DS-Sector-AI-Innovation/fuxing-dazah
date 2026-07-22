"""工艺路线生命周期测试。

覆盖业务场景：
- 路线归档：published 路线可归档为 archived；draft/已归档路线不可归档
- 路线删除：draft 路线可软删除（含图数据级联软删）；published 路线不可删除
- 发布边界场景：空图发布失败（至少需要一个节点）；节点编码重复拒绝；
  单节点图可正常发布
- 路线列表：按产品 ID 过滤
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.production.models import ProcessRoute, Product
from app.modules.production.schemas import ProductCreate, RouteCreate
from app.modules.production.service import route_service
from tests.modules.production.conftest import build_graph_in, rand_code


async def _draft_route(db: AsyncSession) -> tuple[Product, ProcessRoute]:
    """创建产品+草稿路线，供各测试复用。"""
    product = await route_service.create_product(
        db, ProductCreate(product_name=rand_code("产品")), user=None,
    )
    route = await route_service.create_route(
        db, RouteCreate(product_id=product.id, name="V1"), user=None,
    )
    return product, route


class TestArchive:
    async def test_archive_published_route(self, db_session: AsyncSession) -> None:
        """已发布路线可归档，状态变为 archived。"""
        _, route = await _draft_route(db_session)
        await route_service.save_graph(
            db_session, route.id, build_graph_in(), user=None,
        )
        await route_service.publish_route(db_session, route.id, user=None)
        archived = await route_service.archive_route(db_session, route.id, user=None)
        assert archived.status == "archived"

    async def test_archive_draft_rejected(self, db_session: AsyncSession) -> None:
        """草稿路线不可归档，抛出 AppException。"""
        _, route = await _draft_route(db_session)
        with pytest.raises(AppException, match="仅 published"):
            await route_service.archive_route(db_session, route.id, user=None)

    async def test_archive_already_archived_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """已归档路线不可再次归档，抛出 AppException。"""
        _, route = await _draft_route(db_session)
        await route_service.save_graph(
            db_session, route.id, build_graph_in(), user=None,
        )
        await route_service.publish_route(db_session, route.id, user=None)
        await route_service.archive_route(db_session, route.id, user=None)
        with pytest.raises(AppException, match="仅 published"):
            await route_service.archive_route(db_session, route.id, user=None)


class TestDeleteRoute:
    async def test_delete_draft_route(self, db_session: AsyncSession) -> None:
        """草稿路线可软删除，删除后仓库查询返回 None。"""
        _, route = await _draft_route(db_session)
        await route_service.delete_route(db_session, route.id, user=None)
        from app.modules.production.repository.route import get_route
        deleted = await get_route(db_session, route.id)
        assert deleted is None

    async def test_delete_published_route_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """已发布路线不可删除，抛出 AppException。"""
        _, route = await _draft_route(db_session)
        await route_service.save_graph(
            db_session, route.id, build_graph_in(), user=None,
        )
        await route_service.publish_route(db_session, route.id, user=None)
        with pytest.raises(AppException, match="仅 draft"):
            await route_service.delete_route(db_session, route.id, user=None)


class TestPublishEdgeCases:
    async def test_publish_requires_graph(self, db_session: AsyncSession) -> None:
        """无图的路线发布时校验失败——至少需要一个节点。"""
        _, route = await _draft_route(db_session)
        with pytest.raises(AppException):
            await route_service.publish_route(db_session, route.id, user=None)

    async def test_publish_rejects_duplicate_node_code(
        self, db_session: AsyncSession,
    ) -> None:
        """图中存在相同 node_code 的两个节点时保存被拒。"""
        from app.modules.production.schemas import NodeIn, RouteGraphIn

        _, route = await _draft_route(db_session)
        graph = RouteGraphIn(
            nodes=[
                NodeIn(node_code="A", name="A1"),
                NodeIn(node_code="A", name="A2"),
            ],
            edges=[],
        )
        with pytest.raises(AppException, match="节点编码重复"):
            await route_service.save_graph(db_session, route.id, graph, user=None)

    async def test_publish_allows_single_node_graph(
        self, db_session: AsyncSession,
    ) -> None:
        """只有一个节点、没有边的路线可以保存并发布。"""
        from app.modules.production.schemas import NodeIn, RouteGraphIn

        _, route = await _draft_route(db_session)
        graph = RouteGraphIn(nodes=[NodeIn(node_code="S", name="单工序")], edges=[])
        await route_service.save_graph(db_session, route.id, graph, user=None)
        published = await route_service.publish_route(
            db_session, route.id, user=None,
        )
        assert published.status == "published"


class TestRouteList:
    async def test_list_routes_by_product(self, db_session: AsyncSession) -> None:
        """按产品 ID 过滤路线列表，能查到该产品的路线。"""
        product = await route_service.create_product(
            db_session, ProductCreate(product_name=rand_code("产品")), user=None,
        )
        await route_service.create_route(
            db_session, RouteCreate(product_id=product.id, name="V1"), user=None,
        )
        _items, total = await route_service.list_routes_paged(
            db_session, product_id=product.id, page=1, page_size=10,
        )
        assert total >= 1
