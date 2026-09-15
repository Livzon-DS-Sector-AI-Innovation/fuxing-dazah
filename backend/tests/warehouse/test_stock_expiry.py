"""库存效期测试（Ticket 07）：入库登记写入效期、出库拒绝效期、列表返回效期。

造数编码带随机后缀避免跨测试残留冲突；清理为尽力而为
（路由内创建的库存行在 client 会话回滚时自动消失）。
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseStock,
)


async def _seed(db: AsyncSession, suffix: str) -> tuple[WarehouseMaterial, WarehouseLocation]:
    material = WarehouseMaterial(
        code=f"EXP-T-{suffix}",
        name="效期测试物料",
        category="raw",
        unit="kg",
        safety_stock=Decimal("0"),
    )
    location = WarehouseLocation(code=f"EXP-T-L{suffix}", name="效期测试库位")
    db.add_all([material, location])
    await db.commit()
    return material, location


async def _cleanup(db: AsyncSession, suffix: str) -> None:
    await db.rollback()  # 清掉本会话可能残留的失败事务
    m_ids = select(WarehouseMaterial.id).where(WarehouseMaterial.code == f"EXP-T-{suffix}")
    l_ids = select(WarehouseLocation.id).where(WarehouseLocation.code == f"EXP-T-L{suffix}")
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(m_ids)))
    await db.execute(delete(WarehouseStock).where(WarehouseStock.location_id.in_(l_ids)))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.code == f"EXP-T-L{suffix}"))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.code == f"EXP-T-{suffix}"))
    await db.commit()


async def test_inbound_with_expiry_sets_stock_expiry(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    suffix = uuid4().hex[:8]
    try:
        material, location = await _seed(db_session, suffix)
        expiry = (date.today() + timedelta(days=45)).isoformat()

        resp = await auth_client.post(
            "/api/v1/warehouse/movements",
            json={
                "direction": "inbound",
                "source_type": "purchase",
                "material_id": str(material.id),
                "batch_no": f"EXP-B1-{suffix}",
                "quantity": 10,
                "location_id": str(location.id),
                "expiry_date": expiry,
            },
        )
        assert resp.status_code == 201, resp.text

        # 断言走 API（client 会话未提交，跨会话查库不可见）
        listed = await auth_client.get("/api/v1/warehouse/stocks")
        assert listed.status_code == 200
        row = next(
            item for item in listed.json()["data"] if item["batch_no"] == f"EXP-B1-{suffix}"
        )
        assert row["expiry_date"] == expiry
        assert float(row["quantity"]) == 10.0
    finally:
        await _cleanup(db_session, suffix)


async def test_outbound_with_expiry_rejected(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    suffix = uuid4().hex[:8]
    try:
        material, location = await _seed(db_session, suffix)
        resp = await auth_client.post(
            "/api/v1/warehouse/movements",
            json={
                "direction": "outbound",
                "source_type": "sale",
                "material_id": str(material.id),
                "batch_no": "",
                "quantity": 1,
                "location_id": str(location.id),
                "expiry_date": "2027-01-01",
            },
        )
        assert resp.status_code == 422
    finally:
        await _cleanup(db_session, suffix)


async def test_inbound_without_expiry_allows_null(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    suffix = uuid4().hex[:8]
    try:
        material, location = await _seed(db_session, suffix)
        resp = await auth_client.post(
            "/api/v1/warehouse/movements",
            json={
                "direction": "inbound",
                "source_type": "production",
                "material_id": str(material.id),
                "batch_no": f"EXP-B2-{suffix}",
                "quantity": 3,
                "location_id": str(location.id),
            },
        )
        assert resp.status_code == 201, resp.text

        listed = await auth_client.get("/api/v1/warehouse/stocks")
        assert listed.status_code == 200
        row = next(
            item for item in listed.json()["data"] if item["batch_no"] == f"EXP-B2-{suffix}"
        )
        assert row["expiry_date"] is None
    finally:
        await _cleanup(db_session, suffix)
