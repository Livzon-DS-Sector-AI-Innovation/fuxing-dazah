"""出入库按物料筛选测试（Ticket 08）：GET /movements?material_id= 精确过滤。"""

from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import WarehouseLocation, WarehouseMaterial


async def _seed(db: AsyncSession) -> tuple[WarehouseMaterial, WarehouseMaterial, WarehouseLocation]:
    m_a = WarehouseMaterial(
        code=f"MVF-T-{uuid4().hex[:8]}", name="流水物料A", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    m_b = WarehouseMaterial(
        code=f"MVF-T-{uuid4().hex[:8]}", name="流水物料B", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    location = WarehouseLocation(code=f"MVF-T-L{uuid4().hex[:8]}", name="流水测试库位")
    db.add_all([m_a, m_b, location])
    await db.commit()
    return m_a, m_b, location


async def _cleanup(db: AsyncSession, material_ids: list, location_id) -> None:
    from sqlalchemy import delete

    from app.modules.warehouse.models import WarehouseMovement, WarehouseStock

    await db.rollback()
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(material_ids)))
    await db.execute(delete(WarehouseMovement).where(WarehouseMovement.material_id.in_(material_ids)))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id == location_id))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id.in_(material_ids)))
    await db.commit()


async def test_movements_filter_by_material(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    m_a, m_b, location = await _seed(db_session)
    try:
        for material, batch in ((m_a, "BA"), (m_b, "BB")):
            resp = await auth_client.post(
                "/api/v1/warehouse/movements",
                json={
                    "direction": "inbound",
                    "source_type": "purchase",
                    "material_id": str(material.id),
                    "batch_no": batch,
                    "quantity": 5,
                    "location_id": str(location.id),
                },
            )
            assert resp.status_code == 201, resp.text

        listed = await auth_client.get(
            f"/api/v1/warehouse/movements?material_id={m_a.id}&page_size=50"
        )
        assert listed.status_code == 200
        body = listed.json()
        assert body["meta"]["total"] == 1
        assert all(item["material_id"] == str(m_a.id) for item in body["data"])
    finally:
        await _cleanup(db_session, [m_a.id, m_b.id], location.id)
