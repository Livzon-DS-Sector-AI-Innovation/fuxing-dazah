"""先 Base 后镜像 helper 测试（V3.0 分期A Ticket 06）。

接缝：服务函数级——FakeAdapter 注入（构造零依赖），断言
「Base 成功 → 本地写；Base 失败/定位失败 → 本地零变更」。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse import base_mirror
from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseStock,
    WarehouseStockStatusLog,
)


class FakeAdapter:
    """零网络假适配器：search 命中 rec_ok；update 可注入失败批次。"""

    def __init__(self, *, fail_batches: set[str] | None = None) -> None:
        self.fail_batches = fail_batches or set()
        self.update_calls: list[tuple[str, str, dict[str, Any]]] = []

    async def search_records_page(
        self, table_key: str, **kwargs: Any
    ) -> dict[str, Any]:
        return {"records": [{"record_id": "rec_ok", "fields": {}}], "total": 1, "page_token": None}

    async def update_record(
        self, table_key: str, record_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        self.update_calls.append((table_key, record_id, dict(fields)))
        if record_id in self.fail_batches or fields.get("物料批号") in self.fail_batches:
            raise RuntimeError("Base 写入被拒")
        return {"record_id": record_id, "fields": {}}


class EmptyAdapter(FakeAdapter):
    """定位不到记录的假适配器。"""

    async def search_records_page(
        self, table_key: str, **kwargs: Any
    ) -> dict[str, Any]:
        return {"records": [], "total": 0, "page_token": None}


async def _seed_stock(db: AsyncSession, suffix: str) -> WarehouseStock:
    m = WarehouseMaterial(
        code=f"BM-M-{suffix}", name="镜像测试物料", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    loc = WarehouseLocation(code=f"BM-L-{suffix}", name="镜像测试库位")
    db.add_all([m, loc])
    await db.flush()
    stock = WarehouseStock(
        material_id=m.id, material_code=m.code, material_name=m.name,
        batch_no=f"BMB{suffix}", location_id=loc.id, location_code=loc.code,
        location_name=loc.name, quantity=Decimal("10"),
    )
    db.add(stock)
    await db.flush()
    return stock


async def _logs_of(db: AsyncSession, stock: WarehouseStock) -> list[WarehouseStockStatusLog]:
    rows = (
        await db.execute(
            select(WarehouseStockStatusLog).where(
                WarehouseStockStatusLog.stock_id == stock.id
            )
        )
    ).scalars().all()
    return list(rows)


@pytest.fixture(autouse=True)
def _writeback_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认开启回写（生产默认关；本文件测试先 Base 后镜像主路径）。

    关闭路径由 test_disabled_switch_writes_local_only 显式覆盖。
    """
    monkeypatch.setattr(base_mirror, "bitable_writeback_enabled", lambda: True)


class TestBaseMirror:
    def test_status_mapping(self) -> None:
        assert base_mirror.STOCK_STATUS_TO_BASE == {
            "normal": "合格",
            "quarantine": "待检",
            "frozen": "不合格",
        }

    async def test_disabled_switch_writes_local_only(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回写开关关闭（生产默认）：本地直写，不触 Base，返回 None。"""
        monkeypatch.setattr(base_mirror, "bitable_writeback_enabled", lambda: False)
        adapter = FakeAdapter()
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        record_id = await base_mirror.apply_stock_status_base_first(
            db_session, stock, "frozen", adapter=adapter
        )
        assert record_id is None
        assert adapter.update_calls == []  # 零 Base 调用
        assert stock.status == "frozen"  # 本地直写生效
        assert len(await _logs_of(db_session, stock)) == 1

    async def test_base_success_then_local_written(
        self, db_session: AsyncSession
    ) -> None:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        adapter = FakeAdapter()
        record_id = await base_mirror.apply_stock_status_base_first(
            db_session, stock, "quarantine", reason="质检待检", adapter=adapter
        )
        assert record_id == "rec_ok"
        # Base 写入内容：material_receipt.上一状态 = 待检
        assert adapter.update_calls == [("material_receipt", "rec_ok", {"上一状态": "待检"})]
        # 本地镜像：状态 + 日志
        assert stock.status == "quarantine"
        logs = await _logs_of(db_session, stock)
        assert len(logs) == 1
        assert (logs[0].old_status, logs[0].new_status) == ("normal", "quarantine")

    async def test_base_failure_local_unchanged(
        self, db_session: AsyncSession
    ) -> None:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        adapter = FakeAdapter(fail_batches={"rec_ok"})
        with pytest.raises(base_mirror.BaseMirrorError, match="Base 写入失败"):
            await base_mirror.apply_stock_status_base_first(
                db_session, stock, "frozen", adapter=adapter
            )
        assert stock.status == "normal"  # 本地零变更
        assert await _logs_of(db_session, stock) == []

    async def test_record_not_found_rejected(
        self, db_session: AsyncSession
    ) -> None:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        with pytest.raises(base_mirror.BaseMirrorError, match="未找到对应记录"):
            await base_mirror.apply_stock_status_base_first(
                db_session, stock, "frozen", adapter=EmptyAdapter()
            )
        assert stock.status == "normal"
        assert await _logs_of(db_session, stock) == []

    async def test_unknown_status_rejected(
        self, db_session: AsyncSession
    ) -> None:
        stock = await _seed_stock(db_session, uuid4().hex[:6])
        with pytest.raises(base_mirror.BaseMirrorError, match="未知的库存状态"):
            await base_mirror.apply_stock_status_base_first(
                db_session, stock, "exploded", adapter=FakeAdapter()
            )
