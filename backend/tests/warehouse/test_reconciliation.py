"""对账中心后端测试（分期C → V3.0 分期A Ticket 09 裁决反转）。

覆盖：四态分类（修正后键名 代码/物料批号/剩余数量，含单选数组解析）、
Base 胜出标注、人工一键修复三态（mismatch 调数 / missing_local 补行 /
missing_in_feishu 仅标记）、重复修复拒绝、失败处理、权限。
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient
from sqlalchemy import delete, select
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
    m_ml = WarehouseMaterial(
        code=f"{_PREFIX}ML-{suffix}", name="本地缺失", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    loc = WarehouseLocation(code=f"{_PREFIX}LOC-{suffix}", name="对账库位")
    db.add_all([m_match, m_mif, m_mis, m_ml, loc])
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
    return {"match": m_match, "mif": m_mif, "mis": m_mis, "ml": m_ml, "loc": loc}


def _fake_feishu_rows(materials: dict) -> list[dict]:
    """模拟 material_stock 记录（修正后键名；物料批号单选读取为数组）。"""
    return [
        {"record_id": "fr1", "fields": {
            "代码": materials["match"].code, "物料批号": ["B1"], "剩余数量": 50}},
        {"record_id": "fr2", "fields": {
            "代码": materials["mis"].code, "物料批号": ["B3"], "剩余数量": 35}},
        {"record_id": "fr3", "fields": {
            "代码": materials["ml"].code, "物料批号": "B9", "剩余数量": 42}},
    ]


def _patch_adapter(monkeypatch, fake_feishu: list[dict]) -> MagicMock:
    mock_adapter = MagicMock()
    mock_adapter.search_records_page = AsyncMock(return_value={
        "records": fake_feishu, "total": len(fake_feishu), "page_token": None,
    })
    monkeypatch.setattr(
        "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
        lambda: mock_adapter,
    )
    return mock_adapter


async def _cleanup(db: AsyncSession, materials: dict) -> None:
    from app.modules.warehouse.models import WarehouseMovement

    # 先取 id 再 rollback（rollback 会过期会话内对象，属性访问触发隐式 IO）
    ids = [m.id for m in materials.values() if hasattr(m, "id")]
    await db.rollback()
    # 先删子表再删父表（FK 依赖链）
    await db.execute(delete(WarehouseSyncCheckResult))
    await db.execute(delete(WarehouseSyncCheckRun))
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(ids)))
    await db.execute(delete(WarehouseMovement).where(WarehouseMovement.material_id.in_(ids)))
    await db.execute(
        delete(WarehouseLocation).where(
            WarehouseLocation.code.like(f"{_PREFIX}%")
        )
    )
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id.in_(ids)))
    await db.commit()


async def _run_reconciliation(
    auth_client: AsyncClient, monkeypatch, materials: dict
) -> dict:
    _patch_adapter(monkeypatch, _fake_feishu_rows(materials))
    resp = await auth_client.post("/api/v1/warehouse/reconciliation/run")
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def test_reconciliation_four_states(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    suffix = uuid.uuid4().hex[:8]
    materials = await _seed(db_session, suffix)
    try:
        data = await _run_reconciliation(auth_client, monkeypatch, materials)
        assert data["status"] == "completed"
        # match: 本地 50 == 飞书 50（键名修正后命中）
        assert data["cnt_match"] >= 1
        # 飞书缺失: mif 本地有但飞书无
        assert data["cnt_missing_in_feishu"] >= 1
        # 数量不一致: mis 本地 20 ≠ 飞书 35
        assert data["cnt_mismatch"] >= 1
        # 本地缺失: ml 飞书有但本地无库存行
        assert data["cnt_missing_local"] >= 1

        # 差异明细带「Base 胜出」裁决标注 + id（修复按钮定位用）
        results = await auth_client.get(
            f"/api/v1/warehouse/reconciliation/runs/{data['run_id']}/results?status=mismatch"
        )
        assert results.status_code == 200
        items = results.json()["data"]
        assert len(items) >= 1
        mismatch = [i for i in items if i["material_code"].startswith(f"{_PREFIX}MIS")][0]
        assert mismatch["detail"]["verdict"] == "base_wins"
        assert mismatch["detail"]["suggested_action"] == "repair_local"
        assert mismatch["id"]
    finally:
        await _cleanup(db_session, materials)


async def test_repair_mismatch_adjusts_local_quantity(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    suffix = uuid.uuid4().hex[:8]
    materials = await _seed(db_session, suffix)
    try:
        data = await _run_reconciliation(auth_client, monkeypatch, materials)
        results = await auth_client.get(
            f"/api/v1/warehouse/reconciliation/runs/{data['run_id']}/results?status=mismatch"
        )
        row = [
            i for i in results.json()["data"]
            if i["material_code"] == materials["mis"].code
        ][0]

        resp = await auth_client.post(
            f"/api/v1/warehouse/reconciliation/results/{row['id']}/repair"
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["repair_status"] == "repaired"

        # 本地数量调整为 Base 值（20 → 35）
        stock = (
            await db_session.execute(
                select(WarehouseStock).where(
                    WarehouseStock.material_code == materials["mis"].code
                )
            )
        ).scalars().one()
        await db_session.refresh(stock)
        assert float(stock.quantity) == 35.0

        # 重复修复拒绝
        resp = await auth_client.post(
            f"/api/v1/warehouse/reconciliation/results/{row['id']}/repair"
        )
        assert resp.status_code == 409
    finally:
        await _cleanup(db_session, materials)


async def test_repair_missing_local_creates_stock_row(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    suffix = uuid.uuid4().hex[:8]
    materials = await _seed(db_session, suffix)
    try:
        data = await _run_reconciliation(auth_client, monkeypatch, materials)
        results = await auth_client.get(
            f"/api/v1/warehouse/reconciliation/runs/{data['run_id']}/results?status=missing_local"
        )
        row = [
            i for i in results.json()["data"]
            if i["material_code"] == materials["ml"].code
        ][0]

        resp = await auth_client.post(
            f"/api/v1/warehouse/reconciliation/results/{row['id']}/repair"
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["repair_status"] == "repaired"

        # 补建本地行：数量=Base 值，库位=对账补录
        stocks = (
            await db_session.execute(
                select(WarehouseStock).where(
                    WarehouseStock.material_code == materials["ml"].code
                )
            )
        ).scalars().all()
        assert len(stocks) == 1
        await db_session.refresh(stocks[0])
        assert float(stocks[0].quantity) == 42.0
        assert stocks[0].location_code == "RECON-IMPORT"
        assert stocks[0].batch_no == "B9"
    finally:
        await _cleanup(db_session, materials)


async def test_repair_missing_in_feishu_marks_manual(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    suffix = uuid.uuid4().hex[:8]
    materials = await _seed(db_session, suffix)
    try:
        data = await _run_reconciliation(auth_client, monkeypatch, materials)
        results = await auth_client.get(
            f"/api/v1/warehouse/reconciliation/runs/{data['run_id']}/results?status=missing_in_feishu"
        )
        row = [
            i for i in results.json()["data"]
            if i["material_code"] == materials["mif"].code
        ][0]

        resp = await auth_client.post(
            f"/api/v1/warehouse/reconciliation/results/{row['id']}/repair"
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["repair_status"] == "manual"

        # 本地多出：不删数据，数量保持
        stocks = (
            await db_session.execute(
                select(WarehouseStock).where(
                    WarehouseStock.material_code == materials["mif"].code
                )
            )
        ).scalars().all()
        assert len(stocks) == 1
        await db_session.refresh(stocks[0])
        assert float(stocks[0].quantity) == 30.0
    finally:
        await _cleanup(db_session, materials)


async def test_repair_unknown_result_404(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await auth_client.post(
        f"/api/v1/warehouse/reconciliation/results/{uuid.uuid4()}/repair"
    )
    assert resp.status_code == 404


async def test_reconciliation_adapter_failure(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    suffix = uuid.uuid4().hex[:8]
    materials = await _seed(db_session, suffix)
    try:
        mock_adapter = MagicMock()
        mock_adapter.search_records_page = AsyncMock(side_effect=RuntimeError("feishu down"))
        monkeypatch.setattr(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            lambda: mock_adapter,
        )
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
