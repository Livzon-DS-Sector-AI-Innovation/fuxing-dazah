"""周转率/消耗排名/库存报表测试（分期C Ticket 02）。"""

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
    WarehouseStock,
)

CN_TZ = ZoneInfo("Asia/Shanghai")


async def _seed(db: AsyncSession) -> dict[str, WarehouseMaterial]:
    m_fast = WarehouseMaterial(
        code=f"TRP-FAST-{uuid4().hex[:6]}", name="周转快", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    m_zero = WarehouseMaterial(
        code=f"TRP-ZERO-{uuid4().hex[:6]}", name="周转零库存", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    loc = WarehouseLocation(code=f"TRP-L{uuid4().hex[:6]}", name="周转测试库位")
    db.add_all([m_fast, m_zero, loc])
    await db.flush()

    now = datetime.now(CN_TZ)
    # 快消耗：近 30 天出库 40，当前库存 20 → 周转率 2.0
    db.add_all(
        [
            WarehouseMovement(
                movement_no=f"TRP-OUT-{uuid4().hex[:8]}",
                direction="outbound", source_type="production",
                material_id=m_fast.id, material_code=m_fast.code,
                material_name=m_fast.name, batch_no="", quantity=Decimal("40"),
                unit="kg", location_id=loc.id, location_code=loc.code,
                location_name=loc.name, occurred_at=now - timedelta(days=3),
            ),
            # 零库存消耗：出库 15，库存 0
            WarehouseMovement(
                movement_no=f"TRP-OUT-{uuid4().hex[:8]}",
                direction="outbound", source_type="sale",
                material_id=m_zero.id, material_code=m_zero.code,
                material_name=m_zero.name, batch_no="", quantity=Decimal("15"),
                unit="kg", location_id=loc.id, location_code=loc.code,
                location_name=loc.name, occurred_at=now - timedelta(days=2),
            ),
            WarehouseStock(  # 快消耗的当前库存
                material_id=m_fast.id, material_code=m_fast.code,
                material_name=m_fast.name, batch_no="B1",
                location_id=loc.id, location_code=loc.code,
                location_name=loc.name, quantity=Decimal("20"),
            ),
        ]
    )
    await db.commit()
    return {"fast": m_fast, "zero": m_zero, "loc": loc}


async def _cleanup(db: AsyncSession, materials: dict) -> None:
    from sqlalchemy import delete

    from app.modules.warehouse.models import WarehouseAlertRecord

    ids = [m.id for m in materials.values() if hasattr(m, "id")]
    await db.rollback()
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(ids)))
    await db.execute(delete(WarehouseMovement).where(WarehouseMovement.material_id.in_(ids)))
    await db.execute(delete(WarehouseAlertRecord).where(WarehouseAlertRecord.material_id.in_(ids)))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id == materials["loc"].id))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id.in_(ids)))
    await db.commit()


async def test_turnover_ranking(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    materials = await _seed(db_session)
    try:
        resp = await auth_client.get(
            "/api/v1/warehouse/reports/turnover?days=30&order=desc&limit=50"
        )
        assert resp.status_code == 200, resp.text
        rows = resp.json()["data"]
        fast = next(
            (r for r in rows if r["material_code"].startswith("TRP-FAST")), None
        )
        assert fast is not None
        assert fast["turnover"] == 2.0  # 40 / 20
        # 零库存消耗物料：turnover None（已售罄）
        zero = next((r for r in rows if r["material_code"].startswith("TRP-ZERO")), None)
        assert zero is not None
        assert zero["turnover"] is None
    finally:
        await _cleanup(db_session, materials)


async def test_consumption_ranking(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    materials = await _seed(db_session)
    try:
        resp = await auth_client.get("/api/v1/warehouse/reports/consumption?days=30&limit=50")
        assert resp.status_code == 200
        rows = resp.json()["data"]
        codes = [r["material_code"] for r in rows if r["material_code"].startswith("TRP-")]
        assert "TRP-FAST" in [c for c in codes if c.startswith("TRP-FAST")] or any(
            c.startswith("TRP-FAST") for c in codes
        )
        fast = next(r for r in rows if r["material_code"].startswith("TRP-FAST"))
        assert fast["outbound_qty"] == 40.0
    finally:
        await _cleanup(db_session, materials)


async def test_stock_report_and_export(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    materials = await _seed(db_session)
    try:
        resp = await auth_client.get("/api/v1/warehouse/reports/stock?page=1&page_size=200")
        assert resp.status_code == 200
        # 按本次运行的唯一物料编码过滤（历史残留行编码不同）
        rows = [
            item
            for item in resp.json()["data"]
            if item["material_code"] == materials["fast"].code
        ]
        assert len(rows) == 1
        assert float(rows[0]["quantity"]) == 20.0

        export = await auth_client.get("/api/v1/warehouse/reports/stock/export")
        assert export.status_code == 200
        assert ".xlsx" in export.headers.get("content-disposition", "")
    finally:
        await _cleanup(db_session, materials)
