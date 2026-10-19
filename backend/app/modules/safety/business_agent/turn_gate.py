"""轮次串行化门（进程内 per-key asyncio.Lock）。

背景：同一会话的 agent 轮次会并发修改三类共享状态——事件流
（``agent_session_events`` 的 ``(session_id, seq)`` 唯一索引）、
``agent_sessions.message_history`` 整包覆写、消息流水。两个轮次交错
（用户连发两条消息、消息轮与卡片确认轮交叉）时各自从同一基线分配 seq /
覆写历史，触发唯一索引冲突或丢失更新——整轮对话丢失。

此前 ``core/events.py`` docstring 声称「入口层已按 chat_id 串行化」，
但入口层并无该机制；本模块补齐。用法：入口把「执行 + 持久化」整段包在
``async with turn_gate(key)`` 中，key 跨渠道同格式：
``feishu:{chat_id}`` / ``web:{session_id}``。

边界：进程内锁（单事件循环）。多 worker 部署需升级为
``pg_advisory_xact_lock``（``core/events.py`` 的 TODO 已预留位）。
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# 弱值字典：锁被持有/等待期间由协程栈强引用保活；全部释放后可被 GC
# 自动回收，无需手工淘汰（避免「清空时误删他人正在持有的锁」）。
_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


@asynccontextmanager
async def turn_gate(key: str) -> AsyncIterator[None]:
    """同 key 轮次串行执行。

    单线程事件循环内 ``get/set`` 之间无 await 切换点，锁的创建不存在
    并发竞争；此处 await 只发生在锁的获取上。
    """
    lock = _LOCKS.get(key)
    if lock is None:
        lock = _LOCKS[key] = asyncio.Lock()
    async with lock:
        yield
