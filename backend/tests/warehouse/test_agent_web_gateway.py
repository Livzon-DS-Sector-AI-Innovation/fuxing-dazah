"""Agent Web 网关测试（分期B Ticket 05）：SSE 事件序列、鉴权、会话隔离、熔断。"""


from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse import web_gateway
from app.modules.warehouse.models import WarehouseAgentSession


async def test_chat_stream_event_sequence(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    class _FakeRunner:
        async def run(self, session, text, scene_hint=None):
            from app.modules.warehouse.agent.runner import Reply

            return Reply(text="你好，库存正常。", data=None)

    monkeypatch.setattr(web_gateway, "get_runner", lambda: _FakeRunner())

    resp = await auth_client.post(
        "/api/v1/warehouse/agent/chat/stream",
        json={"message": "查一下库存"},
    )
    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers.get("content-type", "")
    body = resp.text
    assert "event: accepted" in body
    assert "event: stage" in body
    assert "event: message" in body
    assert "你好，库存正常。" in body
    assert "event: finished" in body
    # sequence 单调递增
    seqs = [int(line.split("seq: ")[1]) for line in body.splitlines() if line.startswith("seq: ")]
    assert seqs == sorted(seqs)


async def test_chat_stream_creates_web_session(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    class _FakeRunner:
        async def run(self, session, text, scene_hint=None):
            from app.modules.warehouse.agent.runner import Reply

            # 会话键必须是 web 维度
            assert session.chat_id == "web"
            assert session.user_open_id.startswith("web:")
            return Reply(text="ok", data=None)

    monkeypatch.setattr(web_gateway, "get_runner", lambda: _FakeRunner())

    resp = await auth_client.post(
        "/api/v1/warehouse/agent/chat/stream",
        json={"message": "你好"},
    )
    assert resp.status_code == 200

    # web 会话已持久化（网关侧自开事务提交）
    rows = (
        await db_session.execute(
            select(WarehouseAgentSession).where(WarehouseAgentSession.chat_id == "web")
        )
    ).scalars().all()
    assert len(rows) >= 1


async def test_chat_stream_empty_message_rejected(auth_client: AsyncClient) -> None:
    resp = await auth_client.post(
        "/api/v1/warehouse/agent/chat/stream",
        json={"message": ""},
    )
    assert resp.status_code == 422


async def test_chat_stream_scenario_disabled(
    auth_client: AsyncClient, monkeypatch
) -> None:
    from app.modules.warehouse.ai_config.scenario_store import scenario_store

    monkeypatch.setattr(scenario_store, "is_enabled", lambda scenario: False)
    resp = await auth_client.post(
        "/api/v1/warehouse/agent/chat/stream",
        json={"message": "你好"},
    )
    assert resp.status_code == 503


async def test_chat_stream_requires_login(client: AsyncClient) -> None:
    # client 无登录覆写：get_current_user 返回 None → require_user 401
    resp = await client.post(
        "/api/v1/warehouse/agent/chat/stream",
        json={"message": "你好"},
    )
    assert resp.status_code == 401
