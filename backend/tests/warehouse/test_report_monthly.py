"""出入库月报测试（分期C Ticket 01）：聚合口径与 Excel 导出。"""

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


async def _seed(db: AsyncSession) -> None:
    m1 = WarehouseMaterial(
        code=f"RPT-M1-{uuid4().hex[:6]}", name="月报物料一", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    m2 = WarehouseMaterial(
        code=f"RPT-M2-{uuid4().hex[:6]}", name="月报物料二", category="raw",
        unit="个", safety_stock=Decimal("0"),
    )
    loc = WarehouseLocation(code=f"RPT-L{uuid4().hex[:6]}", name="月报库位")
    db.add_all([m1, m2, loc])
    await db.flush()

    now = datetime.now(CN_TZ)
    this_month = now.replace(day=2, hour=10, minute=0, second=0, microsecond=0)
    last_month = (this_month - timedelta(days=15)).replace(day=28, hour=10)

    def mv(no, direction, material, qty, occurred):
        return WarehouseMovement(
            movement_no=no, direction=direction, source_type="purchase"
            if direction == "inbound" else "sale",
            material_id=material.id, material_code=material.code,
            material_name=material.name, batch_no="", quantity=Decimal(qty),
            unit=material.unit, location_id=loc.id, location_code=loc.code,
            location_name=loc.name, occurred_at=occurred,
        )

    db.add_all(
        [
            mv(f"RPT-IN-{uuid4().hex[:8]}", "inbound", m1, "10", this_month),
            mv(f"RPT-IN-{uuid4().hex[:8]}", "inbound", m1, "15", this_month),
            mv(f"RPT-OUT-{uuid4().hex[:8]}", "outbound", m1, "5", this_month),
            mv(f"RPT-IN-{uuid4().hex[:8]}", "inbound", m2, "7", this_month),
            # 上月记录：不应计入本月
            mv(f"RPT-IN-{uuid4().hex[:8]}", "inbound", m1, "999", last_month),
        ]
    )
    await db.commit()


async def _cleanup(db: AsyncSession) -> None:
    from sqlalchemy import delete

    from app.modules.warehouse.models import WarehouseStock

    await db.rollback()
    m_ids = select(WarehouseMaterial.id).where(WarehouseMaterial.code.like("RPT-%"))
    l_ids = select(WarehouseLocation.id).where(WarehouseLocation.code.like("RPT-%"))
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(m_ids)))
    await db.execute(delete(WarehouseMovement).where(WarehouseMovement.material_id.in_(m_ids)))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id.in_(l_ids)))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id.in_(m_ids)))
    await db.commit()


async def test_monthly_report_aggregates(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        await _seed(db_session)
        now = datetime.now(CN_TZ)
        resp = await auth_client.get(
            f"/api/v1/warehouse/reports/monthly?year={now.year}&month={now.month}"
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]

        # 月报聚合仅统计本月：种子本月 3 笔入/1 笔出（残留可能是上月或本月）
        assert data["summary"]["inbound_count"] >= 3
        assert data["summary"]["outbound_count"] >= 1

        items = {i["material_code"]: i for i in data["items"]}
        own_m1 = [k for k in items if k.startswith("RPT-M1")]
        assert own_m1, "月内自造物料应出现在明细"
        assert float(items[own_m1[0]]["inbound_qty"]) == 25.0
        assert float(items[own_m1[0]]["outbound_qty"]) == 5.0
    finally:
        await _cleanup(db_session)


async def test_monthly_report_export(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        await _seed(db_session)
        now = datetime.now(CN_TZ)
        resp = await auth_client.get(
            f"/api/v1/warehouse/reports/monthly/export?year={now.year}&month={now.month}"
        )
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers.get("content-type", "")
        assert ".xlsx" in resp.headers.get("content-disposition", "")
        assert len(resp.content) > 1000
    finally:
        await _cleanup(db_session)
