"""库存状态机测试（分期D Ticket 03）：状态流转校验与流转日志。"""

from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseMovement,
    WarehouseStock,
    WarehouseStockStatusLog,
)


async def _seed_stock(db: AsyncSession, suffix: str) -> WarehouseStock:
    m = WarehouseMaterial(
        code=f"STS-{suffix}", name="状态机测试物料", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    loc = WarehouseLocation(code=f"STS-L{suffix}", name="状态机测试库位")
    db.add_all([m, loc])
    await db.flush()
    stock = WarehouseStock(
        material_id=m.id, material_code=m.code, material_name=m.name,
        batch_no=f"SB{suffix}", location_id=loc.id, location_code=loc.code,
        location_name=loc.name, quantity=Decimal("50"),
    )
    db.add(stock)
    await db.commit()
    return stock


async def _cleanup(db: AsyncSession) -> None:
    from sqlalchemy import delete

    await db.rollback()
    m_ids = select(WarehouseMaterial.id).where(WarehouseMaterial.code.like("STS-%"))
    l_ids = select(WarehouseLocation.id).where(WarehouseLocation.code.like("STS-%"))
    s_ids = select(WarehouseStock.id).where(WarehouseStock.material_id.in_(m_ids))
    await db.execute(delete(WarehouseStockStatusLog).where(
        WarehouseStockStatusLog.stock_id.in_(s_ids)
    ))
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(m_ids)))
    await db.execute(delete(WarehouseMovement).where(WarehouseMovement.material_id.in_(m_ids)))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id.in_(l_ids)))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id.in_(m_ids)))
    await db.commit()


async def test_normal_to_quarantine(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        resp = await auth_client.post(
            f"/api/v1/warehouse/stocks/{stock.id}/status",
            json={"new_status": "quarantine", "reason": "质检待检"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["new_status"] == "quarantine"
    finally:
        await _cleanup(db_session)


async def test_invalid_transition_rejected(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        # normal → frozen 直接跳转不允许
        resp = await auth_client.post(
            f"/api/v1/warehouse/stocks/{stock.id}/status",
            json={"new_status": "frozen", "reason": "跳过待检"},
        )
        assert resp.status_code == 400
    finally:
        await _cleanup(db_session)


async def test_status_log_written(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        await auth_client.post(
            f"/api/v1/warehouse/stocks/{stock.id}/status",
            json={"new_status": "quarantine", "reason": "质检待检"},
        )
        logs = (
            await db_session.execute(
                select(WarehouseStockStatusLog).where(
                    WarehouseStockStatusLog.stock_id == stock.id
                )
            )
        ).scalars().all()
        assert len(logs) >= 1
        assert logs[0].old_status == "normal"
        assert logs[0].new_status == "quarantine"
    finally:
        await _cleanup(db_session)


async def test_stock_list_status_filter(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """库存列表按状态筛选（分期D Ticket 03 前端筛选的后端支撑）。"""
    try:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        await auth_client.post(
            f"/api/v1/warehouse/stocks/{stock.id}/status",
            json={"new_status": "quarantine", "reason": "质检待检"},
        )
        batch = stock.batch_no

        listed = await auth_client.get(
            "/api/v1/warehouse/stocks",
            params={"batch_no": batch, "status": "quarantine"},
        )
        assert listed.status_code == 200, listed.text
        items = listed.json()["data"]
        assert len(items) == 1
        assert items[0]["id"] == str(stock.id)
        assert items[0]["status"] == "quarantine"

        empty = await auth_client.get(
            "/api/v1/warehouse/stocks",
            params={"batch_no": batch, "status": "frozen"},
        )
        assert empty.status_code == 200
        assert empty.json()["data"] == []
    finally:
        await _cleanup(db_session)
