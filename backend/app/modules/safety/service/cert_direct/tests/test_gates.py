"""cert 事件镜像闸门单测（cert-direct Ticket 04）。

三态：全关（默认）=事件照常 / DIRECT 开=事件短路 / DIRECT+EVENT_SYNC 双跑恢复。
"""

from __future__ import annotations

from typing import Any

import pytest

import app.modules.safety.feishu.cert_bitable_handler as handler


def _event(action: str = "record_added") -> dict[str, Any]:
    return {
        "table_id": "tblA",
        "action_list": [{"record_id": "rec1", "action": action}],
    }


@pytest.fixture()
def _patch_dispatch(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """替身化 kind 反查与 upsert/软删，记录调用次数。"""
    calls = {"upsert": 0, "delete": 0}

    def _kind(table_id: str) -> str | None:
        return "special_op" if table_id == "tblA" else None

    async def _upsert(kind: str, record_id: str, *, created: bool = False) -> None:
        calls["upsert"] += 1

    async def _soft_delete(kind: str, record_id: str) -> None:
        calls["delete"] += 1

    monkeypatch.setattr(handler, "table_kind_by_id", _kind)
    monkeypatch.setattr(handler, "_upsert", _upsert)
    monkeypatch.setattr(handler, "_soft_delete", _soft_delete)
    return calls


async def test_gate_open_by_default(
    monkeypatch: pytest.MonkeyPatch, _patch_dispatch: dict[str, int]
) -> None:
    """全关（默认）：legacy 活跃，事件照常进镜像。"""
    monkeypatch.delenv("SAFETY_CERT_DIRECT_ENABLED", raising=False)
    monkeypatch.delenv("SAFETY_CERT_EVENT_SYNC_ENABLED", raising=False)
    await handler._on_cert_record_changed(_event())
    assert _patch_dispatch["upsert"] == 1


async def test_gate_short_circuits_when_direct_on(
    monkeypatch: pytest.MonkeyPatch, _patch_dispatch: dict[str, int]
) -> None:
    """DIRECT 开：事件入口短路，镜像零写入。"""
    monkeypatch.setenv("SAFETY_CERT_DIRECT_ENABLED", "true")
    monkeypatch.delenv("SAFETY_CERT_EVENT_SYNC_ENABLED", raising=False)
    await handler._on_cert_record_changed(_event())
    await handler._on_cert_record_changed(_event("record_deleted"))
    calls = _patch_dispatch
    assert calls["upsert"] == 0
    assert calls["delete"] == 0


async def test_gate_dual_run_with_explicit_event_sync(
    monkeypatch: pytest.MonkeyPatch, _patch_dispatch: dict[str, int]
) -> None:
    """DIRECT + EVENT_SYNC 显式开：旧镜像链路恢复（双跑）。"""
    monkeypatch.setenv("SAFETY_CERT_DIRECT_ENABLED", "true")
    monkeypatch.setenv("SAFETY_CERT_EVENT_SYNC_ENABLED", "true")
    await handler._on_cert_record_changed(_event())
    assert _patch_dispatch["upsert"] == 1
