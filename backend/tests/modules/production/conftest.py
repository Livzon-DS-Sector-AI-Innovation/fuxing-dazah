"""生产模块测试夹具。"""

import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import app
from app.modules.equipment.public_api import EquipmentBrief
from app.modules.production.schemas import (
    EdgeIn,
    FieldDefIn,
    NodeIn,
    ProductCreate,
    RouteCreate,
    RouteGraphIn,
)
from app.modules.production.service import route_service
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User


@pytest.fixture
async def client(db_session: AsyncSession, test_user: User) -> AsyncIterator[AsyncClient]:
    """HTTP 客户端：共享会话 + 固定用户 + 放行 production:batch:read。"""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _override_get_current_user() -> User:
        return test_user

    async def _grant_read_perms(user_id: str, db: object) -> set[str]:
        return {"production:batch:read"}

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    with patch(
        "app.platform.permission.deps.get_user_permissions", new=_grant_read_perms
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """获取已有测试用户，若无则创建。"""
    from sqlalchemy import select

    stmt = select(User).where(User.is_deleted == False).limit(1)  # noqa: E712
    existing = (await db_session.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name="测试用户", employee_no="TEST001")
    db_session.add(user)
    await db_session.flush()
    return user


def rand_code(prefix: str) -> str:
    """随机编码，避免开发库残留数据撞唯一索引。"""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def make_raw_output(
    db: AsyncSession,
    *,
    batch_id: Any = None,
    node_id: Any = None,
    intermediate_type_id: Any = None,
    line_id: Any = None,
    created_by: Any = None,
    quantity: float = 100,
):
    """辅助：手造一条产出记录，精确控制 line_id、创建人与数量。

    未指定 batch_id / node_id / intermediate_type_id 时随机生成。
    """
    from app.modules.production.models import BatchIntermediateOutput

    out = BatchIntermediateOutput(
        batch_id=batch_id or uuid.uuid4(),
        execution_id=uuid.uuid4(),
        node_id=node_id or uuid.uuid4(),
        intermediate_type_id=intermediate_type_id or uuid.uuid4(),
        intermediate_batch_no=rand_code("S"),
        quantity=quantity,
        unit="L",
        is_product=False,
        remark=None,
        created_by=created_by,
        line_id=line_id,
    )
    db.add(out)
    await db.flush()
    return out


@pytest.fixture(autouse=True)
def _mock_equipment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock 设备校验：任何请求的设备 ID 都视为存在。

    execution_service 在后续任务才创建，模块不存在时静默跳过，
    保证 route/batch 阶段的测试也能加载本 conftest。
    """
    import importlib

    async def fake(db: AsyncSession, ids: list[uuid.UUID]) -> list[EquipmentBrief]:
        return [
            EquipmentBrief(id=i, equipment_no=f"EQ-{str(i)[:4]}", name="测试设备")
            for i in ids
        ]

    try:
        mod = importlib.import_module(
            "app.modules.production.service.execution_service"
        )
    except ModuleNotFoundError:
        return
    monkeypatch.setattr(mod, "get_equipment_briefs", fake)


def build_graph_in() -> RouteGraphIn:
    """标准测试图：发酵A --boundary--> 提炼B --normal--> 精制C，C --rework--> B。"""
    return RouteGraphIn(
        nodes=[
            NodeIn(node_code="A", name="发酵", stage_name="发酵", sort_order=1),
            NodeIn(
                node_code="B",
                name="提炼一",
                stage_name="提炼",
                sort_order=2,
                fields=[
                    FieldDefIn(
                        field_key="temp",
                        field_label="温度",
                        phase="start",
                        data_type="numeric",
                        unit="°C",
                        required=True,
                        min_value=20,
                        max_value=30,
                    ),
                    FieldDefIn(
                        field_key="yield_qty",
                        field_label="产出量",
                        field_group="产出物",
                        phase="end",
                        data_type="numeric",
                        unit="kg",
                        required=True,
                    ),
                ],
            ),
            NodeIn(node_code="C", name="精制", stage_name="精制", sort_order=3),
        ],
        edges=[
            EdgeIn(from_node_code="A", to_node_code="B", is_batch_boundary=True),
            EdgeIn(from_node_code="B", to_node_code="C", allow_overlap=True),
            EdgeIn(from_node_code="C", to_node_code="B", edge_type="rework"),
        ],
    )


@pytest.fixture
async def published_route(db_session: AsyncSession) -> dict[str, Any]:
    """已发布的标准路线，返回 product/route/节点/边界边。"""
    product = await route_service.create_product(
        db_session,
        ProductCreate(product_name=rand_code("测试产品"), product_code=rand_code("P")),
        user=None,
    )
    route = await route_service.create_route(
        db_session, RouteCreate(product_id=product.id, route_name="工艺V1"), user=None
    )
    await route_service.save_graph(db_session, route.id, build_graph_in(), user=None)
    route = await route_service.publish_route(db_session, route.id, user=None)
    graph = await route_service.get_graph(db_session, route.id)
    nodes = {n.node_code: n for n in graph.nodes}
    edge_ab = next(
        e
        for e in graph.edges
        if e.from_node_id == nodes["A"].id and e.to_node_id == nodes["B"].id
    )
    return {
        "product": product,
        "route": route,
        "node_a": nodes["A"],
        "node_b": nodes["B"],
        "node_c": nodes["C"],
        "edge_ab": edge_ab,
    }
