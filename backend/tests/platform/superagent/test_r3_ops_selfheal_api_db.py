"""R3 观测 REST —— 工单列表 / 全时间线回放 / 重试（S4，直调 handler 函数）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select


@pytest_asyncio.fixture(autouse=True)
async def _purge_r3_rows():
    """R3 行清理（快照差集法，R3 三期 T1）。

    本文件旧 purge 的 task 侧已按 short_name=r3:api 收窄（2026-11-13 教训），
    但仍删 selfheal 源行 + LIKE 'r3:%' 全清 effect——开闸后同样毁灭真机数据；
    统一换快照差集（只删快照外新增，源行永不动）。
    """
    from tests.platform.superagent._r3_snapshot_purge import (
        purge_new_r3_rows,
        snapshot_r3_rows,
    )

    snap = await snapshot_r3_rows()
    yield
    await purge_new_r3_rows(snap)


async def _make_ticket(db_session, *, stage: str = "diagnosed", status: str = "open"):
    import uuid as uuid_mod

    from app.platform.superagent.models import (
        AgentEffect,
        AgentTask,
        AgentTaskSubscription,
        AgentTrigger,
    )
    from app.platform.superagent.sources import TriggerDraft
    from app.platform.superagent.ingest import ingest_draft
    from app.platform.superagent.models import AgentSource

    src = (
        await db_session.execute(
            select(AgentSource).where(AgentSource.name == "safety.ops.selfheal")
        )
    ).scalar_one_or_none()
    if src is None:
        src = AgentSource(
            kind="ops_scan", name="safety.ops.selfheal", enabled=True,
            config={"evaluate": False},
        )
        db_session.add(src)
        await db_session.flush()
    thread = "ops:job:r3api测试:2026-11-10"
    draft = TriggerDraft(
        external_id="ops:job:r3api测试:2026-11-10:failed", thread_key=thread,
        payload={"signal": "job_failed", "job_name": "r3api测试",
                 "fired_date": "2026-11-10"},
    )
    _, trigger = await ingest_draft(db_session, src, draft)
    task = AgentTask(
        id=uuid_mod.uuid4(), short_name="r3:api", title="R3 api 测试",
        executor="r3_ops_heal", origin_trigger_id=trigger.id,
        mandate={"rule_id": "r3_ops_failure"},
        stage_facts={"r3": {
            "stage": stage, "signal": "job_failed", "job_name": "r3api测试",
            "root_cause_class": "upstream_outage", "confidence": 0.9,
            "executed": [], "repair_rounds": 0, "dep_endpoints": ["10.0.0.9:9550"],
        }},
        status=status, outcome="closed" if status == "ended" else None,
        ended_at=datetime.now(UTC) if status == "ended" else None,
    )
    db_session.add(task)
    db_session.add(AgentTaskSubscription(task_id=task.id, thread_key=thread))
    db_session.add(AgentEffect(
        kind="dm_admin", dedupe_key=f"r3:diag:{task.id}:x",
        payload={"task_id": str(task.id), "text": "诊断卡"}, status="done",
    ))
    await db_session.flush()
    return task


async def test_list_tickets_stage_filter(db_session) -> None:
    from app.modules.safety.api.ops_selfheal import list_tickets

    from app.platform.superagent.models import AgentTask as _AT

    base_total = (
        await db_session.execute(
            select(func.count()).select_from(_AT).where(_AT.executor == "r3_ops_heal")
        )
    ).scalar_one()
    base_nh = (
        await db_session.execute(
            select(func.count()).select_from(_AT).where(
                _AT.executor == "r3_ops_heal",
                _AT.status == "open",
                _AT.stage_facts["r3"]["stage"].astext == "needs_human",
            )
        )
    ).scalar_one()
    diag = await _make_ticket(db_session, stage="diagnosed")
    human = await _make_ticket(db_session, stage="needs_human")
    closed = await _make_ticket(db_session, status="ended")

    resp = await list_tickets(page=1, page_size=200, stage=None, signal=None,
                              job_name=None, db=db_session, _user=None)
    data = _resp_data(resp)
    # 基线差集+在场断言（开闸后真机工单持续进出，全局等值断言必竞态）
    assert data["meta"]["total"] >= base_total + 3
    ids = {x["id"] for x in data["data"]}
    assert {str(t.id) for t in (diag, human, closed)} <= ids
    closed_ids = {x["id"] for x in data["data"] if x["stage"] == "closed"}
    assert str(closed.id) in closed_ids

    resp2 = await list_tickets(page=1, page_size=50, stage="needs_human",
                               signal=None, job_name=None, db=db_session, _user=None)
    data2 = _resp_data(resp2)
    assert data2["meta"]["total"] >= base_nh + 1
    ours = next(x for x in data2["data"] if x["id"] == str(human.id))
    assert ours["stage"] == "needs_human"
    assert ours["root_cause_class"] == "upstream_outage"
    assert ours["dep_endpoints"] == ["10.0.0.9:9550"]
    await db_session.rollback()


def _resp_data(resp):
    import json

    return json.loads(getattr(resp, "body", b"{}").decode())


async def test_ticket_timeline_replay(db_session) -> None:
    from app.modules.safety.api.ops_selfheal import ticket_timeline

    task = await _make_ticket(db_session)
    resp = await ticket_timeline(str(task.id), db=db_session, _user=None)
    data = _resp_data(resp)["data"]
    kinds = [e["kind"] for e in data["events"]]
    assert "trigger" in kinds and "effect" in kinds  # 时间线聚合含 trigger→effect
    trig = next(e for e in data["events"] if e["kind"] == "trigger")
    assert trig["signal"] == "job_failed"
    eff = next(e for e in data["events"] if e["kind"] == "effect")
    assert eff["effect_kind"] == "dm_admin" and eff["status"] == "done"
    assert data["ticket"]["id"] == str(task.id)
    await db_session.rollback()


async def test_retry_ticket_semantics(db_session) -> None:
    from app.core.exceptions import AppException
    from app.modules.safety.api.ops_selfheal import retry_ticket
    from app.platform.superagent.models import AgentInput

    task = await _make_ticket(db_session)
    resp = await retry_ticket(str(task.id), db=db_session, _admin=None)
    assert _resp_data(resp)["data"]["queued"] is True
    inputs = (
        await db_session.execute(
            select(AgentInput).where(AgentInput.task_id == task.id, AgentInput.kind == "system")
        )
    ).scalars().all()
    assert len(inputs) == 1 and inputs[0].payload["type"] == "retry"
    await db_session.commit()

    # 重复重试：已有未读 → 不重复投
    resp2 = await retry_ticket(str(task.id), db=db_session, _admin=None)
    assert "已有未读" in _resp_data(resp2)["data"]["note"]

    # ended 工单 → 409
    task.status = "ended"
    task.outcome = "closed"
    await db_session.flush()
    with pytest.raises(AppException) as exc:
        await retry_ticket(str(task.id), db=db_session, _admin=None)
    assert exc.value.status_code == 409
    await db_session.rollback()


# ═══════════════════════════════════════════════════════════════
# 二期 L2 一键执行：extend-window
# ═══════════════════════════════════════════════════════════════


async def test_extend_window_success_and_once_per_day(db_session, monkeypatch) -> None:
    """一键执行：覆写生效+留痕+结果卡；同 job 当日第二次 409。"""
    from app.modules.safety.api.ops_selfheal import extend_window
    from app.modules.safety.service.ops_selfheal_r3 import window_override

    # 桩 enqueue_effect（DM 不真发，只断言入队）
    from app.platform.superagent import effects as fx

    enqueued: list[tuple[str, dict]] = []

    async def _fake_enqueue(session, kind, payload, **kw):
        enqueued.append((kind, dict(payload)))
        return None

    monkeypatch.setattr(fx, "enqueue_effect", _fake_enqueue)

    window_override.reset_overrides()
    try:
        task = await _make_ticket(db_session, stage="diagnosed")
        resp = await extend_window(
            str(task.id), body={"args": {"until_hour": 15, "until_minute": 0}},
            db=db_session, _admin=None,
        )
        data = _resp_data(resp)
        assert data["data"]["job_name"] == "r3api测试"
        assert data["data"]["new_window"] == "15:00"
        # 覆写 dict 生效（job_window_end 读口）
        from datetime import date

        end = __import__(
            "app.modules.safety.service.ops_selfheal_r3.scan_source",
            fromlist=["job_window_end"],
        ).job_window_end("r3api测试", date.today())
        assert (end.hour, end.minute) == (15, 0)
        # 留痕（AgentInput system l2_window_extend）
        from app.platform.superagent.models import AgentInput

        inputs = (
            await db_session.execute(
                select(AgentInput).where(AgentInput.task_id == task.id)
            )
        ).scalars().all()
        assert any(
            (i.payload or {}).get("type") == "l2_window_extend" and i.payload["ok"] is True
            for i in inputs
        )
        # 结果卡入队
        assert any(k == "dm_admin" and "窗口延长" in (p.get("text") or "")
                   for k, p in enqueued)
        await db_session.flush()

        # 同 job 当日第二次：409（AppException）
        import pytest as _pytest
        from app.core.exceptions import AppException

        task2 = await _make_ticket(db_session, stage="diagnosed")
        with _pytest.raises(AppException) as ei:
            await extend_window(
                str(task2.id), db=db_session, _admin=None, body=None,
            )
        assert ei.value.status_code == 409
        assert "当日已延长" in ei.value.message
    finally:
        window_override.reset_overrides()
    await db_session.rollback()


async def test_extend_window_rejects_closed_and_nonjob(db_session, monkeypatch) -> None:
    """非 open 工单 409；无 job_name 工单 400。"""
    from app.core.exceptions import AppException
    from app.modules.safety.api.ops_selfheal import extend_window
    from app.modules.safety.service.ops_selfheal_r3 import window_override
    from app.platform.superagent import effects as fx

    async def _fake_enqueue(session, kind, payload, **kw):
        return None

    monkeypatch.setattr(fx, "enqueue_effect", _fake_enqueue)
    window_override.reset_overrides()
    try:
        closed = await _make_ticket(db_session, status="ended")
        import pytest as _pytest

        with _pytest.raises(AppException) as e1:
            await extend_window(str(closed.id), db=db_session, _admin=None, body=None)
        assert e1.value.status_code == 409

        # 无 job_name（构造一个 rag 信号形态工单）
        import uuid as uuid_mod

        from app.platform.superagent.models import AgentSource, AgentTask, AgentTrigger

        src = (
            await db_session.execute(
                select(AgentSource).where(AgentSource.name == "safety.ops.selfheal")
            )
        ).scalar_one()
        trig = AgentTrigger(
            id=uuid_mod.uuid4(), source_id=src.id,
            external_id="ops:rag:2026-11-12:degraded:t",
            thread_key="ops:rag:2026-11-12",
            actor={"id": "rag_health", "type": "probe"},
            payload={"signal": "rag_degraded"},
        )
        db_session.add(trig)
        await db_session.flush()
        rag_task = AgentTask(
            id=uuid_mod.uuid4(), short_name="r3:rag", title="R3 rag",
            executor="r3_ops_heal", origin_trigger_id=trig.id,
            mandate={"rule_id": "r3_ops_rag_signal"},
            stage_facts={"r3": {"stage": "diagnosed", "signal": "rag_degraded"}},
            status="open",
        )
        db_session.add(rag_task)
        await db_session.flush()
        with _pytest.raises(AppException) as e2:
            await extend_window(str(rag_task.id), db=db_session, _admin=None, body=None)
        assert e2.value.status_code == 400
        assert "无关联 job" in e2.value.message
    finally:
        window_override.reset_overrides()
    await db_session.rollback()


# ═══════════════════════════════════════════════════════════════
# 观测统计面 GET /ops-selfheal/stats（三期 T5）
# ═══════════════════════════════════════════════════════════════


async def test_stats_aggregates_baseline_diff(db_session) -> None:
    """统计聚合：开出/收口/滞留/信号分布/平均存活——基线差集断言（真机行免疫）。"""
    from datetime import UTC, datetime, timedelta

    from app.modules.safety.api.ops_selfheal import ops_selfheal_stats
    from app.platform.superagent.models import AgentTask as _AT
    from sqlalchemy import update

    base = _resp_data(await ops_selfheal_stats(db=db_session, _user=None))["data"]

    fresh = await _make_ticket(db_session, stage="diagnosed")  # 新开单（job_failed）
    stale = await _make_ticket(db_session, stage="needs_human")  # 滞留>24h
    closed = await _make_ticket(db_session, status="ended")  # 收口
    # stale 单：signals_seen 双信号（分布展平口径）+ 25h 前创建
    facts = dict(stale.stage_facts or {})
    facts["r3"] = {**facts["r3"],
                   "signals_seen": ["push_failed", "ai_call_failed"]}
    await db_session.execute(
        update(_AT).where(_AT.id == stale.id).values(
            created_at=datetime.now(UTC) - timedelta(hours=25),
            stage_facts=facts,
        )
    )
    await db_session.flush()

    data = _resp_data(await ops_selfheal_stats(db=db_session, _user=None))["data"]
    assert data["open_total"] == base["open_total"] + 2
    assert data["closed_total"] == base["closed_total"] + 1
    assert data["opened_7d"] == base["opened_7d"] + 3
    assert data["closed_7d"] == base["closed_7d"] + 1
    assert data["stale_open_gt_24h"] == base["stale_open_gt_24h"] + 1
    # 信号分布（signals_seen 展平 + 无 seen 回退 r3.signal）
    assert data["by_signal"]["push_failed"] == base["by_signal"].get("push_failed", 0) + 1
    assert data["by_signal"]["ai_call_failed"] == base["by_signal"].get("ai_call_failed", 0) + 1
    assert data["by_signal"]["job_failed"] >= base["by_signal"].get("job_failed", 0) + 2
    assert data["avg_lifetime_minutes"] >= 0  # 已收口均值键恒在场
    await db_session.rollback()
