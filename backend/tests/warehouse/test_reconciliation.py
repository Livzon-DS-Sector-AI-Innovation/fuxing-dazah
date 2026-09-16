"""对账中心后端测试（分期C Ticket 05）：四态分类、失败处理、权限。"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseStock,
    WarehouseSyncCheckResult,
    WarehouseSyncCheckRun,
)

_PREFIX = "RCL-"


async def _seed(db: AsyncSession, suffix: str) -> dict[str, WarehouseMaterial]:
    m_match = WarehouseMaterial(
        code=f"{_PREFIX}MATCH-{suffix}", name="对账匹配", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    m_mif = WarehouseMaterial(
        code=f"{_PREFIX}MIF-{suffix}", name="飞书缺失", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    m_mis = WarehouseMaterial(
        code=f"{_PREFIX}MIS-{suffix}", name="数量不一致", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    loc = WarehouseLocation(code=f"{_PREFIX}LOC-{suffix}", name="对账库位")
    db.add_all([m_match, m_mif, m_mis, loc])
    await db.flush()
    db.add_all(
        [
            WarehouseStock(
                material_id=m_match.id, material_code=m_match.code,
                material_name=m_match.name, batch_no="B1",
                location_id=loc.id, location_code=loc.code, location_name=loc.name,
                quantity=Decimal("50"),
            ),
            WarehouseStock(
                material_id=m_mif.id, material_code=m_mif.code,
                material_name=m_mif.name, batch_no="B2",
                location_id=loc.id, location_code=loc.code, location_name=loc.name,
                quantity=Decimal("30"),
            ),
            WarehouseStock(
                material_id=m_mis.id, material_code=m_mis.code,
                material_name=m_mis.name, batch_no="B3",
                location_id=loc.id, location_code=loc.code, location_name=loc.name,
                quantity=Decimal("20"),
            ),
        ]
    )
    await db.commit()
    return {"match": m_match, "mif": m_mif, "mis": m_mis, "loc": loc}


async def _cleanup(db: AsyncSession, materials: dict) -> None:

    from app.modules.warehouse.models import WarehouseMovement

    await db.rollback()
    # 先删子表再删父表（FK 依赖链）
    await db.execute(delete(WarehouseSyncCheckResult))
    await db.execute(delete(WarehouseSyncCheckRun))
    ids = [m.id for m in materials.values() if hasattr(m, "id")]
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(ids)))
    await db.execute(delete(WarehouseMovement).where(WarehouseMovement.material_id.in_(ids)))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id == materials["loc"].id))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id.in_(ids)))
    await db.commit()


async def test_reconciliation_four_states(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    suffix = uuid.uuid4().hex[:8]
    materials = await _seed(db_session, suffix)
    try:
        fake_feishu = [
            {"record_id": "fr1", "fields": {"物料编码": materials["match"].code, "批次": "B1", "可用库存": 50}},
            {"record_id": "fr2", "fields": {"物料编码": materials["mis"].code, "批次": "B3", "可用库存": 35}},
        ]
        mock_adapter = MagicMock()
        mock_adapter.search_records_page = AsyncMock(return_value={
            "records": fake_feishu, "total": len(fake_feishu), "page_token": None,
        })
        with patch(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            return_value=mock_adapter,
        ):
            resp = await auth_client.post("/api/v1/warehouse/reconciliation/run")
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["status"] == "completed"
        # match 1: 本地 50 == 飞书 50
        assert data["cnt_match"] >= 1
        # 飞书缺失: mif 本地有但飞书无
        assert data["cnt_missing_in_feishu"] >= 1
        # 数量不一致: mis 本地 20 ≠ 飞书 35
        assert data["cnt_mismatch"] >= 1

        results = await auth_client.get(
            f"/api/v1/warehouse/reconciliation/runs/{data['run_id']}/results?status=mismatch"
        )
        assert results.status_code == 200
        items = results.json()["data"]
        assert len(items) >= 1
        assert any(i["material_code"].startswith(f"{_PREFIX}MIS") for i in items)
    finally:
        await _cleanup(db_session, materials)


async def test_reconciliation_adapter_failure(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    suffix = uuid.uuid4().hex[:8]
    materials = await _seed(db_session, suffix)
    try:
        mock_adapter = MagicMock()
        mock_adapter.search_records_page = AsyncMock(side_effect=RuntimeError("feishu down"))
        with patch(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            return_value=mock_adapter,
        ):
            resp = await auth_client.post("/api/v1/warehouse/reconciliation/run")
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["status"] == "failed"
        assert data["error_message"]
    finally:
        await _cleanup(db_session, materials)


async def test_reconciliation_requires_permission(
    auth_client: AsyncClient, monkeypatch
) -> None:
    from app.platform.permission import deps as permission_deps

    async def _limited(user_id: str, db: AsyncSession) -> set[str]:
        return {"warehouse:stock:read"}

    monkeypatch.setattr(permission_deps, "get_user_permissions", _limited)
    resp = await auth_client.post("/api/v1/warehouse/reconciliation/run")
    assert resp.status_code == 403
