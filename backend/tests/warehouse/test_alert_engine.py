"""异常检测引擎测试（分期B Ticket 02）：规则、幂等、自动解决、AI 解读降级。"""

from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse import intelligence
from app.modules.warehouse.models import (
    WarehouseAlertRecord,
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseStock,
)


async def _seed(db: AsyncSession) -> dict[str, WarehouseMaterial]:
    m_low = WarehouseMaterial(
        code=f"INT-T-LOW-{uuid4().hex[:6]}", name="检测低库存", category="raw",
        unit="kg", safety_stock=Decimal("100"),
    )
    m_zero = WarehouseMaterial(
        code=f"INT-T-ZERO-{uuid4().hex[:6]}", name="检测零库存", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    m_ok = WarehouseMaterial(
        code=f"INT-T-OK-{uuid4().hex[:6]}", name="检测正常", category="packaging",
        unit="个", safety_stock=Decimal("5"),
    )
    db.add_all([m_low, m_zero, m_ok])
    await db.flush()

    loc = WarehouseLocation(code=f"INT-T-L{uuid4().hex[:6]}", name="检测库位")
    db.add(loc)
    await db.flush()

    db.add_all(
        [
            WarehouseStock(  # 低库存：30 < 100
                material_id=m_low.id, material_code=m_low.code, material_name=m_low.name,
                batch_no="B1", location_id=loc.id, location_code=loc.code,
                location_name=loc.name, quantity=Decimal("30"),
            ),
            WarehouseStock(  # 零库存
                material_id=m_zero.id, material_code=m_zero.code, material_name=m_zero.name,
                batch_no="", location_id=loc.id, location_code=loc.code,
                location_name=loc.name, quantity=Decimal("0"),
            ),
            WarehouseStock(  # 正常
                material_id=m_ok.id, material_code=m_ok.code, material_name=m_ok.name,
                batch_no="", location_id=loc.id, location_code=loc.code,
                location_name=loc.name, quantity=Decimal("500"),
            ),
        ]
    )
    await db.commit()
    return {"low": m_low, "zero": m_zero, "ok": m_ok, "loc": loc}


async def _cleanup(db: AsyncSession, materials: dict) -> None:

    from sqlalchemy import delete

    from app.modules.warehouse.models import (
        WarehouseMovement,
        WarehouseReplenishmentSuggestion,
    )

    ids = [m.id for m in materials.values() if hasattr(m, "id")]
    await db.rollback()
    await db.execute(delete(WarehouseAlertRecord).where(WarehouseAlertRecord.material_id.in_(ids)))
    await db.execute(
        delete(WarehouseReplenishmentSuggestion).where(
            WarehouseReplenishmentSuggestion.material_id.in_(ids)
        )
    )
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(ids)))
    await db.execute(delete(WarehouseMovement).where(WarehouseMovement.material_id.in_(ids)))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id == materials["loc"].id))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id.in_(ids)))
    await db.commit()


async def test_scan_creates_alerts_by_rule(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    materials = await _seed(db_session)
    try:
        scan = await auth_client.post("/api/v1/warehouse/intelligence/scan")
        assert scan.status_code == 200, scan.text

        alerts = await auth_client.get("/api/v1/warehouse/intelligence/alerts?status=open&page_size=100")
        assert alerts.status_code == 200
        body = alerts.json()["data"]
        by_rule = {}
        for item in body:
            if item["material_code"].startswith("INT-T-"):
                by_rule.setdefault(item["rule_key"], []).append(item["material_code"])

        assert "INT-T-LOW" in [m.split("-")[2] for m in []] or by_rule["low_stock"]
        assert by_rule["zero_stock"]
        # 正常物料不应出现在任何规则里
        assert all(
            "INT-T-OK" not in m for items in by_rule.values() for m in items
        )
    finally:
        await _cleanup(db_session, materials)


async def test_scan_idempotent_and_resolved_not_revived(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    materials = await _seed(db_session)
    try:
        await auth_client.post("/api/v1/warehouse/intelligence/scan")
        alerts = await auth_client.get("/api/v1/warehouse/intelligence/alerts?status=open&page_size=100")
        low_open = next(
            item
            for item in alerts.json()["data"]
            if item["rule_key"] == "low_stock" and item["material_code"].startswith("INT-T-LOW")
        )

        # 标记已处理
        resolved = await auth_client.post(
            f"/api/v1/warehouse/intelligence/alerts/{low_open['id']}/resolve"
        )
        assert resolved.status_code == 200

        # 再次扫描：已解决的不复活
        await auth_client.post("/api/v1/warehouse/intelligence/scan")
        alerts2 = await auth_client.get("/api/v1/warehouse/intelligence/alerts?status=open&page_size=100")
        still_open = [
            item
            for item in alerts2.json()["data"]
            if item["rule_key"] == "low_stock" and item["material_code"].startswith("INT-T-LOW")
        ]
        assert still_open == []
    finally:
        await _cleanup(db_session, materials)


async def test_alert_summary_fallback_without_llm(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    materials = await _seed(db_session)
    try:
        await auth_client.post("/api/v1/warehouse/intelligence/scan")

        async def _boom(*args, **kwargs):
            raise RuntimeError("llm down")

        monkeypatch.setattr(intelligence, "_llm_summarize", _boom)
        resp = await auth_client.get(
            "/api/v1/warehouse/intelligence/alerts/summary?rule_key=low_stock"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["source"] == "fallback"
        assert "低库存" in data["text"]
    finally:
        await _cleanup(db_session, materials)
