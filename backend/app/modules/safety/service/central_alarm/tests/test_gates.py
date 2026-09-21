"""Ticket 04：事件 handler 与手动同步端点闸门单测（照消防 test_gates 口径）。"""

from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.feishu import central_alarm_bitable_handler as handler
from app.modules.safety.service.central_alarm.service import (
    central_alarm_app_token,
    central_alarm_table_ids,
)


async def test_event_handler_returns_when_direct_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
    called: list[str] = []

    async def fake_upsert(record_id: str, table_id: str) -> None:
        called.append(record_id)

    async def fake_delete(record_id: str, table_id: str) -> None:
        called.append(record_id)

    monkeypatch.setattr(handler, "_handle_upsert", fake_upsert)
    monkeypatch.setattr(handler, "_handle_delete", fake_delete)

    await handler.handle_central_alarm_record_changed({
        "file_token": central_alarm_app_token(),
        "table_id": central_alarm_table_ids()[0],
        "action_list": [{"record_id": "rec1", "action": "record_added"}],
    })
    await handler.handle_central_alarm_record_changed({
        "file_token": central_alarm_app_token(),
        "table_id": central_alarm_table_ids()[0],
        "record_id": "rec2",
    })

    assert called == []


async def test_event_handler_processes_when_direct_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", raising=False)
    called: list[str] = []

    async def fake_upsert(record_id: str, table_id: str) -> None:
        called.append(record_id)

    async def fake_delete(record_id: str, table_id: str) -> None:
        called.append(record_id)

    monkeypatch.setattr(handler, "_handle_upsert", fake_upsert)
    monkeypatch.setattr(handler, "_handle_delete", fake_delete)

    await handler.handle_central_alarm_record_changed({
        "file_token": central_alarm_app_token(),
        "table_id": central_alarm_table_ids()[0],
        "action_list": [{"record_id": "rec1", "action": "record_added"}],
    })

    assert called == ["rec1"]


async def test_api_sync_short_circuits_when_direct_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
    import app.modules.safety.api.central_alarm as api_module

    result = await api_module.sync_from_bitable(db=cast(AsyncSession, None))
    assert "直读" in result.message
    assert result.data == {"synced_count": 0, "soft_deleted_count": 0}
