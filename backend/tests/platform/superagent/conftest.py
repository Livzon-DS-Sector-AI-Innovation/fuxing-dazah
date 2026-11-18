"""superagent 域测试 conftest —— 引擎测试隔离开关（R3 三期验收收口，2026-11-18）。

动因（2026-11-17 实证）：共享 dev 库下测试中途 commit 的任务/输入/效果会被
活引擎（source_poll/effects/outbox/task/watchdog 五循环）拾走双跑——同 dedupe
双行假红、真烧 LLM 诊断、测试噪音卡真发管理员。runtime.engine_test_paused 检测
本夹具持有的 advisory lock，持锁期间引擎整轮空转。

锁随连接断开自动释放（测试崩溃不死锁）；引擎 try 成功即释放、自身永不持锁。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text

_LOCK_KEY = 977333701  # 与 app/platform/superagent/runtime.py 同值，勿改


@pytest_asyncio.fixture(autouse=True)
async def _pause_live_engine() -> AsyncIterator[None]:
    """每测持锁（独立连接；测试间释放——引擎可在间隙正常运转。）。"""
    from tests.conftest import _test_engine

    async with _test_engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _LOCK_KEY})
        try:
            yield
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
