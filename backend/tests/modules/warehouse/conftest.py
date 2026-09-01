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
