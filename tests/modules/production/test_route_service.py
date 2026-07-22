"""工艺路线与图编辑业务规则测试。

覆盖业务场景：
- 产品：名称唯一；软删除后同名可重建；有未完成批次时不可删除
- 图编辑：版本号递增；保存并读取完整图（节点/边/字段）；未知边引用拒绝；
  发布后图冻结不可再编辑；环形流转无起点拒绝发布；不可达节点拒绝发布
- 版本复制：新版本继承完整图结构
- 边界边约束：批次边界边不允许开启流水线模式
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.production.models import Batch, ProcessRoute, Product
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
        db, RouteCreate(product_id=product.id, name="V1"), user=None,
    )
    return product, route


class TestProduct:
    async def test_duplicate_name_rejected(self, db_session: AsyncSession) -> None:
        """同名产品重复创建抛出 AppException。"""
        name = f"产品-{uuid.uuid4().hex[:8]}"
        await route_service.create_product(
            db_session, ProductCreate(product_name=name), user=None,
        )
        with pytest.raises(AppException):
            await route_service.create_product(
                db_session, ProductCreate(product_name=name), user=None,
            )

    async def test_soft_delete_then_recreate_same_name(
        self, db_session: AsyncSession,
    ) -> None:
        """软删除后同名产品可重新创建，新 ID 与旧不同。"""
        name = f"产品-{uuid.uuid4().hex[:8]}"
        p1 = await route_service.create_product(
            db_session, ProductCreate(product_name=name), user=None,
        )
        await route_service.delete_product(db_session, p1.id, user=None)
        p2 = await route_service.create_product(
            db_session, ProductCreate(product_name=name), user=None,
        )
        assert p2.id != p1.id

    async def test_delete_with_unfinished_batch_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """存在未完成批次的产品不可删除。"""
        product = await route_service.create_product(
            db_session,
            ProductCreate(product_name=f"产品-{uuid.uuid4().hex[:8]}"),
            user=None,
        )
        db_session.add(
            Batch(
                batch_no=f"B-{uuid.uuid4().hex[:8]}",
                product_id=product.id,
                route_id=uuid.uuid4(),
            )
        )
        await db_session.flush()
        with pytest.raises(AppException):
            await route_service.delete_product(db_session, product.id, user=None)


class TestGraph:
    async def test_version_increments(self, db_session: AsyncSession) -> None:
        """同一产品下创建新路线版本号自动递增。"""
        product, route = await _draft_route(db_session)
        assert route.version == 1
        route2 = await route_service.create_route(
            db_session, RouteCreate(product_id=product.id, name="V2"), user=None,
        )
        assert route2.version == 2

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
            nodes=[NodeIn(node_code="A", name="a")],
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
            nodes=[NodeIn(node_code="A", name="a"), NodeIn(node_code="B", name="b")],
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
                NodeIn(node_code="A", name="a"),
                NodeIn(node_code="B", name="b"),
                NodeIn(node_code="X", name="孤立"),
            ],
            edges=[EdgeIn(from_node_code="A", to_node_code="B")],
        )
        await route_service.save_graph(db_session, route.id, graph, user=None)
        with pytest.raises(AppException):
            await route_service.publish_route(db_session, route.id, user=None)

    async def test_new_version_copies_graph(self, db_session: AsyncSession) -> None:
        """从已发布版本创建新版本，继承完整的 3 节点 3 边图结构。"""
        _, route = await _draft_route(db_session)
        await route_service.save_graph(
            db_session, route.id, build_graph_in(), user=None,
        )
        await route_service.publish_route(db_session, route.id, user=None)
        v2 = await route_service.new_version(db_session, route.id, user=None)
        assert v2.status == "draft"
        assert v2.version == 2
        graph = await route_service.get_graph(db_session, v2.id)
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
            db_session, RouteCreate(product_id=product.id, name="V1"), user=None,
        )
        graph = build_graph_in()
        graph.edges[0].allow_overlap = True
        with pytest.raises(AppException, match="批次边界边不允许"):
            await route_service.save_graph(db_session, route.id, graph, user=None)
