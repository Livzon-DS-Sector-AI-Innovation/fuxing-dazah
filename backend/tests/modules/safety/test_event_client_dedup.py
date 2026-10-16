"""安全飞书事件去重（event_id TTL 表）的单元测试。

飞书事件是 at-least-once 投递：断线重连窗口内收到的事件会在重连成功后被
原样重推（同 event_id 同 message_id），不去重则 bot 对同一条消息答两遍。
纯内存验证，不依赖 Redis / 飞书网络。
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.modules.safety.feishu import event_client

_EVENT_TYPE = "test.dedup_probe"


def _v2_event(event_id: str | None) -> dict[str, Any]:
    header: dict[str, Any] = {"event_type": _EVENT_TYPE}
    if event_id is not None:
        header["event_id"] = event_id
    return {"schema": "2.0", "header": header, "event": {"k": "v"}}


@pytest.fixture()
def probe_handler(monkeypatch) -> list[dict[str, Any]]:
    """注册独立事件类型的探针 handler，测试结束后清理模块级注册表。"""
    seen: list[dict[str, Any]] = []

    async def handler(event_data: dict[str, Any]) -> None:
        seen.append(event_data)

    monkeypatch.setitem(event_client._handlers, _EVENT_TYPE, [handler])
    event_client._event_dedup.clear()
    yield seen
    event_client._event_dedup.clear()


async def test_duplicate_event_id_dispatched_once(probe_handler) -> None:
    assert await event_client._dispatch_event(_v2_event("evt-1")) is None
    assert await event_client._dispatch_event(_v2_event("evt-1")) is None
    assert await event_client._dispatch_event(_v2_event("evt-1")) is None
    assert len(probe_handler) == 1


async def test_different_event_ids_all_dispatch(probe_handler) -> None:
    await event_client._dispatch_event(_v2_event("evt-a"))
    await event_client._dispatch_event(_v2_event("evt-b"))
    assert len(probe_handler) == 2


async def test_event_without_event_id_never_deduped(probe_handler) -> None:
    await event_client._dispatch_event(_v2_event(None))
    await event_client._dispatch_event(_v2_event(None))
    assert len(probe_handler) == 2


async def test_dedup_expires_after_ttl(probe_handler) -> None:
    await event_client._dispatch_event(_v2_event("evt-ttl"))
    # 登记时间回拨到 TTL 之外，模拟窗口过期后飞书仍在重推
    event_client._event_dedup["evt-ttl"] = (
        time.monotonic() - event_client._EVENT_DEDUP_TTL - 1
    )
    await event_client._dispatch_event(_v2_event("evt-ttl"))
    assert len(probe_handler) == 2
