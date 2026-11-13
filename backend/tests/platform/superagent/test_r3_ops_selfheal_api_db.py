"""R3 观测 REST —— 工单列表 / 全时间线回放 / 重试（S4，直调 handler 函数）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select


@pytest_asyncio.fixture(autouse=True)
async def _purge_r3_rows():
    """清理本文件测试创建的 R3 行——按测试工单特征圈定（short_name 前缀 r3:）。

    不按 executor 全删：dev 库可能有真机冒烟/观测留下的活跃工单（2026-11-13
    教训——无条件全删把真机冒烟工单一起清了）。本文件 _make_ticket 恒用
    short_name="r3:api"，按此前缀+源名圈定。
    """
    yield
    from app.platform.superagent.models import (
        AgentEffect,
        AgentInput,
        AgentSource,
        AgentTask,
        AgentTaskSubscription,
        AgentTrigger,
    )
    from tests.conftest import _test_session_factory

    async with _test_session_factory() as s:
        task_ids = [
            str(t.id)
            for t in (
                await s.execute(
                    select(AgentTask).where(
                        AgentTask.short_name.in_(("r3:api", "r3:rag"))
                    )
                )
            ).scalars().all()
        ]
        if task_ids:
            await s.execute(
                AgentInput.__table__.delete().where(AgentInput.task_id.in_(task_ids))
            )
            await s.execute(
                AgentTaskSubscription.__table__.delete().where(
                    AgentTaskSubscription.task_id.in_(task_ids)
                )
            )
            await s.execute(
                AgentTask.__table__.delete().where(AgentTask.id.in_(task_ids))
            )
        src = (
            await s.execute(
                select(AgentSource).where(AgentSource.name == "safety.ops.selfheal")
            )
        ).scalar_one_or_none()
        if src is not None:
            # 只删挂在本文件测试工单上的 trigger（同 thread 的任务行已按 id 清），
            # 不按 source_id 全删——防误清真机冒烟轮留下的源/读位
            trig_ids = [
                t.id for t in (
                    await s.execute(
                        select(AgentTrigger).where(
                            AgentTrigger.source_id == src.id,
                            AgentTrigger.thread_key.like("ops:job:r3api测试:%"),
                        )
                    )
                ).scalars().all()
            ]
            if trig_ids:
                await s.execute(
                    AgentTrigger.__table__.delete().where(
                        AgentTrigger.id.in_(trig_ids)
                    )
                )
            await s.execute(
                AgentSource.__table__.delete().where(AgentSource.id == src.id)
            )
        await s.execute(
            AgentEffect.__table__.delete().where(
                AgentEffect.dedupe_key.like("r3:%")
                | AgentEffect.kind.in_(("r3_repair", "r3_closure_card"))
            )
        )
        await s.commit()


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

    await _make_ticket(db_session, stage="diagnosed")
    await _make_ticket(db_session, stage="needs_human")
    closed = await _make_ticket(db_session, status="ended")

    resp = await list_tickets(page=1, page_size=20, stage=None, signal=None,
                              job_name=None, db=db_session, _user=None)
    data = _resp_data(resp)
    assert data["meta"]["total"] == 3
    closed_rows = [x for x in data["data"] if x["stage"] == "closed"]
    assert len(closed_rows) == 1 and closed_rows[0]["id"] == str(closed.id)

    resp2 = await list_tickets(page=1, page_size=20, stage="needs_human",
                               signal=None, job_name=None, db=db_session, _user=None)
    data2 = _resp_data(resp2)
    assert data2["meta"]["total"] == 1
    assert data2["data"][0]["stage"] == "needs_human"
    assert data2["data"][0]["root_cause_class"] == "upstream_outage"
    assert data2["data"][0]["dep_endpoints"] == ["10.0.0.9:9550"]
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
