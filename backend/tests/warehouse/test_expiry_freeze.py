"""效期自动冻结测试（分期D Ticket 04）：冻结范围、日志、通知、窗口守卫。"""

from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse import expiry_freeze, scheduled
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseStock,
    WarehouseStockStatusLog,
)

_PREFIX = f"EXPF-{uuid4().hex[:6]}-"


async def _seed_stock(
    db: AsyncSession, *, suffix: str, expiry_offset_days: int, status: str = "normal"
) -> WarehouseStock:
    """seed 物料+库位+库存行；expiry_offset_days<0 表示已过期。"""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    m = WarehouseMaterial(
        code=f"{_PREFIX}M{suffix}", name="效期冻结测试物料", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    loc = WarehouseLocation(code=f"{_PREFIX}L{suffix}", name="效期冻结测试库位")
    db.add_all([m, loc])
    await db.flush()
    expiry = (
        datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=expiry_offset_days)
    ).date()
    stock = WarehouseStock(
        material_id=m.id, material_code=m.code, material_name=m.name,
        batch_no=f"EB{suffix}", location_id=loc.id, location_code=loc.code,
        location_name=loc.name, quantity=Decimal("10"), expiry_date=expiry,
        status=status,
    )
    db.add(stock)
    await db.commit()
    return stock


async def _cleanup(db: AsyncSession) -> None:
    from sqlalchemy import delete

    await db.rollback()
    m_ids = select(WarehouseMaterial.id).where(WarehouseMaterial.code.like(f"{_PREFIX}%"))
    l_ids = select(WarehouseLocation.id).where(WarehouseLocation.code.like(f"{_PREFIX}%"))
    s_ids = select(WarehouseStock.id).where(WarehouseStock.material_id.in_(m_ids))
    await db.execute(delete(WarehouseStockStatusLog).where(
        WarehouseStockStatusLog.stock_id.in_(s_ids)
    ))
    await db.execute(delete(WarehouseStock).where(WarehouseStock.material_id.in_(m_ids)))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.id.in_(l_ids)))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.id.in_(m_ids)))
    await db.commit()


async def test_freeze_only_expired_normal_rows(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        expired = await _seed_stock(db_session, suffix="1", expiry_offset_days=-3)
        future = await _seed_stock(db_session, suffix="2", expiry_offset_days=60)
        quarantined = await _seed_stock(
            db_session, suffix="3", expiry_offset_days=-1, status="quarantine"
        )

        changed = await expiry_freeze.freeze_expired_stocks(db_session)

        assert [row["stock_id"] for row in changed] == [str(expired.id)]
        # 同一会话身份映射：内存对象即查询对象，未 flush 前不可 refresh（会覆盖回 DB 旧值）
        assert expired.status == "frozen"
        assert future.status == "normal"
        assert quarantined.status == "quarantine"

        # 流转日志：old=normal → new=frozen，operator 为空（系统）
        logs = (
            await db_session.execute(
                select(WarehouseStockStatusLog).where(
                    WarehouseStockStatusLog.stock_id == expired.id
                )
            )
        ).scalars().all()
        assert len(logs) == 1
        assert logs[0].old_status == "normal"
        assert logs[0].new_status == "frozen"
        assert logs[0].operator_id is None

        # 幂等：重复执行不再产生变更
        assert await expiry_freeze.freeze_expired_stocks(db_session) == []
    finally:
        await _cleanup(db_session)


async def test_notify_sent_to_configured_chat(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    try:
        await _seed_stock(db_session, suffix="1", expiry_offset_days=-3)
        changed = await expiry_freeze.freeze_expired_stocks(db_session)

        monkeypatch.setattr(
            expiry_freeze,
            "get_settings",
            lambda: type("S", (), {"WAREHOUSE_ALERT_CHAT_ID": "oc_test"})(),
        )
        send_mock = AsyncMock(return_value="om_test")
        monkeypatch.setattr(notification, "send_card", send_mock)

        assert await expiry_freeze.notify_expired_freeze(changed) is True
        send_mock.assert_awaited_once()
        call = send_mock.await_args
        assert call is not None
        assert call.args[0] == "oc_test"
        assert "已自动冻结" in str(call.args[1])
    finally:
        await _cleanup(db_session)


async def test_notify_skipped_without_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        expiry_freeze,
        "get_settings",
        lambda: type("S", (), {"WAREHOUSE_ALERT_CHAT_ID": ""})(),
    )
    send_mock = AsyncMock(return_value="om_x")
    monkeypatch.setattr(notification, "send_card", send_mock)

    assert await expiry_freeze.notify_expired_freeze([{"material_code": "X"}]) is False
    send_mock.assert_not_awaited()
    # 无变更同样跳过
    monkeypatch.setattr(
        expiry_freeze,
        "get_settings",
        lambda: type("S", (), {"WAREHOUSE_ALERT_CHAT_ID": "oc_test"})(),
    )
    assert await expiry_freeze.notify_expired_freeze([]) is False
    send_mock.assert_not_awaited()


async def test_scheduled_wrapper_window_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    freeze_mock = AsyncMock(return_value=[])
    notify_mock = AsyncMock(return_value=False)
    monkeypatch.setattr(expiry_freeze, "freeze_expired_stocks", freeze_mock)
    monkeypatch.setattr(expiry_freeze, "notify_expired_freeze", notify_mock)

    # 窗口外（守卫借用 scheduled 模块内引用）直接跳过
    monkeypatch.setattr(scheduled, "is_in_snapshot_window", lambda now: False)
    await scheduled._run_scheduled_expiry_freeze()
    freeze_mock.assert_not_awaited()

    # 窗口内执行冻结+通知
    monkeypatch.setattr(scheduled, "is_in_snapshot_window", lambda now: True)
    await scheduled._run_scheduled_expiry_freeze()
    freeze_mock.assert_awaited_once()
    notify_mock.assert_awaited_once()
