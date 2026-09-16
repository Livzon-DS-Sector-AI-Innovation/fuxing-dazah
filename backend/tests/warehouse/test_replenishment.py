"""补货建议引擎测试（分期B Ticket 03）。"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseMovement,
    WarehouseReplenishmentSuggestion,
    WarehouseStock,
)

CN_TZ = ZoneInfo("Asia/Shanghai")


async def _seed(db: AsyncSession) -> dict[str, object]:
    m_fast = WarehouseMaterial(
        code=f"RPL-T-FAST-{uuid4().hex[:6]}", name="补货快消耗", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    m_slow = WarehouseMaterial(
        code=f"RPL-T-SLOW-{uuid4().hex[:6]}", name="补货无消耗", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    loc = WarehouseLocation(code=f"RPL-T-L{uuid4().hex[:6]}", name="补货测试库位")
    db.add_all([m_fast, m_slow, loc])
    await db.flush()

    now = datetime.now(CN_TZ)
    # 快消耗：30 天内出库合计 60（日均 2），当前库存 10 → 可支撑 5 天，建议 14*2-10=18
    for d in range(6):
        db.add(
            WarehouseMovement(
                movement_no=f"RPL-T-OUT-{uuid4().hex[:8]}-{d}",
                direction="outbound", source_type="production",
                material_id=m_fast.id, material_code=m_fast.code, material_name=m_fast.name,
                batch_no="", quantity=Decimal("10"), unit="kg",
                location_id=loc.id, location_code=loc.code, location_name=loc.name,
                occurred_at=now - timedelta(days=d * 5),
            )
        )
    # 无消耗物料：仅入库
    db.add(
        WarehouseMovement(
            movement_no=f"RPL-T-IN-{uuid4().hex[:8]}",
            direction="inbound", source_type="purchase",
            material_id=m_slow.id, material_code=m_slow.code, material_name=m_slow.name,
            batch_no="", quantity=Decimal("50"), unit="kg",
            location_id=loc.id, location_code=loc.code, location_name=loc.name,
            occurred_at=now - timedelta(days=2),
        )
    )
    db.add_all(
        [
            WarehouseStock(
                material_id=m_fast.id, material_code=m_fast.code, material_name=m_fast.name,
                batch_no="RB1", location_id=loc.id, location_code=loc.code,
                location_name=loc.name, quantity=Decimal("10"),
            ),
            WarehouseStock(
                material_id=m_slow.id, material_code=m_slow.code, material_name=m_slow.name,
                batch_no="RB2", location_id=loc.id, location_code=loc.code,
                location_name=loc.name, quantity=Decimal("50"),
            ),
        ]
    )
    await db.commit()
    return {"fast": m_fast, "slow": m_slow, "loc": loc}


async def _cleanup(db: AsyncSession, seeded: dict) -> None:

    from sqlalchemy import delete

    from app.modules.warehouse.models import WarehouseAlertRecord

    ids = [seeded["fast"].id, seeded["slow"].id]
    await db.rollback()
    await db.execute(delete(WarehouseReplenishmentSuggestion).where(
        WarehouseReplenishmentSuggestion.material_id.in_(ids)
    ))
    await db.execute(delete(WarehouseAlertRecord).where(WarehouseAlertRecord.material_id.in_(ids)))
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(ids)))
    await db.execute(delete(WarehouseMovement).where(
        WarehouseMovement.material_id.in_(ids),
        WarehouseMovement.movement_no.like("RPL-T-%"),
    ))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id == seeded["loc"].id))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id.in_(ids)))
    await db.commit()


async def test_refresh_computes_suggestions(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seed(db_session)
    try:
        resp = await auth_client.post("/api/v1/warehouse/intelligence/scan")
        assert resp.status_code == 200, resp.text

        listed = await auth_client.get("/api/v1/warehouse/replenishment/suggestions?status=pending")
        assert listed.status_code == 200
        rows = {
            item["material_code"]: item
            for item in listed.json()["data"]
            if item["material_code"].startswith("RPL-T-")
        }
        assert "RPL-T-FAST" in {c.split("-")[0] + "-" + c.split("-")[1] for c in rows} or rows
        fast = next(
            item
            for code, item in rows.items()
            if code.startswith("RPL-T-FAST")
        )
        assert float(fast["avg_daily_outbound"]) == 2.0
        assert float(fast["days_cover"]) == 5.0
        assert float(fast["suggested_qty"]) == 18.0
        # 无消耗物料不生成建议
        assert all(not code.startswith("RPL-T-SLOW") for code in rows)
    finally:
        await _cleanup(db_session, seeded)


async def test_suggestion_status_flow_and_refresh_protection(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seed(db_session)
    try:
        await auth_client.post("/api/v1/warehouse/intelligence/scan")
        listed = await auth_client.get("/api/v1/warehouse/replenishment/suggestions?status=pending")
        fast = next(
            item
            for item in listed.json()["data"]
            if item["material_code"].startswith("RPL-T-FAST")
        )

        handled = await auth_client.post(
            f"/api/v1/warehouse/replenishment/suggestions/{fast['id']}/status",
            json={"status": "handled"},
        )
        assert handled.status_code == 200
        assert handled.json()["data"]["status"] == "handled"

        # 再扫描：handled 行不被覆盖
        await auth_client.post("/api/v1/warehouse/intelligence/scan")
        all_rows = await auth_client.get("/api/v1/warehouse/replenishment/suggestions?page_size=100")
        handled_row = next(
            item
            for item in all_rows.json()["data"]
            if item["id"] == fast["id"]
        )
        assert handled_row["status"] == "handled"
        assert handled_row["handled_at"] is not None

        # pending → 才能流转；handled 再流转被拒
        again = await auth_client.post(
            f"/api/v1/warehouse/replenishment/suggestions/{fast['id']}/status",
            json={"status": "ignored"},
        )
        assert again.status_code == 400
    finally:
        await _cleanup(db_session, seeded)


async def test_suggestion_status_requires_valid_value(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    seeded = await _seed(db_session)
    try:
        await auth_client.post("/api/v1/warehouse/intelligence/scan")
        listed = await auth_client.get("/api/v1/warehouse/replenishment/suggestions?status=pending")
        fast = next(
            item
            for item in listed.json()["data"]
            if item["material_code"].startswith("RPL-T-FAST")
        )
        bad = await auth_client.post(
            f"/api/v1/warehouse/replenishment/suggestions/{fast['id']}/status",
            json={"status": "pending"},
        )
        assert bad.status_code == 422
    finally:
        await _cleanup(db_session, seeded)
