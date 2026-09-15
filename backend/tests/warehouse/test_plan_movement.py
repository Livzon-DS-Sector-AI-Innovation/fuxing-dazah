"""计划单联动登记测试（Ticket 11）：从执行中计划生成出入库登记并完成回填。"""

from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import WarehouseLocation, WarehouseMaterial


async def _seed(db: AsyncSession) -> tuple[WarehouseMaterial, WarehouseLocation]:
    material = WarehouseMaterial(
        code=f"PMV-T-{uuid4().hex[:8]}", name="联动测试物料", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    location = WarehouseLocation(code=f"PMV-T-L{uuid4().hex[:8]}", name="联动测试库位")
    db.add_all([material, location])
    await db.commit()
    return material, location


async def _create_started_plan(auth_client: AsyncClient, material, location) -> str:
    created = await auth_client.post(
        "/api/v1/warehouse/plans",
        json={
            "direction": "inbound",
            "source_type": "purchase",
            "material_id": str(material.id),
            "batch_no": "PMV-B1",
            "quantity": 12,
            "location_id": str(location.id),
        },
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["data"]["id"]
    started = await auth_client.post(f"/api/v1/warehouse/plans/{plan_id}/start")
    assert started.status_code == 200
    return plan_id


async def _cleanup(db: AsyncSession, material_id, location_id) -> None:
    from sqlalchemy import delete

    from app.modules.warehouse.models import (
        WarehouseMovement,
        WarehouseMovementPlan,
        WarehouseStock,
    )

    await db.rollback()
    await db.execute(delete(WarehouseMovementPlan).where(WarehouseMovementPlan.material_id == material_id))
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id == material_id))
    await db.execute(delete(WarehouseMovement).where(WarehouseMovement.material_id == material_id))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id == location_id))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id == material_id))
    await db.commit()


async def test_generate_movement_completes_plan(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    material, location = await _seed(db_session)
    try:
        plan_id = await _create_started_plan(auth_client, material, location)

        resp = await auth_client.post(f"/api/v1/warehouse/plans/{plan_id}/movement")
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["movement"]["direction"] == "inbound"
        assert float(data["movement"]["quantity"]) == 12.0
        assert data["plan"]["status"] == "completed"
        assert data["plan"]["movement_id"] == data["movement"]["id"]

        # 库存已通过既有 createMovement 逻辑增加
        stocks = await auth_client.get("/api/v1/warehouse/stocks?page_size=50")
        stock_row = next(
            item
            for item in stocks.json()["data"]
            if item["material_id"] == str(material.id) and item["batch_no"] == "PMV-B1"
        )
        assert float(stock_row["quantity"]) == 12.0

        # 重复生成被拒
        again = await auth_client.post(f"/api/v1/warehouse/plans/{plan_id}/movement")
        assert again.status_code == 400
    finally:
        await _cleanup(db_session, material.id, location.id)


async def test_generate_requires_in_progress(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    material, location = await _seed(db_session)
    try:
        created = await auth_client.post(
            "/api/v1/warehouse/plans",
            json={
                "direction": "inbound",
                "source_type": "purchase",
                "material_id": str(material.id),
                "quantity": 3,
                "location_id": str(location.id),
            },
        )
        plan_id = created.json()["data"]["id"]

        # planned 状态直接生成 → 拒绝
        resp = await auth_client.post(f"/api/v1/warehouse/plans/{plan_id}/movement")
        assert resp.status_code == 400
    finally:
        await _cleanup(db_session, material.id, location.id)


async def test_generate_with_quantity_override(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    material, location = await _seed(db_session)
    try:
        plan_id = await _create_started_plan(auth_client, material, location)

        resp = await auth_client.post(
            f"/api/v1/warehouse/plans/{plan_id}/movement",
            json={"quantity": 7.5},
        )
        assert resp.status_code == 201, resp.text
        assert float(resp.json()["data"]["movement"]["quantity"]) == 7.5
    finally:
        await _cleanup(db_session, material.id, location.id)
