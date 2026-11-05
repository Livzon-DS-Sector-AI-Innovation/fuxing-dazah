"""T06 B5 旧事件通道止血单测（RED 先行）。

验收：EVENT_SYNC=false → push 行为不变（deprecated 日志可见）；
EVENT_SYNC=true → 不调用 mapping/update_record、CRITICAL 告警、return False。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.feishu import bitable_handler
from app.modules.safety.service.hazard_direct import config as hazard_config


class _FakeBitable:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def update_record(self, record_id: str, fields: dict[str, Any]) -> bool:
        self.calls.append((record_id, fields))
        return True


class _LogCapture(logging.Handler):
    """独立捕获 handler（app 日志配置可能关 propagate，caplog 抓不到）。"""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _wire(monkeypatch: pytest.MonkeyPatch, *, event_sync: bool) -> tuple[_FakeBitable, list[Any]]:
    fake_client = _FakeBitable()
    mapped: list[Any] = []

    monkeypatch.setattr(
        "app.modules.safety.service.hazard_direct.config.event_sync_enabled",
        lambda: event_sync,
    )
    monkeypatch.setattr(bitable_handler, "SafetyBitableClient", lambda: fake_client)

    async def _fake_field_defs(client: Any) -> None:
        return None

    async def _fake_sync_ignore(record_id: str, ttl: int = 30) -> None:
        return None

    def _fake_map(hazard: Any) -> dict[str, Any]:
        mapped.append(hazard)
        return {"隐患描述": "人工描述", "隐患级别": "较大隐患"}

    monkeypatch.setattr(bitable_handler, "_get_field_definitions", _fake_field_defs)
    monkeypatch.setattr(bitable_handler, "_set_sync_ignore", _fake_sync_ignore)
    monkeypatch.setattr(bitable_handler, "_map_model_to_bitable", _fake_map)
    return fake_client, mapped


async def test_push_keeps_behavior_when_event_sync_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    map_doc = bitable_handler._map_model_to_bitable.__doc__ or ""
    fake_client, mapped = _wire(monkeypatch, event_sync=False)
    hazard = SimpleNamespace(id="h1", feishu_record_id="rec1")
    cap = _LogCapture()
    bitable_handler.logger.addHandler(cap)
    try:
        ok = await bitable_handler.push_hazard_to_bitable(hazard)
    finally:
        bitable_handler.logger.removeHandler(cap)

    assert ok is True
    assert len(mapped) == 1
    assert fake_client.calls == [("rec1", {"隐患描述": "人工描述", "隐患级别": "较大隐患"})]
    # deprecated 标记：docstring + 运行日志
    assert "已废弃" in (bitable_handler.push_hazard_to_bitable.__doc__ or "")
    assert "已废弃" in map_doc, map_doc
    assert any("废弃" in record.getMessage() for record in cap.records)


async def test_push_refuses_when_event_sync_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client, mapped = _wire(monkeypatch, event_sync=True)
    hazard = SimpleNamespace(id="h1", feishu_record_id="rec1")
    cap = _LogCapture()
    bitable_handler.logger.addHandler(cap)
    try:
        ok = await bitable_handler.push_hazard_to_bitable(hazard)
    finally:
        bitable_handler.logger.removeHandler(cap)

    assert ok is False
    assert mapped == [], "EVENT_SYNC=true 时不得调用 _map_model_to_bitable（整行映射）"
    assert fake_client.calls == [], "EVENT_SYNC=true 时不得发起任何 Bitable 写"
    assert any(
        record.levelno >= logging.CRITICAL and "拒绝整行回写" in record.getMessage()
        for record in cap.records
    ), [record.getMessage() for record in cap.records]


async def test_push_without_feishu_record_id_stays_quiet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.safety.service.hazard_direct.config.event_sync_enabled",
        lambda: True,
    )
    hazard = SimpleNamespace(id="h1", feishu_record_id="")
    assert await bitable_handler.push_hazard_to_bitable(hazard) is False


def test_event_sync_flag_still_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """B5 只加隔离，不放宽开关默认值语义（由 config 层负责）。"""
    monkeypatch.delenv("SAFETY_HAZARD_EVENT_SYNC_ENABLED", raising=False)
    # 读取链在测试 conftest 中被 stub 到 env/default，默认关闭。
    assert hazard_config.event_sync_enabled() is False
