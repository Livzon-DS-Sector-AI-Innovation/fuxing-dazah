"""库存日快照测试：聚合口径、幂等覆盖、窗口守卫、互斥标志。"""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.modules.warehouse import snapshot as snapshot_module
from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseStock,
    WarehouseStockDailySnapshot,
)

CN_TZ = ZoneInfo("Asia/Shanghai")


async def _seed_material_with_stocks(db_session, code: str = "M-SNAP-001") -> WarehouseMaterial:
    """一个物料 + 两个库位的库存行 + 一行软删除库存。"""
    material = WarehouseMaterial(
        code=code, name="快照测试物料", category="raw", unit="kg", safety_stock=Decimal("10")
    )
    db_session.add(material)
    await db_session.flush()

    loc_a = WarehouseLocation(code=f"L-{code}-A", name="A 库位")
    loc_b = WarehouseLocation(code=f"L-{code}-B", name="B 库位")
    db_session.add_all([loc_a, loc_b])
    await db_session.flush()

    db_session.add_all(
        [
            WarehouseStock(
                material_id=material.id,
                material_code=material.code,
                material_name=material.name,
                batch_no="B1",
                location_id=loc_a.id,
                location_code=loc_a.code,
                location_name=loc_a.name,
                quantity=Decimal("100"),
            ),
            WarehouseStock(
                material_id=material.id,
                material_code=material.code,
                material_name=material.name,
                batch_no="B2",
                location_id=loc_b.id,
                location_code=loc_b.code,
                location_name=loc_b.name,
                quantity=Decimal("23.5"),
            ),
            # 软删除行不计入快照
            WarehouseStock(
                material_id=material.id,
                material_code=material.code,
                material_name=material.name,
                batch_no="B3",
                location_id=loc_a.id,
                location_code=loc_a.code,
                location_name=loc_a.name,
                quantity=Decimal("999"),
                is_deleted=True,
            ),
        ]
    )
    await db_session.flush()
    return material


async def test_snapshot_aggregates_only_live_stocks(db_session) -> None:
    material = await _seed_material_with_stocks(db_session)

    rows = await snapshot_module.build_stock_snapshot_rows(db_session, date(2026, 9, 15))

    assert len(rows) == 1
    row = rows[0]
    assert row["material_id"] == material.id
    assert row["material_code"] == "M-SNAP-001"
    assert row["total_quantity"] == Decimal("123.5")
    assert row["stock_rows"] == 2


async def test_snapshot_upsert_is_idempotent(db_session) -> None:
    await _seed_material_with_stocks(db_session)
    snapshot_date = date(2026, 9, 15)

    rows = await snapshot_module.build_stock_snapshot_rows(db_session, snapshot_date)
    assert await snapshot_module.upsert_snapshot_rows(db_session, rows) == len(rows)

    # 库存变化后同日重跑：覆盖而非新增
    stocks = (await db_session.execute(select(WarehouseStock))).scalars().all()
    for stock in stocks:
        if not stock.is_deleted:
            stock.quantity = Decimal("50")
    await db_session.flush()

    rows2 = await snapshot_module.build_stock_snapshot_rows(db_session, snapshot_date)
    await snapshot_module.upsert_snapshot_rows(db_session, rows2)

    saved = (
        (
            await db_session.execute(
                select(WarehouseStockDailySnapshot).where(
                    WarehouseStockDailySnapshot.snapshot_date == snapshot_date
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(saved) == 1
    assert saved[0].total_quantity == Decimal("100")  # 50 × 2 行


def test_snapshot_window_guard() -> None:
    assert snapshot_module.is_in_snapshot_window(datetime(2026, 9, 15, 0, 30, tzinfo=CN_TZ))
    assert snapshot_module.is_in_snapshot_window(datetime(2026, 9, 15, 5, 59, tzinfo=CN_TZ))
    assert not snapshot_module.is_in_snapshot_window(datetime(2026, 9, 15, 6, 0, tzinfo=CN_TZ))
    assert not snapshot_module.is_in_snapshot_window(datetime(2026, 9, 15, 12, 0, tzinfo=CN_TZ))


async def test_snapshot_mutex_skip(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    """已在运行时跳过本轮，且不清理他人的运行标志。"""
    monkeypatch.setattr(snapshot_module, "_snapshot_running", True)

    written = await snapshot_module.run_stock_daily_snapshot(date(2026, 9, 15))

    assert written == 0
    assert snapshot_module._snapshot_running is True
    monkeypatch.setattr(snapshot_module, "_snapshot_running", False)
