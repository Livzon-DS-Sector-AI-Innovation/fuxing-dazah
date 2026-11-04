"""warehouse 模块测试 fixtures 与数据工厂。

复用顶层 tests/conftest.py 的 `db_session`（真实库+回滚）。
api_context 提供共享 session 的 HTTP client，并放行全部 warehouse 权限。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import app
from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseMovement,
    WarehouseStock,
)
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User

WAREHOUSE_PERMS = {
    "warehouse:material:read",
    "warehouse:material:create",
    "warehouse:material:update",
    "warehouse:material:delete",
    "warehouse:location:read",
    "warehouse:location:create",
    "warehouse:location:update",
    "warehouse:location:delete",
    "warehouse:stock:read",
    "warehouse:movement:read",
    "warehouse:movement:create",
    "warehouse:movement:delete",
    "warehouse:stocktake:read",
    "warehouse:stocktake:create",
    "warehouse:stocktake:update",
    "warehouse:stocktake:confirm",
    "warehouse:stocktake:delete",
    # ── 系统配置 ──
    "warehouse:system-config:read",
    "warehouse:system-config:update",
}


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """获取已有测试用户，若无则创建。"""
    from sqlalchemy import select

    stmt = select(User).where(User.is_deleted == False).limit(1)  # noqa: E712
    existing = (await db_session.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name="仓储测试用户", employee_no=f"WH-{uuid.uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def api_context(
    db_session: AsyncSession, test_user: User
) -> AsyncIterator[tuple[AsyncClient, Any]]:
    """HTTP client 与共享 session 配对，并放行 warehouse 全部权限。"""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _override_get_current_user() -> User:
        return test_user

    async def _grant_perms(user_id: str, db: object) -> set[str]:
        return WAREHOUSE_PERMS

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    with patch(
        "app.platform.permission.deps.get_user_permissions", new=_grant_perms
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, db_session
    app.dependency_overrides.clear()


# ── 数据工厂 ──


def rand_code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def create_material(
    db: AsyncSession, *, code: str | None = None, **overrides: Any
) -> WarehouseMaterial:
    material = WarehouseMaterial(
        code=code or rand_code("MAT"),
        name=overrides.pop("name", f"测试物料-{uuid.uuid4().hex[:6]}"),
        category=overrides.pop("category", "raw"),
        unit=overrides.pop("unit", "kg"),
        safety_stock=overrides.pop("safety_stock", Decimal("0")),
        **overrides,
    )
    db.add(material)
    await db.flush()
    return material


async def create_location(
    db: AsyncSession, *, code: str | None = None, **overrides: Any
) -> WarehouseLocation:
    location = WarehouseLocation(
        code=code or rand_code("LOC"),
        name=overrides.pop("name", f"测试库位-{uuid.uuid4().hex[:6]}"),
        **overrides,
    )
    db.add(location)
    await db.flush()
    return location


async def create_stock(
    db: AsyncSession,
    material: WarehouseMaterial,
    location: WarehouseLocation,
    *,
    quantity: Decimal | float = Decimal("100"),
    batch_no: str = "",
) -> WarehouseStock:
    stock = WarehouseStock(
        material_id=material.id,
        material_code=material.code,
        material_name=material.name,
        batch_no=batch_no,
        location_id=location.id,
        location_code=location.code,
        location_name=location.name,
        quantity=Decimal(str(quantity)),
    )
    db.add(stock)
    await db.flush()
    return stock


async def create_movement(
    db: AsyncSession,
    material: WarehouseMaterial,
    location: WarehouseLocation,
    *,
    direction: str = "inbound",
    quantity: Decimal | float = Decimal("10"),
    **overrides: Any,
) -> WarehouseMovement:
    movement = WarehouseMovement(
        movement_no=overrides.pop(
            "movement_no", f"{direction[:2].upper()}-{uuid.uuid4().hex[:12]}"
        ),
        direction=direction,
        source_type=overrides.pop("source_type", "purchase"),
        material_id=material.id,
        material_code=material.code,
        material_name=material.name,
        quantity=Decimal(str(quantity)),
        unit=material.unit,
        location_id=location.id,
        location_code=location.code,
        location_name=location.name,
        **overrides,
    )
    db.add(movement)
    await db.flush()
    return movement


@pytest.fixture(autouse=True)
def _pin_bitable_env_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """仓库测试钉住两项运行参数（live 库会随生产切换/直读改造翻转）：

    - bitable_env_mode=test（prod 只读闸会让提交链测试先撞闸）；
    - warehouse_direct_read_enabled=0（直读分支会真连 Base——既有测试
      一律走镜像原路径；直读分支测试自行 monkeypatch 开关与 reader）。

    只覆写这两键，其余运行参数仍读 live 值；测试体内自行 monkeypatch
    runtime_store 者后到先得（fixture 先装、体内后装）。
    """
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    original = runtime_store.get_value

    def _get_value(key: str) -> Any:
        if key == "bitable_env_mode":
            return "test"
        if key == "warehouse_direct_read_enabled":
            return "0"
            return "test"
        return original(key)

    monkeypatch.setattr(runtime_store, "get_value", _get_value)


@pytest.fixture(autouse=True)
async def _hide_backfilled_mirror_rows(db_session: AsyncSession) -> AsyncIterator[None]:
    """回灌镜像数据对测试不可见（2026-11-04 生产切换回灌了 2731 库存行 +
    2.5w 流水行；盘点快照/月报聚合等断言按「干净库」口径写）。

    软删（updated_by 是 users 外键，不能做标记位）：
    - 正常回滚 → live 数据原样；
    - 端点显式 commit 泄漏（reconciliation run 先例）→ teardown 用新会话
      按签名补偿复活并提交，live 数据无净变更。
    """
    from sqlalchemy import update

    from app.modules.warehouse.models import WarehouseMovement, WarehouseStock

    await db_session.execute(
        update(WarehouseMovement)
        .where(
            WarehouseMovement.movement_no.like("RCPT-%")
            | WarehouseMovement.movement_no.like("OTB-%")
        )
        .values(is_deleted=True)
    )
    await db_session.execute(
        update(WarehouseStock)
        .where(WarehouseStock.location_code == "RECON-IMPORT")
        .values(is_deleted=True)
    )
    yield
    # 补偿（按回灌签名复活；正常回滚时为空操作。签名行若被真实业务刻意
    # 软删会被测试运行复活——回灌行不属本地操作域，可接受）。
    # 用测试专用 NullPool 工厂——全局池连接跨测试事件循环复用会炸
    from tests.conftest import _test_session_factory

    async with _test_session_factory() as heal:
        await heal.execute(
            update(WarehouseMovement)
            .where(
                WarehouseMovement.is_deleted.is_(True),
                WarehouseMovement.movement_no.like("RCPT-%")
                | WarehouseMovement.movement_no.like("OTB-%"),
            )
            .values(is_deleted=False)
        )
        await heal.execute(
            update(WarehouseStock)
            .where(
                WarehouseStock.is_deleted.is_(True),
                WarehouseStock.location_code == "RECON-IMPORT",
            )
            .values(is_deleted=False)
        )
        await heal.commit()
