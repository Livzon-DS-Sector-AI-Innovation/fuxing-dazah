"""AI 调用审计 live 冒烟：真实 LLM 调用产生完整审计链（票 06 验收）。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.ai_audit.audited_client import WarehouseAuditedLLMClient
from app.modules.warehouse.ai_audit.context import warehouse_audit_scope
from app.modules.warehouse.ai_audit.models import AiCallAudit


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """生产引擎连接池绑定首次使用的 event loop（pytest-asyncio 每测试新建
    loop）——dispose 后本测试内新建连接，避免跨 loop 复用死连接。"""
    import app.core.database as db_mod

    await db_mod.engine.dispose()
    yield
    await db_mod.engine.dispose()


@pytest.mark.live
async def test_live_audit_chain(db_session: AsyncSession) -> None:
    trace_id = str(uuid.uuid4())
    with warehouse_audit_scope(
        "agent_chat",
        trace_id=trace_id,
        chat_id="oc_live_test",
        user_open_id="ou_live_test",
        channel="feishu",
    ):
        client = WarehouseAuditedLLMClient()
        msg = await client.chat_with_tools(
            [{"role": "user", "content": "连通性测试，回复两个字：正常"}]
        )
    assert msg.content  # LLM 正常返回
    row = (
        await db_session.execute(
            select(AiCallAudit).where(AiCallAudit.trace_id == trace_id)
        )
    ).scalars().one()
    assert row.scenario == "agent_chat"
    assert row.status == "success"
    assert row.model
    assert row.input_tokens is not None and row.input_tokens > 0
    assert row.latency_ms is not None
    assert row.prompt_version and len(row.prompt_version) == 12
