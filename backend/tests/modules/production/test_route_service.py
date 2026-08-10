"""工艺路线与图编辑业务规则测试。

覆盖业务场景：
- 图编辑：route_name 产品内唯一；保存并读取完整图（节点/边/字段）；未知边引用拒绝；
  发布后图冻结不可再编辑；环形流转无起点拒绝发布；不可达节点拒绝发布；
  工序名称路线内唯一约束
- 路线复制：复制为新产品路线继承完整图结构
- 边界边约束：批次边界边不允许开启流水线模式

产品主数据的 CRUD 规则见 test_product_service.py。
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.production.models import ProcessRoute, Product
from app.modules.production.schemas import (
    EdgeIn,
    NodeIn,
    ProductCreate,
    RouteCreate,
    RouteGraphIn,
)
from app.modules.production.service import route_service
from tests.modules.production.conftest import build_graph_in, rand_code


async def _draft_route(db: AsyncSession) -> tuple[Product, ProcessRoute]:
    """辅助：创建产品+草稿路线。"""
    product = await route_service.create_product(
        db, ProductCreate(product_name="产品"), user=None,
    )
    route = await route_service.create_route(
        db, RouteCreate(product_id=product.id, route_name="V1"), user=None,
    )
    return product, route


class TestGraph:
    async def test_duplicate_route_name_rejected(self, db_session: AsyncSession) -> None:
        """同一产品下 route_name 唯一；不同产品可同名。"""
        product, route = await _draft_route(db_session)
        assert route.route_name == "V1"
        with pytest.raises(AppException):
            await route_service.create_route(
                db_session, RouteCreate(product_id=product.id, route_name="V1"), user=None,
            )
        other = await route_service.create_product(
            db_session, ProductCreate(product_name=f"其他-{uuid.uuid4().hex[:8]}"), user=None,
        )
        route2 = await route_service.create_route(
            db_session, RouteCreate(product_id=other.id, route_name="V1"), user=None,
        )
        assert route2.route_name == "V1"

    async def test_save_and_get_graph(self, db_session: AsyncSession) -> None:
        """保存标准测试图后读取，3 节点、3 边、B 节点含 2 个字段定义。"""
        _, route = await _draft_route(db_session)
        await route_service.save_graph(
            db_session, route.id, build_graph_in(), user=None,
        )
        graph = await route_service.get_graph(db_session, route.id)
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 3
        node_b = next(n for n in graph.nodes if n.node_code == "B")
        assert len(node_b.fields) == 2

    async def test_save_graph_rejects_unknown_edge_code(
        self, db_session: AsyncSession,
    ) -> None:
        """边引用了不存在的 node_code 时保存被拒。"""
        _, route = await _draft_route(db_session)
        graph = RouteGraphIn(
            nodes=[NodeIn(node_code="A", name="a", stage_name="工段A")],
            edges=[EdgeIn(from_node_code="A", to_node_code="X")],
        )
        with pytest.raises(AppException):
            await route_service.save_graph(db_session, route.id, graph, user=None)

    async def test_publish_freezes_graph(self, db_session: AsyncSession) -> None:
        """发布后图冻结，再次保存抛出 AppException。"""
        _, route = await _draft_route(db_session)
        await route_service.save_graph(
            db_session, route.id, build_graph_in(), user=None,
        )
        route = await route_service.publish_route(db_session, route.id, user=None)
        assert route.status == "published"
        with pytest.raises(AppException):
            await route_service.save_graph(
                db_session, route.id, build_graph_in(), user=None,
            )

    async def test_publish_rejects_cycle_without_start(
        self, db_session: AsyncSession,
    ) -> None:
        """A→B→A 环形图发布时因缺少起点被拒（所有节点都有入边）。"""
        _, route = await _draft_route(db_session)
        graph = RouteGraphIn(
            nodes=[NodeIn(node_code="A", name="a", stage_name="工段A"), NodeIn(node_code="B", name="b", stage_name="工段B")],
            edges=[
                EdgeIn(from_node_code="A", to_node_code="B"),
                EdgeIn(from_node_code="B", to_node_code="A"),
            ],
        )
        await route_service.save_graph(db_session, route.id, graph, user=None)
        with pytest.raises(AppException):
            await route_service.publish_route(db_session, route.id, user=None)

    async def test_publish_rejects_unreachable_node(
        self, db_session: AsyncSession,
    ) -> None:
        """存在孤立不可达节点 X 时发布被拒。"""
        _, route = await _draft_route(db_session)
        graph = RouteGraphIn(
            nodes=[
                NodeIn(node_code="A", name="a", stage_name="工段A"),
                NodeIn(node_code="B", name="b", stage_name="工段B"),
                NodeIn(node_code="X", name="孤立", stage_name="工段X"),
            ],
            edges=[EdgeIn(from_node_code="A", to_node_code="B")],
        )
        await route_service.save_graph(db_session, route.id, graph, user=None)
        with pytest.raises(AppException):
            await route_service.publish_route(db_session, route.id, user=None)

    async def test_copy_route_copies_graph(self, db_session: AsyncSession) -> None:
        """从已发布路线复制为新路线，继承完整的 3 节点 3 边图结构。"""
        _, route = await _draft_route(db_session)
        await route_service.save_graph(
            db_session, route.id, build_graph_in(), user=None,
        )
        await route_service.publish_route(db_session, route.id, user=None)
        copy = await route_service.copy_route(db_session, route.id, "复制路线", user=None)
        assert copy.status == "draft"
        assert copy.route_name == "复制路线"
        graph = await route_service.get_graph(db_session, copy.id)
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 3

    async def test_batch_boundary_with_allow_overlap_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """批次边界边不允许同时开启流水线模式（allow_overlap）。"""
        product = await route_service.create_product(
            db_session,
            ProductCreate(product_name="测试", product_code=rand_code("P")),
            user=None,
        )
        route = await route_service.create_route(
            db_session, RouteCreate(product_id=product.id, route_name="V1"), user=None,
        )
        graph = build_graph_in()
        graph.edges[0].allow_overlap = True
        with pytest.raises(AppException, match="批次边界边不允许"):
            await route_service.save_graph(db_session, route.id, graph, user=None)

    async def test_duplicate_node_name_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """同一路线内工序名称 name 不可重复。"""
        _, route = await _draft_route(db_session)
        graph = RouteGraphIn(
            nodes=[
                NodeIn(node_code="A", name="发酵", stage_name="工段A"),
                NodeIn(node_code="B", name="发酵", stage_name="工段A"),
            ],
        )
        with pytest.raises(AppException, match="工序名称重复"):
            await route_service.save_graph(db_session, route.id, graph, user=None)

    async def test_same_name_across_routes_allowed(
        self, db_session: AsyncSession,
    ) -> None:
        """不同路线内工序名称 name 可以相同。"""
        _, route1 = await _draft_route(db_session)
        p2 = await route_service.create_product(
            db_session, ProductCreate(product_name=rand_code("P")), user=None,
        )
        route2 = await route_service.create_route(
            db_session, RouteCreate(product_id=p2.id, route_name="V1"), user=None,
        )
        graph = RouteGraphIn(nodes=[NodeIn(node_code="A", name="发酵", stage_name="工段A")])
        await route_service.save_graph(db_session, route1.id, graph, user=None)
        await route_service.save_graph(db_session, route2.id, graph, user=None)
        g1 = await route_service.get_graph(db_session, route1.id)
        g2 = await route_service.get_graph(db_session, route2.id)
        assert g1.nodes[0].name == g2.nodes[0].name == "发酵"
