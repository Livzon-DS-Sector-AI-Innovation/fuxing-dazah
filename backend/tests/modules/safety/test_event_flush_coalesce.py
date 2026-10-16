"""2-F 事件收口：轮内批量（seq 内存分配 + 尾部一次 flush）。

接缝：``start_turn_event_batch / end_turn_event_batch / append_event``——
批量开启时同 db 同 session 走内存 seq、不逐条 flush；批量外（低频/后台/
独立 session）走旧路径逐条 flush。用假 db 计数往返。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace


class _FakeDb:
    """计数 execute/flush 的假 AsyncSession。

    标量查询模拟 SQLAlchemy autoflush 语义：查询前待 flush 事件可见，
    故 SELECT max(seq) 返回已 add 条数 + 1。
    """

    def __init__(self) -> None:
        self.execute_calls = 0
        self.flush_calls = 0
        self.added: list = []

    async def execute(self, stmt):
        self.execute_calls += 1
        return SimpleNamespace(scalar_one=lambda: len(self.added) + 1)

    async def flush(self):
        self.flush_calls += 1

    def add(self, obj):
        self.added.append(obj)


_SID = uuid.uuid4()


def test_batch_coalesces_flush_and_seq() -> None:
    from app.modules.safety.business_agent.core import events

    async def scenario():
        db = _FakeDb()
        events.start_turn_event_batch(db, _SID)
        try:
            for i in range(5):
                await events.append_event(
                    db, session_id=_SID, event_type="user_message",
                    payload={"i": i},
                )
        finally:
            await events.end_turn_event_batch()

        return db

    db = asyncio.run(scenario())
    # seq 基准只查一次；5 条事件内存连续分配 1..5；轮末一次 flush
    assert db.execute_calls == 1
    assert db.flush_calls == 1
    assert [e.seq for e in db.added] == [1, 2, 3, 4, 5]


def test_legacy_path_without_batch() -> None:
    from app.modules.safety.business_agent.core import events

    async def scenario():
        db = _FakeDb()
        for _ in range(3):
            await events.append_event(
                db, session_id=_SID, event_type="assistant_message", payload={},
            )
        return db

    db = asyncio.run(scenario())
    assert db.execute_calls == 3  # 逐条 SELECT max
    assert db.flush_calls == 3   # 逐条 flush
    assert [e.seq for e in db.added] == [1, 2, 3]


def test_batch_isolated_from_foreign_session() -> None:
    """批量开启时，独立 session（如 memory_write 后台）仍走旧路径。"""

    from app.modules.safety.business_agent.core import events

    other_sid = uuid.uuid4()

    async def scenario():
        db = _FakeDb()
        foreign = _FakeDb()
        events.start_turn_event_batch(db, _SID)
        try:
            await events.append_event(db, session_id=_SID, event_type="turn_end", payload={})
            # 不同 db + 不同 session → 旧路径
            await events.append_event(
                foreign, session_id=other_sid, event_type="memory_write", payload={},
            )
            # 同 db 不同 session → 旧路径
            await events.append_event(
                db, session_id=other_sid, event_type="memory_write", payload={},
            )
        finally:
            await events.end_turn_event_batch()
        return db, foreign

    db, foreign = asyncio.run(scenario())
    # 批量内 1 条（1 execute + 1 flush 收口）；同 db 外 session 1 条走旧路径
    assert db.execute_calls == 2 and db.flush_calls == 2
    assert foreign.execute_calls == 1 and foreign.flush_calls == 1  # 旧路径
    # 批量结束后回到旧路径
    asyncio.run(
        events.append_event(db, session_id=_SID, event_type="turn_end", payload={})
    )
    assert db.execute_calls == 3 and db.flush_calls == 3
