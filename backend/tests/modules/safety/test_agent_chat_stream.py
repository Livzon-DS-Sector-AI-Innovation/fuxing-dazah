"""2-F Web SSE 端点：事件序列 / seq 单调 / pending 事件 / error 不断流 / 熔断 503。

接缝：POST /agent/chat/stream（ASGI 级，全链路 mock——run_turn/session_store/
async_session_factory 均替换，无 LLM 无 DB）。配方对齐仓储 test_agent_web_gateway。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture
def _mock_pipeline(monkeypatch: pytest.MonkeyPatch):
    """替身 run_turn / session_store / db factory（无 LLM 无 DB）。"""
    import app.core.database as db_mod
    from app.modules.safety.api import business_agent as api_mod
    from app.modules.safety.business_agent import executor as executor_mod
    from app.modules.safety.business_agent import session_store as store_mod
    from app.modules.safety.business_agent.schemas import PendingActionData

    session_obj = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        message_history=None,
        message_count=0,
    )

    async def fake_run_turn(message, deps, *, message_history=None):
        if message == "挂起":
            return {
                "answer": "请确认",
                "messages": [{"role": "assistant", "content": "请确认"}],
                "pending_action": PendingActionData(
                    tool_name="create_oh_followup",
                    arguments={"person": "张三"},
                    summary="创建随访",
                ),
                "sources": None,
            }
        if message == "炸":
            raise RuntimeError("boom")
        return {
            "answer": "好的",
            "messages": [{"role": "assistant", "content": "好的"}],
            "pending_action": None,
            "sources": [{"title": "t"}],
        }

    class _FakeSession:
        async def __aenter__(self):
            return SimpleNamespace(commit=self._commit)

        async def __aexit__(self, *args):
            return False

        async def _commit(self):
            pass

    async def fake_build_deps(db, *, session_id=None, feishu_user_id=None):
        return SimpleNamespace(
            db=db, session_id=session_id, channel="web",
            person=None, role="safety_admin",
        )

    async def fake_get_or_create_session(db, *, channel, chat_id, user_id, role):
        return session_obj

    async def fake_create_pending_action(db, *, session_id, pending, message_history_snapshot):
        return SimpleNamespace(id="00000000-0000-0000-0000-000000000002")

    async def fake_update_session_history(db, session, *, messages, title=None):
        return None

    async def fake_save_message(db, *, session_id, user_message, agent_answer, pending_action_id=None):
        return None

    monkeypatch.setattr(executor_mod, "run_turn", fake_run_turn)
    monkeypatch.setattr(api_mod, "_build_deps", fake_build_deps)
    monkeypatch.setattr(store_mod, "get_or_create_session", fake_get_or_create_session)
    monkeypatch.setattr(store_mod, "create_pending_action", fake_create_pending_action)
    monkeypatch.setattr(store_mod, "update_session_history", fake_update_session_history)
    monkeypatch.setattr(store_mod, "save_message", fake_save_message)
    monkeypatch.setattr(db_mod, "async_session_factory", lambda: _FakeSession())
    return fake_run_turn


async def _stream_events(message: str) -> list[tuple[str, dict]]:
    """直接驱动端点函数，解析 SSE 流 → [(event, data)]。"""
    from app.modules.safety.api.business_agent import agent_chat_stream
    from app.modules.safety.business_agent.schemas import AgentChatRequest

    resp = await agent_chat_stream(AgentChatRequest(message=message), current_user=None)
    assert resp.media_type == "text/event-stream"
    chunks: list[str] = []
    gen = resp.body_iterator

    async for chunk in gen:
        chunks.append(chunk if isinstance(chunk, str) else chunk.decode())
    events: list[tuple[str, dict]] = []
    for block in "".join(chunks).split("\n\n"):
        if not block.strip():
            continue
        event_name = ""
        data: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((event_name, data))
    return events


async def test_stream_event_sequence_and_seq_monotonic(_mock_pipeline) -> None:
    events = await _stream_events("你好")
    names = [n for n, _ in events]
    assert names == ["accepted", "stage", "message", "finished"]
    seqs = [d["seq"] for _, d in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    message_data = dict(events[2][1])
    assert message_data["answer"] == "好的"
    assert message_data["sources"] == [{"title": "t"}]
    assert "session_id" in message_data
    assert events[3][1]["duration_ms"] >= 0


async def test_stream_pending_event_before_message(_mock_pipeline) -> None:
    events = await _stream_events("挂起")
    names = [n for n, _ in events]
    assert names == ["accepted", "stage", "pending", "message", "finished"]
    pending_data = dict(events[2][1])
    assert pending_data["pending_action"]["tool_name"] == "create_oh_followup"
    assert pending_data["pending_action_id"]


async def test_stream_error_event_not_breaking(_mock_pipeline) -> None:
    events = await _stream_events("炸")
    names = [n for n, _ in events]
    assert names == ["accepted", "stage", "error"]
    assert "boom" in dict(events[2][1])["error"]


async def test_stream_disabled_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.responses import JSONResponse

    from app.modules.safety.ai_config.scenario_store import scenario_store
    from app.modules.safety.api.business_agent import agent_chat_stream
    from app.modules.safety.business_agent.schemas import AgentChatRequest

    monkeypatch.setattr(scenario_store, "is_enabled", lambda scenario: False)
    resp = await agent_chat_stream(AgentChatRequest(message="你好"), current_user=None)
    assert isinstance(resp, JSONResponse) and resp.status_code == 503


def test_stream_endpoint_registered() -> None:
    from app.modules.safety.api.business_agent import business_agent_router

    paths = {r.path for r in business_agent_router.routes}
    assert "/agent/chat/stream" in paths
    assert "/agent/chat" in paths  # 旧同步端点保留（飞书/回滚不受影响）
