"""出入库计划单测试（Ticket 10）：CRUD、状态机、权限。"""

from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import WarehouseLocation, WarehouseMaterial


async def _seed(db: AsyncSession) -> tuple[WarehouseMaterial, WarehouseLocation]:
    material = WarehouseMaterial(
        code=f"PLAN-T-{uuid4().hex[:8]}", name="计划单测试物料", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    location = WarehouseLocation(code=f"PLAN-T-L{uuid4().hex[:8]}", name="计划单测试库位")
    db.add_all([material, location])
    await db.commit()
    return material, location


async def _cleanup(db: AsyncSession, material_id, location_id) -> None:
    from sqlalchemy import delete

    from app.modules.warehouse.models import WarehouseMovementPlan, WarehouseStock

    await db.rollback()
    await db.execute(delete(WarehouseMovementPlan).where(WarehouseMovementPlan.material_id == material_id))
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id == material_id))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id == location_id))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id == material_id))
    await db.commit()


async def test_create_and_get_plan(auth_client: AsyncClient, db_session: AsyncSession) -> None:
    material, location = await _seed(db_session)
    try:
        created = await auth_client.post(
            "/api/v1/warehouse/plans",
            json={
                "direction": "inbound",
                "source_type": "purchase",
                "material_id": str(material.id),
                "batch_no": "PB1",
                "quantity": 25,
                "location_id": str(location.id),
            },
        )
        assert created.status_code == 201, created.text
        plan = created.json()["data"]
        assert plan["status"] == "planned"
        assert plan["plan_no"].startswith("IP")

        fetched = await auth_client.get(f"/api/v1/warehouse/plans/{plan['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["data"]["plan_no"] == plan["plan_no"]
    finally:
        await _cleanup(db_session, material.id, location.id)


async def test_plan_state_machine(auth_client: AsyncClient, db_session: AsyncSession) -> None:
    material, location = await _seed(db_session)
    try:
        created = await auth_client.post(
            "/api/v1/warehouse/plans",
            json={
                "direction": "outbound",
                "source_type": "production",
                "material_id": str(material.id),
                "quantity": 5,
                "location_id": str(location.id),
            },
        )
        plan_id = created.json()["data"]["id"]

        # planned → in_progress
        started = await auth_client.post(f"/api/v1/warehouse/plans/{plan_id}/start")
        assert started.status_code == 200
        assert started.json()["data"]["status"] == "in_progress"

        # in_progress → 不可再 start
        again = await auth_client.post(f"/api/v1/warehouse/plans/{plan_id}/start")
        assert again.status_code == 400

        # in_progress → cancelled（必填原因）
        cancelled = await auth_client.post(
            f"/api/v1/warehouse/plans/{plan_id}/cancel",
            json={"reason": "生产计划变更"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["data"]["status"] == "cancelled"

        # cancelled → 不可再取消
        twice = await auth_client.post(
            f"/api/v1/warehouse/plans/{plan_id}/cancel",
            json={"reason": "重复取消"},
        )
        assert twice.status_code == 400
    finally:
        await _cleanup(db_session, material.id, location.id)


async def test_cancel_reason_required(auth_client: AsyncClient, db_session: AsyncSession) -> None:
    material, location = await _seed(db_session)
    try:
        created = await auth_client.post(
            "/api/v1/warehouse/plans",
            json={
                "direction": "inbound",
                "source_type": "purchase",
                "material_id": str(material.id),
                "quantity": 1,
                "location_id": str(location.id),
            },
        )
        plan_id = created.json()["data"]["id"]

        missing = await auth_client.post(
            f"/api/v1/warehouse/plans/{plan_id}/cancel", json={}
        )
        assert missing.status_code == 422
    finally:
        await _cleanup(db_session, material.id, location.id)


async def test_list_plans_filter_status(
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
                "quantity": 8,
                "location_id": str(location.id),
            },
        )
        plan_no = created.json()["data"]["plan_no"]

        listed = await auth_client.get("/api/v1/warehouse/plans?status=planned&keyword=PLAN-T")
        assert listed.status_code == 200
        body = listed.json()
        assert body["meta"]["total"] >= 1
        assert all(item["status"] == "planned" for item in body["data"])
        assert any(item["plan_no"] == plan_no for item in body["data"])
    finally:
        await _cleanup(db_session, material.id, location.id)


async def test_create_plan_without_permission(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    from app.platform.permission import deps as permission_deps

    material, location = await _seed(db_session)
    try:
        async def _limited(user_id: str, db: AsyncSession) -> set[str]:
            return {"warehouse:plans:list"}

        monkeypatch.setattr(permission_deps, "get_user_permissions", _limited)

        resp = await auth_client.post(
            "/api/v1/warehouse/plans",
            json={
                "direction": "inbound",
                "source_type": "purchase",
                "material_id": str(material.id),
                "quantity": 1,
                "location_id": str(location.id),
            },
        )
        assert resp.status_code == 403
    finally:
        await _cleanup(db_session, material.id, location.id)
