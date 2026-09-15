"""库存高级筛选测试（Ticket 09）：批次号、效期区间。"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseStock,
)


async def _seed_two_stocks(db: AsyncSession) -> tuple[WarehouseMaterial, WarehouseLocation]:
    material = WarehouseMaterial(
        code=f"FLT-T-{uuid4().hex[:8]}",
        name="筛选测试物料",
        category="raw",
        unit="kg",
        safety_stock=Decimal("0"),
    )
    location = WarehouseLocation(code=f"FLT-T-L{uuid4().hex[:8]}", name="筛选测试库位")
    db.add_all([material, location])
    await db.flush()
    db.add_all(
        [
            WarehouseStock(
                material_id=material.id,
                material_code=material.code,
                material_name=material.name,
                batch_no="B-NEAR",
                location_id=location.id,
                location_code=location.code,
                location_name=location.name,
                expiry_date=date.today() + timedelta(days=20),
                quantity=Decimal("10"),
            ),
            WarehouseStock(
                material_id=material.id,
                material_code=material.code,
                material_name=material.name,
                batch_no="B-FAR",
                location_id=location.id,
                location_code=location.code,
                location_name=location.name,
                expiry_date=date.today() + timedelta(days=300),
                quantity=Decimal("20"),
            ),
        ]
    )
    await db.commit()
    return material, location


async def _cleanup(db: AsyncSession, material_id, location_id) -> None:
    from sqlalchemy import delete

    from app.modules.warehouse.models import WarehouseMovement

    await db.rollback()
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id == material_id))
    await db.execute(delete(WarehouseMovement).where(WarehouseMovement.material_id == material_id))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id == location_id))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id == material_id))
    await db.commit()


async def test_stocks_filter_by_batch(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    material, location = await _seed_two_stocks(db_session)
    try:
        resp = await auth_client.get("/api/v1/warehouse/stocks?batch_no=B-NEAR")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["batch_no"] == "B-NEAR"
    finally:
        await _cleanup(db_session, material.id, location.id)


async def test_stocks_filter_by_expiry_range(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    material, location = await _seed_two_stocks(db_session)
    try:
        frm = (date.today() + timedelta(days=10)).isoformat()
        to = (date.today() + timedelta(days=40)).isoformat()
        resp = await auth_client.get(
            f"/api/v1/warehouse/stocks?expiry_from={frm}&expiry_to={to}"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["batch_no"] == "B-NEAR"
    finally:
        await _cleanup(db_session, material.id, location.id)
