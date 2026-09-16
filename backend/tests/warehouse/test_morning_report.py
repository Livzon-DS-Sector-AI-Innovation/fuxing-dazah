"""每日晨报测试（分期C Ticket 03）：聚合口径、幂等覆盖、窗口守卫、端点。"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse import morning_report
from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseMovement,
    WarehouseStock,
)

CN_TZ = ZoneInfo("Asia/Shanghai")


async def _seed(db: AsyncSession) -> None:
    m = WarehouseMaterial(
        code=f"BRI-M-{uuid4().hex[:6]}", name="晨报物料", category="raw",
        unit="kg", safety_stock=Decimal("100"),
    )
    loc = WarehouseLocation(code=f"BRI-L{uuid4().hex[:6]}", name="晨报库位")
    db.add_all([m, loc])
    await db.flush()

    now = datetime.now(CN_TZ)
    db.add_all(
        [
            WarehouseMovement(  # 昨日入库 20
                movement_no=f"BRI-IN-{uuid4().hex[:8]}",
                direction="inbound", source_type="purchase",
                material_id=m.id, material_code=m.code, material_name=m.name,
                batch_no="B1", quantity=Decimal("20"), unit="kg",
                location_id=loc.id, location_code=loc.code, location_name=loc.name,
                occurred_at=now - timedelta(days=1),
            ),
            WarehouseStock(  # 低库存：30 < 100
                material_id=m.id, material_code=m.code, material_name=m.name,
                batch_no="B1", location_id=loc.id, location_code=loc.code,
                location_name=loc.name, quantity=Decimal("30"),
            ),
        ]
    )
    await db.commit()


async def _cleanup(db: AsyncSession) -> None:
    from sqlalchemy import delete

    from app.modules.warehouse.models import WarehouseAlertRecord

    await db.rollback()
    m_ids = select(WarehouseMaterial.id).where(WarehouseMaterial.code.like("BRI-%"))
    l_ids = select(WarehouseLocation.id).where(WarehouseLocation.code.like("BRI-%"))
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(m_ids)))
    await db.execute(delete(WarehouseMovement).where(WarehouseMovement.material_id.in_(m_ids)))
    await db.execute(delete(WarehouseAlertRecord).where(WarehouseAlertRecord.material_id.in_(m_ids)))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id.in_(l_ids)))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id.in_(m_ids)))
    await db.commit()


async def test_generate_morning_report_content(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        await _seed(db_session)
        # 直接在 db_session 上扫描（同会话可见，无需跨会话提交）
        from app.modules.warehouse.intelligence import run_alert_scan

        await run_alert_scan(db_session)

        today = datetime.now(CN_TZ).date()
        content = await morning_report.generate_morning_report(db_session, today)

        assert content["yesterday"]["inbound_qty"] == 20.0  # 种子昨日入库 20
        assert content["yesterday"]["inbound_count"] == 1
        assert content["alerts"]["open_total"] >= 1
        assert any(i["material_name"] == "晨报物料" for i in content["low_stock_top5"])
    finally:
        await _cleanup(db_session)


async def test_morning_report_idempotent(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        await _seed(db_session)
        today = datetime.now(CN_TZ).date()
        await morning_report.generate_morning_report(db_session, today)
        await db_session.commit()  # 跨会话可见
        await morning_report.generate_morning_report(db_session, today)
        await db_session.commit()

        listed = await auth_client.get("/api/v1/warehouse/reports/briefings?limit=10")
        assert listed.status_code == 200
        same_day = [
            item
            for item in listed.json()["data"]
            if item["brief_date"] == today.isoformat()
        ]
        assert len(same_day) == 1
    finally:
        await _cleanup(db_session)


async def test_morning_report_endpoint(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        await _seed(db_session)
        today = datetime.now(CN_TZ).date()
        await morning_report.generate_morning_report(db_session, today)
        await db_session.commit()  # 跨会话可见

        resp = await auth_client.get(
            f"/api/v1/warehouse/reports/briefings/{today.isoformat()}"
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["brief_date"] == today.isoformat()
    finally:
        await _cleanup(db_session)


def test_morning_report_window_guard() -> None:
    assert morning_report.is_in_briefing_window(datetime(2026, 9, 16, 8, 0, tzinfo=CN_TZ))
    assert morning_report.is_in_briefing_window(datetime(2026, 9, 16, 8, 59, tzinfo=CN_TZ))
    assert not morning_report.is_in_briefing_window(datetime(2026, 9, 16, 9, 0, tzinfo=CN_TZ))
    assert not morning_report.is_in_briefing_window(datetime(2026, 9, 16, 7, 0, tzinfo=CN_TZ))
