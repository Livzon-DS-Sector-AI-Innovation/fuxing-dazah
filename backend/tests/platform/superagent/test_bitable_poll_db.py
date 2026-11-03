"""bitable_poll 源测试 —— 指纹幂等 / 读位水位 / 源→effect 直派生 / crash 窗口。"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.platform.superagent.bitable_poll import (
    register_bitable_fetcher,
    relevant_fingerprint,
)
from app.platform.superagent.ingest import ingest_source_once, load_cursors
from app.platform.superagent.models import AgentEffect, AgentSource, AgentTrigger
from app.platform.superagent.sources import SourceRegistry, register_builtin_sources


@pytest.fixture()
def registry() -> SourceRegistry:
    """独立注册表（含 bitable_poll/cron_tick 内置插件）。"""
    return register_builtin_sources(SourceRegistry())


RELEVANT = ["整改状态", "隐患级别（人工）", "检查日期", "责任部门", "检查类别"]


def _rec(record_id: str, status: str = "未关闭", level: str = "", lms: int = 1000,
         supervision: str = "") -> dict[str, Any]:
    return {
        "record_id": record_id,
        "last_modified_time": lms,
        "fields": {
            "整改状态": [{"type": "text", "text": status}],
            "隐患级别（人工）": [{"type": "text", "text": level}] if level else None,
            "督办等级": [{"type": "text", "text": supervision}] if supervision else None,
        },
    }


# ═══════════════════════════════════════════════════════════════
# 指纹纯函数
# ═══════════════════════════════════════════════════════════════


def test_fingerprint_stable_for_same_relevant_values() -> None:
    a = relevant_fingerprint(_rec("r1")["fields"], RELEVANT)
    b = relevant_fingerprint(_rec("r2")["fields"], RELEVANT)  # 不同 record_id 同字段
    assert a == b


def test_fingerprint_ignores_supervision_field_changes() -> None:
    """自写回声抑制核心：督办等级列（未进指纹）变化 → 指纹不变 → external_id 不变。"""
    before = relevant_fingerprint(_rec("r1", supervision="")["fields"], RELEVANT)
    after = relevant_fingerprint(_rec("r1", supervision="一般预警")["fields"], RELEVANT)
    assert before == after


def test_fingerprint_changes_on_relevant_field_change() -> None:
    before = relevant_fingerprint(_rec("r1", status="未关闭")["fields"], RELEVANT)
    after = relevant_fingerprint(_rec("r1", status="已关闭")["fields"], RELEVANT)
    assert before != after


def test_fingerprint_flattens_rich_text() -> None:
    """富文本 [{"type":"text","text":"x"}] 与纯文本 "x" 同指纹（Bitable 返回形态差异不致重放）。"""
    rich = {"整改状态": [{"type": "text", "text": "未关闭"}]}
    plain = {"整改状态": "未关闭"}
    assert relevant_fingerprint(rich, RELEVANT) == relevant_fingerprint(plain, RELEVANT)


# ═══════════════════════════════════════════════════════════════
# 插件 poll + 直派生（B 层）
# ═══════════════════════════════════════════════════════════════


class _FetcherHolder:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.calls: list[int] = []

    async def __call__(self, watermark_ms: int) -> list[dict[str, Any]]:
        self.calls.append(watermark_ms)
        return self.records


async def _make_bitable_source(db_session, holder: _FetcherHolder) -> AgentSource:
    fname = f"test_fetch_{uuid.uuid4().hex[:8]}"
    register_bitable_fetcher(fname, holder)
    row = AgentSource(
        kind="bitable_poll", name=f"test.bp.{uuid.uuid4().hex[:8]}",
        config={"fetcher": fname, "thread_prefix": "hazard",
                "relevant_fields": RELEVANT, "effect_kind": "supervision_writeback"},
        enabled=True,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def test_first_sight_baseline_no_flood(db_session, registry) -> None:
    holder = _FetcherHolder([_rec("r1")])
    src = await _make_bitable_source(db_session, holder)

    summary = await ingest_source_once(db_session, src, registry=registry)

    assert summary == {"stored": 0, "duplicate": 0, "filtered": 0, "polled": 0, "rebased": True}
    assert holder.calls == []  # 首见未拉取（基准登记后下轮起拉）
    cursors = await load_cursors(db_session, src.id)
    assert "last_modified_ms" in cursors


async def test_poll_stores_triggers_and_derives_effects(db_session, registry) -> None:
    """正常轮：Trigger 落库 + supervision_writeback effect 直派生（仅 stored）。"""
    holder = _FetcherHolder([_rec("r1", lms=2000), _rec("r2", lms=2100)])
    src = await _make_bitable_source(db_session, holder)

    # 首见登记基准
    await ingest_source_once(db_session, src, registry=registry)
    # 手动把水位拨回，模拟「基准后有变化」
    cursors = await load_cursors(db_session, src.id)
    from app.platform.superagent.models import AgentSourceCursor

    cursor_row = (
        await db_session.execute(
            select(AgentSourceCursor).where(AgentSourceCursor.source_id == src.id)
        )
    ).scalar_one()
    cursor_row.value = 1500
    await db_session.flush()

    summary = await ingest_source_once(db_session, src, registry=registry)
    assert summary["stored"] == 2
    assert summary["derived_effects"] == 2

    triggers = (
        await db_session.execute(select(AgentTrigger).where(AgentTrigger.source_id == src.id))
    ).scalars().all()
    assert {t.external_id.split(":")[0] for t in triggers} == {"r1", "r2"}
    effects = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.kind == "supervision_writeback")
        )
    ).scalars().all()
    assert len(effects) == 2
    # 水位推进到批内最大
    cursors = await load_cursors(db_session, src.id)
    assert cursors["last_modified_ms"] == 2100


async def test_crash_window_no_duplicate_effects(db_session, registry) -> None:
    """crash 窗口：Trigger 落库+effect 入队后、水位未推即崩 → 重启重拉：
    全 duplicate、**零新增 effect**（直派生只对 stored）、水位补推。"""
    holder = _FetcherHolder([_rec("r1", lms=2000)])
    src = await _make_bitable_source(db_session, holder)

    await ingest_source_once(db_session, src, registry=registry)  # 首见基准
    from app.platform.superagent.models import AgentSourceCursor

    cursor_row = (
        await db_session.execute(
            select(AgentSourceCursor).where(AgentSourceCursor.source_id == src.id)
        )
    ).scalar_one()
    cursor_row.value = 1500
    await db_session.flush()

    # 「进程 A」：完整一轮后手动回滚水位（模拟崩在推水位前）
    await ingest_source_once(db_session, src, registry=registry)
    cursor_row.value = 1500
    await db_session.flush()

    # 「进程 B」重启重拉同批
    summary = await ingest_source_once(db_session, src, registry=registry)
    assert summary["stored"] == 0
    assert summary["duplicate"] == 1
    assert summary.get("derived_effects", 0) == 0  # 零新增 effect

    effects = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.kind == "supervision_writeback")
        )
    ).scalars().all()
    assert len(effects) == 1  # 不重放：effect 恰一条
    cursors = await load_cursors(db_session, src.id)
    assert cursors["last_modified_ms"] == 2000  # 不漏单：水位补推


async def test_echo_suppression_end_to_end(db_session, registry) -> None:
    """端到端回声抑制：督办回写只改 lms+督办等级 → 重拉 → duplicate → 零派生。"""
    holder = _FetcherHolder([])
    src = await _make_bitable_source(db_session, holder)

    await ingest_source_once(db_session, src, registry=registry)
    from app.platform.superagent.models import AgentSourceCursor

    cursor_row = (
        await db_session.execute(
            select(AgentSourceCursor).where(AgentSourceCursor.source_id == src.id)
        )
    ).scalar_one()
    cursor_row.value = 1500
    await db_session.flush()

    holder.records = [_rec("r1", lms=2000)]
    await ingest_source_once(db_session, src, registry=registry)  # 首见 r1：stored+effect
    # 督办回写后（lms 变化、督办等级有值、相关字段未变）
    holder.records = [_rec("r1", lms=3000, supervision="一般预警")]
    summary = await ingest_source_once(db_session, src, registry=registry)

    assert summary["stored"] == 0
    assert summary["duplicate"] == 1
    assert summary.get("derived_effects", 0) == 0


async def test_unknown_fetcher_noop(db_session, registry) -> None:
    src = AgentSource(
        kind="bitable_poll", name=f"test.bp.bad.{uuid.uuid4().hex[:6]}",
        config={"fetcher": "no_such"}, enabled=True,
    )
    db_session.add(src)
    await db_session.flush()
    summary = await ingest_source_once(db_session, src, registry=registry)
    assert summary == {"stored": 0, "duplicate": 0, "filtered": 0, "polled": 0}
