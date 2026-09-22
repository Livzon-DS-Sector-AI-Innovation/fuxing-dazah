"""事件闸门单测（chemical_inventory-direct Ticket 06）。

EVENT_SYNC 关（DIRECT 开）→ drive 事件入口整体短路、订阅短路、全量同步短路；
legacy（EVENT_SYNC 开或 DIRECT 关）→ 行为与改造前一致。
"""

from __future__ import annotations

from typing import Any

import pytest

import app.modules.safety.feishu.chemical_inventory_bitable_handler as handler_mod
from app.modules.safety.service.chemical_inventory_direct import config


def _event() -> dict[str, Any]:
    return {
        "file_token": "appX",
        "table_id": "tblX",
        "action_list": [{"record_id": "rec1", "action": "record_added"}],
    }


@pytest.fixture
def _patch_route(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """替身化 token/table 过滤与三个 handler，返回调用记录。"""
    calls: dict[str, list[Any]] = {"created": [], "changed": [], "deleted": []}

    async def _rec_created(event_data: dict[str, Any]) -> None:
        calls["created"].append(event_data)

    async def _rec_changed(event_data: dict[str, Any]) -> None:
        calls["changed"].append(event_data)

    async def _rec_deleted(event_data: dict[str, Any]) -> None:
        calls["deleted"].append(event_data)

    monkeypatch.setattr(handler_mod, "_get_inventory_app_token", lambda: "appX")
    monkeypatch.setattr(handler_mod, "_get_inventory_table_id", lambda: "tblX")
    monkeypatch.setattr(handler_mod, "_handle_created", _rec_created)
    monkeypatch.setattr(handler_mod, "_handle_changed", _rec_changed)
    monkeypatch.setattr(handler_mod, "_handle_deleted", _rec_deleted)
    return calls


class TestEventGateClosed:
    async def test_drive_event_short_circuits(
        self, monkeypatch: pytest.MonkeyPatch, _patch_route: dict[str, list[Any]]
    ) -> None:
        monkeypatch.setattr(config, "legacy_event_sync_active", lambda: False)
        await handler_mod._on_inventory_drive_changed(_event())
        assert _patch_route == {"created": [], "changed": [], "deleted": []}

    async def test_subscribe_short_circuits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """闸门关时不订阅（连配置中心都不该碰）。"""
        monkeypatch.setattr(config, "legacy_event_sync_active", lambda: False)

        def _boom() -> None:
            raise AssertionError("闸门关时不该读连接配置")

        monkeypatch.setattr(handler_mod, "_inventory_conn", _boom)
        assert await handler_mod.ensure_chemical_inventory_bitable_subscribed() is False

    async def test_full_sync_short_circuits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "legacy_event_sync_active", lambda: False)

        def _boom() -> bool:
            raise AssertionError("直读模式下不该走到镜像同步")

        monkeypatch.setattr(handler_mod, "_enabled", _boom)
        result = await handler_mod.sync_inventory_records_from_bitable()
        assert result == {"skipped": True, "reason": "direct_mode"}


class TestEventGateOpen:
    async def test_drive_event_dispatches(
        self, monkeypatch: pytest.MonkeyPatch, _patch_route: dict[str, list[Any]]
    ) -> None:
        monkeypatch.setattr(config, "legacy_event_sync_active", lambda: True)
        await handler_mod._on_inventory_drive_changed(_event())
        assert [e["record_id"] for e in _patch_route["created"]] == ["rec1"]

    async def test_full_sync_passes_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """legacy 下闸门放行（未配置连接时走既有优雅降级路径）。"""
        monkeypatch.setattr(config, "legacy_event_sync_active", lambda: True)
        monkeypatch.setattr(handler_mod, "_enabled", lambda: False)
        result = await handler_mod.sync_inventory_records_from_bitable()
        assert result["skipped"] is True
        assert "reason" not in result or result.get("reason") != "direct_mode"
