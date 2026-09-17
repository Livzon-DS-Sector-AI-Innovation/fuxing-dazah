"""Ticket 06：事件处理器与 API 同步闸门单测。"""

from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.feishu import fire_alarm_bitable_handler as handler


async def test_event_handler_returns_when_direct_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_FIRE_ALARM_DIRECT_ENABLED", "true")
    called: list[str] = []

    async def fake_upsert(record_id: str) -> None:
        called.append(record_id)

    monkeypatch.setattr(handler, "_handle_upsert", fake_upsert)

    await handler.handle_fire_alarm_record_changed({
        "action_list": [{"record_id": "rec1", "action": "record_added"}],
    })

    assert called == []


async def test_api_sync_returns_disabled_when_direct_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_FIRE_ALARM_DIRECT_ENABLED", "true")
    import app.modules.safety.api.fire_alarm as api_module

    result = await api_module.sync_from_bitable(db=cast(AsyncSession, None))

    assert result.data == {"synced_count": 0, "soft_deleted_count": 0}
    assert "已关闭" in result.message
