"""事件层仓储+引擎测试（B 层，真 PG 回滚式 db_session）。

核心不变量（冒烟②验收口径的自动化底座）：
- 落库幂等：同 (source, external_id) 重投 → duplicate，行数不增
- cursor 推进仅在所覆盖 Trigger 全部落库后（crash 窗口重启 → 不重放不漏单）
- Fast Path 拦截同样落库留痕（disposition=filtered+原因）
- Thread 按 thread_key 单行滚动
- cron_tick 源：首见登记基准零回溯；网格点幂等
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.platform.superagent.ingest import (
    apply_cursor_updates,
    ingest_draft,
    ingest_source_once,
    load_cursors,
)
from app.platform.superagent.models import (
    AgentSource,
    AgentSourceCursor,
    AgentThread,
    AgentTrigger,
)
from app.platform.superagent.sources import (
    CronTickSource,
    Source,
    SourceRegistry,
    TriggerDraft,
)

# ── 测试数据纪律：source.name 一律 test. 前缀；回滚式 session 不落库 ──


class EchoSource(Source):
    """回放式假源：固定返回构造时给定的草稿与读位（测试注入用）。"""

    kind = "test_echo"

    def __init__(
        self, drafts: list[TriggerDraft], cursor_updates: dict[str, Any] | None = None,
    ) -> None:
        self.drafts = drafts
        self.cursor_updates = cursor_updates or {}

    async def poll(self, session: Any, source_row: AgentSource, cursors: dict[str, Any]):
        from app.platform.superagent.sources import PollResult

        return PollResult(drafts=self.drafts, cursor_updates=self.cursor_updates)


async def _make_source(db_session, *, name: str, config: dict | None = None) -> AgentSource:
    row = AgentSource(kind="test_echo", name=name, config=config or {}, enabled=True)
    db_session.add(row)
    await db_session.flush()
    return row


def _draft(n: str, *, actor: dict | None = None, thread: str = "t:1") -> TriggerDraft:
    return TriggerDraft(
        external_id=f"ext-{n}", thread_key=thread, actor=actor or {"id": "u1"}, human=True,
    )


async def test_ingest_draft_idempotent(db_session) -> None:
    """同草稿投两次：一行；第二次 duplicate 且处置轨迹追加。"""
    src = await _make_source(db_session, name="test.idem")

    outcome1, row1 = await ingest_draft(db_session, src, _draft("a"))
    outcome2, row2 = await ingest_draft(db_session, src, _draft("a"))

    assert outcome1 == "stored" and outcome2 == "duplicate"
    assert row1.id == row2.id
    steps = [s["step"] for s in row2.disposition]
    assert steps == ["stored", "duplicate"]
    count = len(
        (await db_session.execute(select(AgentTrigger.id).where(AgentTrigger.source_id == src.id))).scalars().all()
    )
    assert count == 1


async def test_fastpath_filtered_still_stored_with_reason(db_session) -> None:
    """机器人自身消息：落库留痕 + disposition 含 filtered 原因，不进后续链路。"""
    src = await _make_source(
        db_session, name="test.fastpath", config={"self_actors": ["bot_1"]},
    )
    draft = _draft("b", actor={"id": "bot_1"})

    outcome, row = await ingest_draft(db_session, src, draft)

    assert outcome == "stored"
    steps = [s["step"] for s in row.disposition]
    assert steps == ["stored", "filtered"]
    assert row.disposition[1]["reason"] == "self_actor:bot_1"


async def test_thread_upsert_single_row(db_session) -> None:
    """同 thread_key 两次落库 → Thread 单行、last_trigger_at 推进。"""
    src = await _make_source(db_session, name="test.thread")
    await ingest_draft(db_session, src, _draft("c1", thread="t:hazard-1"))
    await ingest_draft(db_session, src, _draft("c2", thread="t:hazard-1"))

    threads = (
        await db_session.execute(select(AgentThread).where(AgentThread.thread_key == "t:hazard-1"))
    ).scalars().all()
    assert len(threads) == 1
    assert threads[0].last_trigger_at is not None


async def test_source_round_stores_and_advances_cursor(db_session) -> None:
    """整轮：草稿全部落库 + 读位同轮写入（正常路径）。"""
    src = await _make_source(db_session, name="test.round")
    registry = SourceRegistry()
    registry.register(EchoSource([_draft("r1"), _draft("r2")], {"watermark": "w-2"}))

    summary = await ingest_source_once(db_session, src, registry=registry)

    assert summary == {"stored": 2, "duplicate": 0, "filtered": 0, "polled": 2}
    cursors = await load_cursors(db_session, src.id)
    assert cursors == {"watermark": "w-2"}


async def test_crash_window_restart_no_replay_no_loss(db_session) -> None:
    """crash 窗口不变量：落 Trigger 后、推 cursor 前崩溃 → 重启重拉同批全部
    duplicate（不重放）、cursor 补推（不漏单）、行数不变。"""
    src = await _make_source(db_session, name="test.crash")
    drafts = [_draft("k1"), _draft("k2")]

    # 「进程 A」：草稿落库，未推读位即崩溃（无 cursor 写入）
    for d in drafts:
        await ingest_draft(db_session, src, d)
    assert await load_cursors(db_session, src.id) == {}

    # 「进程 B」重启：同批重拉（假源固定回放）
    registry = SourceRegistry()
    registry.register(EchoSource(drafts, {"watermark": "w-2"}))
    summary = await ingest_source_once(db_session, src, registry=registry)

    assert summary["stored"] == 0
    assert summary["duplicate"] == 2
    rows = (
        await db_session.execute(select(AgentTrigger).where(AgentTrigger.source_id == src.id))
    ).scalars().all()
    assert len(rows) == 2  # 不重放：零新增
    assert await load_cursors(db_session, src.id) == {"watermark": "w-2"}  # 不漏单：读位补推


async def test_apply_cursor_upsert(db_session) -> None:
    """读位 upsert：同名覆盖、异名并存。"""
    src = await _make_source(db_session, name="test.cursor")
    await apply_cursor_updates(db_session, src.id, {"a": 1})
    await apply_cursor_updates(db_session, src.id, {"a": 2, "b": "x"})

    cursors = await load_cursors(db_session, src.id)
    assert cursors == {"a": 2, "b": "x"}
    rows = (
        await db_session.execute(
            select(AgentSourceCursor).where(AgentSourceCursor.source_id == src.id)
        )
    ).scalars().all()
    assert len(rows) == 2


async def test_cron_tick_first_sight_rebases_without_flood(db_session) -> None:
    """cron_tick 首见：只登记基准零回溯（防启用瞬间洪泛）。"""
    src = AgentSource(
        kind="cron_tick", name="test.cron",
        config={"job": "testjob", "schedule": {"strategy": "interval", "interval_seconds": 3600}},
        enabled=True,
    )
    db_session.add(src)
    await db_session.flush()

    plugin = CronTickSource()
    result = await plugin.poll(db_session, src, {})

    assert result.drafts == []
    assert result.rebase is True
    assert "last_tick" in result.cursor_updates


async def test_cron_tick_grid_emits_and_idempotent(db_session) -> None:
    """cron_tick 网格：读位 3 秒前、interval=1s → 2-3 发；同批再投全 duplicate。"""
    now = datetime.now(UTC)
    src = AgentSource(
        kind="cron_tick", name="test.cron2",
        config={"job": "gridjob", "schedule": {"strategy": "interval", "interval_seconds": 1}},
        enabled=True,
    )
    db_session.add(src)
    await db_session.flush()

    plugin = CronTickSource()
    result = await plugin.poll(
        db_session, src, {"last_tick": (now - timedelta(seconds=3)).isoformat()},
    )
    assert 1 <= len(result.drafts) <= 4

    for draft in result.drafts:
        outcome, _ = await ingest_draft(db_session, src, draft)
        assert outcome == "stored"
    for draft in result.drafts:  # 重启重放同批
        outcome, _ = await ingest_draft(db_session, src, draft)
        assert outcome == "duplicate"
    assert all(d.external_id.startswith("gridjob:") for d in result.drafts)


async def test_unknown_kind_reports_error(db_session) -> None:
    """未知插件类型：逐源容错，不炸整轮。"""
    src = AgentSource(kind="no_such_kind", name="test.unknown", config={}, enabled=True)
    db_session.add(src)
    await db_session.flush()

    registry = SourceRegistry()  # 空注册表
    summary = await ingest_source_once(db_session, src, registry=registry)
    assert summary == {"error": "unknown_kind:no_such_kind"}


@pytest.mark.parametrize("external_id", ["a" * 512, "job:2026-11-02T10:00:00+08:00"])
async def test_trigger_external_id_length_bounds(db_session, external_id: str) -> None:
    """external_id 达列长上限可用（512 内）。"""
    src = await _make_source(db_session, name=f"test.len.{uuid.uuid4().hex[:6]}")
    draft = TriggerDraft(external_id=external_id, thread_key="t:len")
    outcome, _ = await ingest_draft(db_session, src, draft)
    assert outcome == "stored"


async def test_duplicate_disposition_capped(db_session) -> None:
    """处置轨迹上限：重复投递超 50 次后不再追加（防 JSONB 无界增长）。"""
    src = await _make_source(db_session, name="test.cap")
    draft = _draft("cap")
    await ingest_draft(db_session, src, draft)
    for _ in range(80):
        _, row = await ingest_draft(db_session, src, draft)
    assert len(row.disposition) == 50
