"""会话并发修复回归（InvalidRequestError: Session is already flushing 根因 + 同族问题）。

背景（2026-10-16 飞书机器人报错「这个月有多少变更」）：run_turn 轮内调度
记忆提取后台任务并复用轮内 deps.db——后台任务与主流程的 flush/commit 在同
一 AsyncSession 上交错，触发 InvalidRequestError: Session is already
flushing，异常从入口层兜底逃逸给用户，且整轮对话历史随事务回滚丢失。

同族问题（举一反三）：
- bitable AI 整改初审后台任务捕获外层事件处理 service/session；
- 同会话并发轮次（连发消息 / 消息轮与卡片确认轮交叉）无串行化——事件流
  (session_id, seq) 唯一索引撞车、message_history 相互覆写。

本文件锁定契约：
1. ``schedule_memory_extraction``：独立 session（绝不触碰 deps.db）、
   对话文本直传、commit 归属独立事务；
2. ``turn_gate``：同 key 串行、异 key 不互斥；
3. Web 入口：run_turn 持久化 commit 完成后才调度记忆提取（顺序保证），
   同 session_id 并发轮次被串行化。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

# ═══════════════════════════════════════════════════════════════
# 1. schedule_memory_extraction：独立 session + 文本直传
# ═══════════════════════════════════════════════════════════════


async def test_memory_task_uses_own_session(monkeypatch) -> None:
    """后台记忆提取必须自开 session：merge/commit 都发生在工厂会话上，
    deps.db（轮内会话）绝不被后台任务触碰。"""
    import app.core.database as db_mod
    from app.modules.safety.business_agent import executor
    from app.modules.safety.business_agent.core import memory as mem_mod
    from app.modules.safety.memory import extractor as extractor_mod

    calls: dict = {"factory": 0, "commit": 0, "merge_dbs": [], "texts": None}

    class _OwnSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, stmt):
            # append_event 旧路径的 SELECT max(seq)+1
            return SimpleNamespace(scalar_one=lambda: 1)

        async def flush(self):
            pass

        async def commit(self):
            calls["commit"] += 1

        def add(self, obj):
            pass

    def fake_factory():
        calls["factory"] += 1
        return _OwnSession()

    async def fake_extract(self, user_message, agent_reply, deps):
        calls["texts"] = (user_message, agent_reply)
        return [SimpleNamespace(memory_type="fact", content="x",
                                importance=0.9, confidence=0.9)]

    async def fake_merge(db, user_id, fact, embedding):
        calls["merge_dbs"].append(db)
        return uuid.UUID(int=1), []

    async def fake_get_embedder():
        async def embed(text):
            return [0.1, 0.2]

        return SimpleNamespace(embed=embed)

    monkeypatch.setattr(db_mod, "async_session_factory", fake_factory)
    monkeypatch.setattr(extractor_mod.MemoryExtractor, "extract", fake_extract)
    monkeypatch.setattr(mem_mod, "merge_on_conflict", fake_merge)
    monkeypatch.setattr(mem_mod, "_get_embedder", fake_get_embedder)

    sentinel_db = object()
    deps = SimpleNamespace(
        db=sentinel_db,
        session_id="00000000-0000-0000-0000-00000000000f",
        channel="feishu",
        person=SimpleNamespace(user_id="ou_x", name="张三", department=None),
        role="safety_admin",
    )

    task = executor.schedule_memory_extraction(
        session_id=deps.session_id,
        user_message="这个月有多少变更",
        agent_answer="共 3 条",
        deps=deps,
    )
    assert task is not None
    await task

    assert calls["factory"] == 1
    assert calls["texts"] == ("这个月有多少变更", "共 3 条")
    assert calls["merge_dbs"], "merge_on_conflict 应被调用"
    assert all(db is not sentinel_db for db in calls["merge_dbs"]), \
        "后台记忆提取严禁使用轮内 deps.db"
    assert calls["commit"] == 1, "入库 commit 应发生在独立 session 上"


async def test_memory_task_skips_anonymous_or_empty(monkeypatch) -> None:
    """匿名（person=None）/ 空文本 / 无 session_id 不调度任务。"""
    from app.modules.safety.business_agent import executor

    deps = SimpleNamespace(db=object(), session_id=str(uuid.uuid4()),
                           channel="web", person=None, role=None)
    assert executor.schedule_memory_extraction(
        session_id=deps.session_id, user_message="q", agent_answer="a", deps=deps,
    ) is None
    person = SimpleNamespace(user_id="ou_x", name="张三", department=None)
    deps2 = SimpleNamespace(db=object(), session_id=str(uuid.uuid4()),
                            channel="web", person=person, role=None)
    assert executor.schedule_memory_extraction(
        session_id=None, user_message="q", agent_answer="a", deps=deps2,
    ) is None
    assert executor.schedule_memory_extraction(
        session_id=deps2.session_id, user_message="", agent_answer="a", deps=deps2,
    ) is None


# ═══════════════════════════════════════════════════════════════
# 2. turn_gate：同 key 串行 / 异 key 不互斥
# ═══════════════════════════════════════════════════════════════


async def test_turn_gate_serializes_same_key() -> None:
    from app.modules.safety.business_agent.turn_gate import turn_gate

    events: list[str] = []
    release = asyncio.Event()

    async def first():
        async with turn_gate("k1"):
            events.append("first-in")
            await release.wait()
            events.append("first-out")

    async def second():
        await asyncio.sleep(0.01)  # 确保第一个先拿到锁
        events.append("second-attempt")
        async with turn_gate("k1"):
            events.append("second-in")

    t1 = asyncio.create_task(first())
    t2 = asyncio.create_task(second())
    await asyncio.sleep(0.05)
    assert events[:2] == ["first-in", "second-attempt"]
    assert "second-in" not in events, "同 key 第二个轮次必须被挡在门外"
    release.set()
    await asyncio.gather(t1, t2)
    assert events == ["first-in", "second-attempt", "first-out", "second-in"]


async def test_turn_gate_different_keys_independent() -> None:
    from app.modules.safety.business_agent.turn_gate import turn_gate

    events: list[str] = []

    async def a():
        async with turn_gate("ka"):
            events.append("a-in")
            await asyncio.sleep(0.02)
            events.append("a-out")

    async def b():
        await asyncio.sleep(0.005)
        async with turn_gate("kb"):
            events.append("b-in")

    await asyncio.gather(a(), b())
    assert events.index("b-in") < events.index("a-out"), "异 key 不应互相阻塞"


# ═══════════════════════════════════════════════════════════════
# 3. Web 入口：commit → schedule 顺序 + 并发轮次串行化
# ═══════════════════════════════════════════════════════════════


def _patch_web_turn_seams(monkeypatch, run_turn_fake) -> list[str]:
    """替换 _execute_turn_and_persist 的全部外部接缝，返回 trace 列表。"""
    from app.modules.safety.api import business_agent as api_mod
    from app.modules.safety.business_agent import executor as executor_mod
    from app.modules.safety.business_agent import session_store as store_mod

    trace: list[str] = []

    class _Db:
        async def commit(self):
            trace.append("commit")

    async def fake_build_deps(db, *, session_id=None, feishu_user_id=None):
        return SimpleNamespace(db=db, session_id=session_id or "s1",
                               channel="web", person=None, role=None)

    async def fake_get_or_create(db, **kw):
        return SimpleNamespace(id="00000000-0000-0000-0000-000000000003",
                               message_history=None, message_count=0)

    async def fake_update(db, session, *, messages, title=None):
        pass

    async def fake_save(db, **kw):
        pass

    async def fake_schedule(**kw):
        trace.append("schedule")

    monkeypatch.setattr(api_mod, "_build_deps", fake_build_deps)
    monkeypatch.setattr(store_mod, "get_or_create_session", fake_get_or_create)
    monkeypatch.setattr(store_mod, "update_session_history", fake_update)
    monkeypatch.setattr(store_mod, "save_message", fake_save)
    monkeypatch.setattr(executor_mod, "run_turn", run_turn_fake)
    monkeypatch.setattr(executor_mod, "schedule_memory_extraction", fake_schedule)
    return trace


async def test_web_turn_commits_before_memory_schedule(monkeypatch) -> None:
    """记忆提取必须在轮次事务 commit 之后调度（后台读事件/写 seq 的前提）。"""
    from app.modules.safety.api import business_agent as api_mod
    from app.modules.safety.api.business_agent import _execute_turn_and_persist
    from app.modules.safety.business_agent import executor as executor_mod
    from app.modules.safety.business_agent import session_store as store_mod

    trace: list[str] = []

    async def fake_run_turn(message, deps, *, message_history=None):
        return {"answer": "ans", "messages": [], "pending_action": None, "sources": None}

    def fake_schedule(**kw):
        trace.append("schedule")

    async def fake_build_deps(db, *, session_id=None, feishu_user_id=None):
        return SimpleNamespace(db=db, session_id=session_id or "s1",
                               channel="web", person=None, role=None)

    async def fake_get_or_create(db, **kw):
        return SimpleNamespace(id="00000000-0000-0000-0000-000000000003",
                               message_history=None, message_count=0)

    async def fake_update(db, session, *, messages, title=None):
        pass

    async def fake_save(db, **kw):
        pass

    monkeypatch.setattr(api_mod, "_build_deps", fake_build_deps)
    monkeypatch.setattr(store_mod, "get_or_create_session", fake_get_or_create)
    monkeypatch.setattr(store_mod, "update_session_history", fake_update)
    monkeypatch.setattr(store_mod, "save_message", fake_save)
    monkeypatch.setattr(executor_mod, "run_turn", fake_run_turn)
    monkeypatch.setattr(executor_mod, "schedule_memory_extraction", fake_schedule)

    class _Db:
        async def commit(self):
            trace.append("commit")

    result, session, pa = await _execute_turn_and_persist(
        _Db(), message="这个月有多少变更", session_id="s1", feishu_user_id=None,
    )
    assert result["answer"] == "ans"
    assert trace == ["commit", "schedule"], "必须先 commit 再调度记忆提取"


async def test_web_turn_gate_serializes_concurrent_turns(monkeypatch) -> None:
    """同 session_id 的两个并发轮次不得交错执行（seq/历史互踩防护）。"""
    from app.modules.safety.api.business_agent import _execute_turn_and_persist

    overlaps: list[str] = []

    async def fake_run_turn(message, deps, *, message_history=None):
        overlaps.append(f"in:{message}")
        await asyncio.sleep(0.02)
        overlaps.append(f"out:{message}")
        return {"answer": "ans", "messages": [], "pending_action": None, "sources": None}

    trace = _patch_web_turn_seams(monkeypatch, fake_run_turn)

    class _Db:
        async def commit(self):
            trace.append("commit")

    db = _Db()
    t1 = asyncio.create_task(_execute_turn_and_persist(
        db, message="m1", session_id="same", feishu_user_id=None))
    t2 = asyncio.create_task(_execute_turn_and_persist(
        db, message="m2", session_id="same", feishu_user_id=None))
    await asyncio.gather(t1, t2)

    # 串行化：任一轮次的 out 必须先于另一轮次的 in
    assert overlaps in (
        ["in:m1", "out:m1", "in:m2", "out:m2"],
        ["in:m2", "out:m2", "in:m1", "out:m1"],
    ), f"并发轮次发生交错: {overlaps}"


# ═══════════════════════════════════════════════════════════════
# 4. bitable AI 审查后台任务：独立 session
# ═══════════════════════════════════════════════════════════════


async def test_rectification_review_bg_opens_own_session(monkeypatch) -> None:
    """AI 整改初审后台任务必须自开 session（不得捕获事件处理链路的 service）。"""
    import app.core.database as db_mod
    import app.modules.safety.service as service_mod
    from app.modules.safety.feishu import bitable_handler as bh

    opened: list = []

    class _OwnSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    def fake_factory():
        session = _OwnSession()
        opened.append(session)
        return session

    seen: list = []

    class _FakeHazardSvc:
        async def run_rectification_review(self, hazard_id):
            seen.append((self._session, hazard_id))

    class _FakeService:
        def __init__(self, session):
            self._session = session
            self.hazard = _FakeHazardSvc()
            self.hazard._session = session

    monkeypatch.setattr(db_mod, "async_session_factory", fake_factory)
    monkeypatch.setattr(service_mod, "SafetyService", _FakeService)

    hazard_id = uuid.uuid4()
    await bh._run_rectification_review_bg(hazard_id)

    assert len(opened) == 1, "后台任务应经 async_session_factory 自开会话"
    assert seen == [(opened[0], hazard_id)], "审查应在自开会话上执行"
