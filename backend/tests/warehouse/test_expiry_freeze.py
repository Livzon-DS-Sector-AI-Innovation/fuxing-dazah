"""效期自动冻结测试（分期D Ticket 04 → V3.0 分期A Ticket 06 先 Base 后镜像）。

改造后语义：冻结 = 先写 Base（material_receipt.上一状态=不合格）再落本地
frozen；Base 失败条目跳过不回滚已成功条目；通知目标走 DB→env 回退链。
Base 交互经 monkeypatch base_mirror.WarehouseBitableAdapter 为零网络假件。
"""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse import base_mirror, expiry_freeze, scheduled
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseStock,
    WarehouseStockStatusLog,
)

_PREFIX = f"EXPF-{uuid4().hex[:6]}-"


class FakeBaseAdapter:
    """零网络假适配器：按物料批号返回 record_id；fail_batches 注入失败。"""

    def __init__(self, *, fail_batches: set[str] | None = None) -> None:
        self.fail_batches = fail_batches or set()
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
        batch = record_id.removeprefix("rec_")
        if batch in self.fail_batches:
            raise RuntimeError("Base 写入被拒")
        return {"record_id": record_id, "fields": {}}


def _patch_base(
    monkeypatch: pytest.MonkeyPatch, *, writeback: bool = True, **kwargs: Any
) -> FakeBaseAdapter:
    """注入 Base 假件并设定回写开关（默认开，测先 Base 后本地主路径）。"""
    adapter = FakeBaseAdapter(**kwargs)
    monkeypatch.setattr(base_mirror, "WarehouseBitableAdapter", lambda: adapter)
    monkeypatch.setattr(base_mirror, "bitable_writeback_enabled", lambda: writeback)
    return adapter


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
    auth_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _patch_base(monkeypatch)
    try:
        expired = await _seed_stock(db_session, suffix="1", expiry_offset_days=-3)
        future = await _seed_stock(db_session, suffix="2", expiry_offset_days=60)
        quarantined = await _seed_stock(
            db_session, suffix="3", expiry_offset_days=-1, status="quarantine"
        )

        result = await expiry_freeze.freeze_expired_stocks(db_session)

        assert [row["stock_id"] for row in result["changed"]] == [str(expired.id)]
        assert result["skipped"] == []
        # 先 Base 后本地：Base 写不合格，本地置 frozen + 日志
        assert adapter.update_calls == [("material_receipt", "rec_EB1", {"上一状态": "不合格"})]
        assert expired.status == "frozen"
        assert future.status == "normal"
        assert quarantined.status == "quarantine"

        logs = (
            await db_session.execute(
                select(WarehouseStockStatusLog).where(
                    WarehouseStockStatusLog.stock_id == expired.id
                )
            )
        ).scalars().all()
        assert len(logs) == 1
        assert (logs[0].old_status, logs[0].new_status) == ("normal", "frozen")
        assert logs[0].operator_id is None

        # 幂等：重复执行不再产生变更
        assert await expiry_freeze.freeze_expired_stocks(db_session) == {
            "changed": [],
            "skipped": [],
        }
    finally:
        await _cleanup(db_session)


async def test_freeze_skips_base_failure_rows(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_base(monkeypatch, fail_batches={"EBbad"})
    try:
        bad = await _seed_stock(db_session, suffix="bad", expiry_offset_days=-3)
        good = await _seed_stock(db_session, suffix="good", expiry_offset_days=-2)

        result = await expiry_freeze.freeze_expired_stocks(db_session)

        assert [row["stock_id"] for row in result["changed"]] == [str(good.id)]
        assert [row["stock_id"] for row in result["skipped"]] == [str(bad.id)]
        assert "Base 写入失败" in result["skipped"][0]["error"]
        # 失败行本地保持 normal（下轮重试），成功行不回滚
        assert bad.status == "normal"
        assert good.status == "frozen"
    finally:
        await _cleanup(db_session)


async def test_freeze_local_only_when_writeback_disabled(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回写开关关闭（生产默认）：冻结退化为本地直写，零 Base 调用。"""
    adapter = _patch_base(monkeypatch, writeback=False)
    try:
        expired = await _seed_stock(db_session, suffix="off", expiry_offset_days=-3)
        result = await expiry_freeze.freeze_expired_stocks(db_session)

        assert [row["stock_id"] for row in result["changed"]] == [str(expired.id)]
        assert result["skipped"] == []
        assert adapter.update_calls == []  # 零 Base 调用
        assert expired.status == "frozen"  # 本地直写生效
    finally:
        await _cleanup(db_session)


async def test_notify_sent_to_configured_target(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_base(monkeypatch)
    from app.modules.warehouse.ops_config.scheduler_store import scheduler_store

    monkeypatch.setattr(scheduler_store, "get_alert_target", lambda: "oc_test")
    try:
        await _seed_stock(db_session, suffix="1", expiry_offset_days=-3)
        result = await expiry_freeze.freeze_expired_stocks(db_session)

        send_mock = AsyncMock(return_value="om_test")
        monkeypatch.setattr(notification, "send_card", send_mock)

        assert await expiry_freeze.notify_expired_freeze(result["changed"]) is True
        send_mock.assert_awaited_once()
        call = send_mock.await_args
        assert call is not None
        assert call.args[0] == "oc_test"
        assert "已自动冻结" in str(call.args[1])
    finally:
        await _cleanup(db_session)


async def test_notify_skipped_without_target(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.warehouse.ops_config.scheduler_store import scheduler_store

    monkeypatch.setattr(scheduler_store, "get_alert_target", lambda: None)
    send_mock = AsyncMock(return_value="om_x")
    monkeypatch.setattr(notification, "send_card", send_mock)

    assert await expiry_freeze.notify_expired_freeze([{"material_code": "X"}]) is False
    send_mock.assert_not_awaited()
    # 无变更同样跳过
    assert await expiry_freeze.notify_expired_freeze([]) is False
    send_mock.assert_not_awaited()


async def test_scheduled_wrapper_window_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    freeze_mock = AsyncMock(return_value={"changed": [], "skipped": []})
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
