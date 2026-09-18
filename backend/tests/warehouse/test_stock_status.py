"""库存状态机测试（分期D Ticket 03 → V3.0 分期A Ticket 06 先 Base 后镜像）。

改造后语义：Web 状态变更先写 Base（material_receipt.上一状态，三态映射
合格/待检/不合格）再落本地；Base 失败 502 且本地零变更；非法流转仍 400。
Base 交互经 monkeypatch base_mirror.WarehouseBitableAdapter 为零网络假件。
"""

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse import base_mirror
from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseMovement,
    WarehouseStock,
    WarehouseStockStatusLog,
)


class FakeBaseAdapter:
    """零网络假适配器：按物料批号返回 record_id；fail_update 注入失败。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.update_calls: list[tuple[str, str, dict[str, Any]]] = []

    async def search_records_page(
        self, table_key: str, **kwargs: Any
    ) -> dict[str, Any]:
        value = (kwargs.get("filter_json") or {}).get("conditions", [{}])[0].get("value", [""])[0]
        return {
            "records": [{"record_id": f"rec_{value}", "fields": {}}],
            "total": 1,
            "page_token": None,
        }

    async def update_record(
        self, table_key: str, record_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        self.update_calls.append((table_key, record_id, dict(fields)))
        if self.fail:
            raise RuntimeError("Base 写入被拒")
        return {"record_id": record_id, "fields": {}}


def _patch_base(
    monkeypatch: pytest.MonkeyPatch, *, writeback: bool = True, **kwargs: Any
) -> FakeBaseAdapter:
    """注入 Base 假件并设定回写开关（默认开，测先 Base 后镜像主路径）。"""
    adapter = FakeBaseAdapter(**kwargs)
    monkeypatch.setattr(base_mirror, "WarehouseBitableAdapter", lambda: adapter)
    monkeypatch.setattr(base_mirror, "bitable_writeback_enabled", lambda: writeback)
    return adapter


async def _seed_stock(db: AsyncSession, suffix: str) -> WarehouseStock:
    m = WarehouseMaterial(
        code=f"STS-{suffix}", name="状态机测试物料", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    loc = WarehouseLocation(code=f"STS-L{suffix}", name="状态机测试库位")
    db.add_all([m, loc])
    await db.flush()
    stock = WarehouseStock(
        material_id=m.id, material_code=m.code, material_name=m.name,
        batch_no=f"SB{suffix}", location_id=loc.id, location_code=loc.code,
        location_name=loc.name, quantity=Decimal("50"),
    )
    db.add(stock)
    await db.commit()
    return stock


async def _cleanup(db: AsyncSession) -> None:
    from sqlalchemy import delete

    await db.rollback()
    m_ids = select(WarehouseMaterial.id).where(WarehouseMaterial.code.like("STS-%"))
    l_ids = select(WarehouseLocation.id).where(WarehouseLocation.code.like("STS-%"))
    s_ids = select(WarehouseStock.id).where(WarehouseStock.material_id.in_(m_ids))
    await db.execute(delete(WarehouseStockStatusLog).where(
        WarehouseStockStatusLog.stock_id.in_(s_ids)
    ))
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(m_ids)))
    await db.execute(delete(WarehouseMovement).where(WarehouseMovement.material_id.in_(m_ids)))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id.in_(l_ids)))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id.in_(m_ids)))
    await db.commit()


async def test_normal_to_quarantine_base_first(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _patch_base(monkeypatch)
    try:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        resp = await auth_client.post(
            f"/api/v1/warehouse/stocks/{stock.id}/status",
            json={"new_status": "quarantine", "reason": "质检待检"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["new_status"] == "quarantine"
        # 先 Base 后本地：上一状态=待检（quarantine 映射）
        assert adapter.update_calls[0][2] == {"上一状态": "待检"}
    finally:
        await _cleanup(db_session)


async def test_base_failure_returns_502_local_unchanged(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_base(monkeypatch, fail=True)
    try:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        resp = await auth_client.post(
            f"/api/v1/warehouse/stocks/{stock.id}/status",
            json={"new_status": "quarantine", "reason": "质检待检"},
        )
        assert resp.status_code == 502
        assert "Base 台账写入失败" in resp.json()["message"]
        # 本地零变更
        await db_session.rollback()
        fresh = (
            await db_session.execute(
                select(WarehouseStock).where(WarehouseStock.id == stock.id)
            )
        ).scalar_one()
        assert fresh.status == "normal"
        logs = (
            await db_session.execute(
                select(WarehouseStockStatusLog).where(
                    WarehouseStockStatusLog.stock_id == stock.id
                )
            )
        ).scalars().all()
        assert logs == []
    finally:
        await _cleanup(db_session)


async def test_status_change_local_only_when_writeback_disabled(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回写开关关闭（生产默认）：状态变更本地直写，零 Base 调用。"""
    adapter = _patch_base(monkeypatch, writeback=False)
    try:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        resp = await auth_client.post(
            f"/api/v1/warehouse/stocks/{stock.id}/status",
            json={"new_status": "quarantine", "reason": "质检待检"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["new_status"] == "quarantine"
        assert adapter.update_calls == []  # 零 Base 调用
        # 本地状态 + 日志正常落（client 会话提交，refresh 绕过身份映射旧值）
        await db_session.rollback()
        fresh = (
            await db_session.execute(
                select(WarehouseStock).where(WarehouseStock.id == stock.id)
            )
        ).scalar_one()
        await db_session.refresh(fresh)
        assert fresh.status == "quarantine"
        logs = (
            await db_session.execute(
                select(WarehouseStockStatusLog).where(
                    WarehouseStockStatusLog.stock_id == stock.id
                )
            )
        ).scalars().all()
        assert len(logs) == 1
    finally:
        await _cleanup(db_session)


async def test_invalid_transition_rejected(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _patch_base(monkeypatch)
    try:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        # normal → frozen 直接跳转不允许（不触达 Base）
        resp = await auth_client.post(
            f"/api/v1/warehouse/stocks/{stock.id}/status",
            json={"new_status": "frozen", "reason": "跳过待检"},
        )
        assert resp.status_code == 400
        assert adapter.update_calls == []
    finally:
        await _cleanup(db_session)


async def test_status_log_written(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_base(monkeypatch)
    try:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        await auth_client.post(
            f"/api/v1/warehouse/stocks/{stock.id}/status",
            json={"new_status": "quarantine", "reason": "质检待检"},
        )
        logs = (
            await db_session.execute(
                select(WarehouseStockStatusLog).where(
                    WarehouseStockStatusLog.stock_id == stock.id
                )
            )
        ).scalars().all()
        assert len(logs) >= 1
        assert logs[0].old_status == "normal"
        assert logs[0].new_status == "quarantine"
    finally:
        await _cleanup(db_session)


async def test_stock_list_status_filter(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """库存列表按状态筛选（分期D Ticket 03 前端筛选的后端支撑）。"""
    _patch_base(monkeypatch)
    try:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        await auth_client.post(
            f"/api/v1/warehouse/stocks/{stock.id}/status",
            json={"new_status": "quarantine", "reason": "质检待检"},
        )
        batch = stock.batch_no

        listed = await auth_client.get(
            "/api/v1/warehouse/stocks",
            params={"batch_no": batch, "status": "quarantine"},
        )
        assert listed.status_code == 200, listed.text
        items = listed.json()["data"]
        assert len(items) == 1
        assert items[0]["id"] == str(stock.id)
        assert items[0]["status"] == "quarantine"

        empty = await auth_client.get(
            "/api/v1/warehouse/stocks",
            params={"batch_no": batch, "status": "frozen"},
        )
        assert empty.status_code == 200
        assert empty.json()["data"] == []
    finally:
        await _cleanup(db_session)
