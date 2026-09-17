"""快递通知自动化测试（V3.0 分期A Ticket 08）。

接缝：事件入口 fire_push_event + 渲染器 + submit 侧 payload 构造
（_express_payload 纯函数）；发送经 notification dry_run/monkeypatch 假件。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.pipeline import submit as submit_mod
from app.modules.warehouse.ai_audit import failure_notifier
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import WarehousePushLog
from app.modules.warehouse.push_center import engine, events
from app.modules.warehouse.push_center.store import PushConfigStore


@dataclass
class StubPushRow:
    task_name: str
    enabled: bool = True
    schedule: dict[str, Any] | None = None
    targets: str | None = None
    note: str | None = None
    is_deleted: bool = False


_EXPRESS_PAYLOAD = {
    "product_name": "盐酸万古霉素",
    "product_batch_no": "260901",
    "quantity": 12,
    "unit": "kg",
    "customer": "福州某某医药",
    "express_no": "SF1234567890",
}


def _make_store(rows: dict[str, StubPushRow | None]) -> PushConfigStore:
    return PushConfigStore(row_loader=lambda name: rows.get(name))


class TestExpressRenderer:
    def test_card_contains_shipping_fields(self) -> None:
        card = events.render_express_notify_card(_EXPRESS_PAYLOAD)
        assert card["schema"] == "2.0"
        assert card["header"]["title"]["content"] == "📦 发货通知"
        joined = "".join(str(e) for e in card["body"]["elements"])
        assert "盐酸万古霉素" in joined
        assert "260901" in joined
        assert "福州某某医药" in joined
        assert "SF1234567890" in joined


class TestFirePushEvent:
    async def test_event_task_pushes_to_targets(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = {"express_notify": StubPushRow(task_name="express_notify", targets="oc_sale")}
        monkeypatch.setattr(engine, "push_store", _make_store(rows))
        monkeypatch.setattr(failure_notifier, "fire_notify_failure", MagicMock())
        sent_cards: list[tuple[str, dict]] = []

        async def _fake_send(chat_id: str, card: dict, dry_run: bool | None = None):
            sent_cards.append((chat_id, card))
            return "om_x"

        monkeypatch.setattr(notification, "send_card", _fake_send)

        results = await events.fire_push_event(
            db_session, "express_notify", _EXPRESS_PAYLOAD
        )
        assert [r.status for r in results] == ["executed"]
        assert len(sent_cards) == 1
        assert sent_cards[0][0] == "oc_sale"
        joined = "".join(str(e) for e in sent_cards[0][1]["body"]["elements"])
        assert "SF1234567890" in joined

        logs = (
            await db_session.execute(
                select(WarehousePushLog).where(
                    WarehousePushLog.task_name == "express_notify"
                )
            )
        ).scalars().all()
        assert len(logs) == 1
        assert logs[0].trigger == "event"
        assert logs[0].slot is None
        assert logs[0].status == "success"
        assert logs[0].message_id == "om_x"

    async def test_disabled_event_task_skipped(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = {"express_notify": StubPushRow(task_name="express_notify", enabled=False, targets="oc_sale")}
        monkeypatch.setattr(engine, "push_store", _make_store(rows))
        results = await events.fire_push_event(
            db_session, "express_notify", _EXPRESS_PAYLOAD
        )
        assert [r.status for r in results] == ["skipped_disabled"]
        logs = (
            await db_session.execute(
                select(WarehousePushLog).where(WarehousePushLog.task_name == "express_notify")
            )
        ).scalars().all()
        assert logs == []

    async def test_no_target_logs_skip(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = {"express_notify": StubPushRow(task_name="express_notify")}
        monkeypatch.setattr(engine, "push_store", _make_store(rows))
        results = await events.fire_push_event(
            db_session, "express_notify", _EXPRESS_PAYLOAD
        )
        assert [r.status for r in results] == ["skipped_no_target"]
        logs = (
            await db_session.execute(
                select(WarehousePushLog).where(WarehousePushLog.task_name == "express_notify")
            )
        ).scalars().all()
        assert len(logs) == 1 and logs[0].status == "skipped"


class TestSubmitSideHelpers:
    def test_express_payload_filters_empty_and_adds_date(self) -> None:
        payload = submit_mod._express_payload(
            {"product_name": "达托霉素", "customer": None, "remark": ""},
            "SF999",
        )
        assert payload["product_name"] == "达托霉素"
        assert payload["express_no"] == "SF999"
        assert "customer" not in payload and "remark" not in payload
        assert "outbound_date" in payload

    async def test_fire_express_notify_swallows_errors(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("推送通道异常")

        monkeypatch.setattr(events, "fire_push_event", _boom)
        # 通知异常不影响出库登记主流程
        assert await submit_mod._fire_express_notify(
            db_session, _EXPRESS_PAYLOAD, "SF1234567890"
        ) is False

    async def test_fire_express_notify_success(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.warehouse.push_center.engine import PushRunResult

        async def _fake_fire(db, scene, payload, **kwargs):
            return [PushRunResult("express_notify", scene, "executed", None, 1)]

        monkeypatch.setattr(events, "fire_push_event", _fake_fire)
        assert await submit_mod._fire_express_notify(
            db_session, _EXPRESS_PAYLOAD, "SF1234567890"
        ) is True
