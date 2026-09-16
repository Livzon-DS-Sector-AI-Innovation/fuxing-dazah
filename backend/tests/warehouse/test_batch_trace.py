"""批次追溯测试（分期D Ticket 01）：入库来源+出库去向+Excel 导出。"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseMovement,
)

CN_TZ = ZoneInfo("Asia/Shanghai")


async def _seed(db: AsyncSession) -> dict:
    suffix = uuid4().hex[:8]
    m = WarehouseMaterial(
        code=f"TRC-{suffix}", name="追溯测试物料", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    loc = WarehouseLocation(code=f"TRC-L{suffix}", name="追溯库位")
    db.add_all([m, loc])
    await db.flush()

    now = datetime.now(CN_TZ)
    rows = [
        WarehouseMovement(
            movement_no=f"TRC-IN-{suffix}-1", direction="inbound",
            source_type="purchase", material_id=m.id, material_code=m.code,
            material_name=m.name, batch_no="TB1", quantity=Decimal("100"),
            unit="kg", location_id=loc.id, location_code=loc.code,
            location_name=loc.name, occurred_at=now - timedelta(days=10),
            remark="采购入库",
        ),
        WarehouseMovement(
            movement_no=f"TRC-IN-{suffix}-2", direction="inbound",
            source_type="purchase", material_id=m.id, material_code=m.code,
            material_name=m.name, batch_no="TB1", quantity=Decimal("50"),
            unit="kg", location_id=loc.id, location_code=loc.code,
            location_name=loc.name, occurred_at=now - timedelta(days=5),
            remark="补货入库",
        ),
        WarehouseMovement(
            movement_no=f"TRC-OUT-{suffix}-1", direction="outbound",
            source_type="production", material_id=m.id, material_code=m.code,
            material_name=m.name, batch_no="TB1", quantity=Decimal("30"),
            unit="kg", location_id=loc.id, location_code=loc.code,
            location_name=loc.name, occurred_at=now - timedelta(days=3),
            remark="生产领料",
        ),
    ]
    db.add_all(rows)
    await db.commit()
    return {"material": m, "location": loc}


async def _cleanup(db: AsyncSession) -> None:
    from sqlalchemy import delete

    from app.modules.warehouse.models import WarehouseStock

    await db.rollback()
    m_ids = select(WarehouseMaterial.id).where(WarehouseMaterial.code.like("TRC-%"))
    l_ids = select(WarehouseLocation.id).where(WarehouseLocation.code.like("TRC-%"))
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(m_ids)))
    await db.execute(delete(WarehouseMovement).where(WarehouseMovement.material_code.like("TRC-%")))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id.in_(l_ids)))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.code.like("TRC-%")))
    await db.commit()


async def test_batch_trace_returns_flows(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        result = await _seed(db_session)
        code = result["material"].code
        resp = await auth_client.get(
            f"/api/v1/warehouse/reports/batch-trace?material_code={code}&batch_no=TB1"
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["material_code"] == code
        assert len(data["inbound_flows"]) == 2
        assert len(data["outbound_flows"]) == 1
        assert data["inbound_flows"][0]["quantity"] in (50.0, 100.0)
        assert data["outbound_flows"][0]["remark"] == "生产领料"
    finally:
        await _cleanup(db_session)


async def test_batch_trace_export(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        result = await _seed(db_session)
        code = result["material"].code
        resp = await auth_client.get(
            f"/api/v1/warehouse/reports/batch-trace/export"
            f"?material_code={code}&batch_no=TB1"
        )
        assert resp.status_code == 200
        assert ".xlsx" in resp.headers.get("content-disposition", "")
    finally:
        await _cleanup(db_session)
