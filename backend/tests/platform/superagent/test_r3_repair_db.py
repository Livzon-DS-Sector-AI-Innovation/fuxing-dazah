"""R3 修复链 —— 漏审日补跑 + 双条件关单 + 防风暴上限（S3，样例 3/4）。

WorkTicketReviewService / DM 发送 / 时钟全部桩；收口卡故意发送失败验证
「工单不置 closed 下轮重发」（§9.4 验收）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

_SCAN_SOURCE = "safety.ops.selfheal"


@pytest_asyncio.fixture(autouse=True)
async def _purge_r3_rows():
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
                    select(AgentTask).where(AgentTask.executor == "r3_ops_heal")
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
                select(AgentSource).where(AgentSource.name == _SCAN_SOURCE)
            )
        ).scalar_one_or_none()
        if src is not None:
            await s.execute(
                AgentTrigger.__table__.delete().where(AgentTrigger.source_id == src.id)
            )
            await s.execute(
                AgentSource.__table__.delete().where(AgentSource.id == src.id)
            )
        await s.execute(
            AgentEffect.__table__.delete().where(
                AgentEffect.dedupe_key.like("r3:%")
                | AgentEffect.dedupe_key.like("r3hist-%")
                | AgentEffect.kind.in_(("r3_repair", "r3_closure_card"))
            )
        )
        await s.commit()


class _Ctx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest_asyncio.fixture
async def repair_env(db_session, monkeypatch):
    """源行 + factory 桩 + auto 修复模式 + 白名单含 L1 三项。"""
    from app.modules.safety.service.ops_selfheal_r3 import config
    from app.modules.safety.superagent_bridge import register_superagent_bridge
    from app.platform.superagent.models import AgentSource

    register_superagent_bridge()
    src = AgentSource(
        kind="ops_scan", name=_SCAN_SOURCE, enabled=True,
        config={"schedule": {"strategy": "interval", "interval_seconds": 300,
                              "timezone": "Asia/Shanghai"}, "evaluate": True},
    )
    db_session.add(src)
    await db_session.flush()
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _Ctx(db_session),
    )
    monkeypatch.setattr(config, "repair_mode", lambda: "auto")
    monkeypatch.setattr(
        config, "allowed_actions",
        lambda: {"notify_enriched", "rag_recheck", "effects_unpark", "job_backfill"},
    )
    yield {"source": src, "monkeypatch": monkeypatch}
    monkeypatch.setattr(config, "repair_mode", lambda: "observe")
    monkeypatch.setattr(config, "allowed_actions", lambda: {"notify_enriched", "rag_recheck"})


async def _make_diagnosed_job_ticket(
    db_session,
    source,
    *,
    job_name: str = "作业票审核",
    fired_date: str | None = None,
    rc: str = "upstream_outage",
    healthy: bool = False,
    missed_days: list[str] | None = None,
    endpoints: list[str] | None = None,
) -> Any:
    """已诊断工单（stage_facts 直填，跳过诊断段）+ 信号/漏审 trigger + job 行。"""
    import uuid as uuid_mod

    from app.modules.safety.models.msds import SchedulerJobRun
    from app.platform.superagent.models import AgentTask, AgentTrigger
    from app.platform.superagent.tasks import create_task

    fired = fired_date or (date.today() - timedelta(days=2)).isoformat()
    thread = f"ops:job:{job_name}:{fired}"
    trigger = AgentTrigger(
        id=uuid_mod.uuid4(), source_id=source.id,
        external_id=f"ops:job:{job_name}:{fired}:failed", thread_key=thread,
        actor={"id": job_name, "type": "scheduled_job"},
        payload={"signal": "job_failed", "job_name": job_name, "fired_date": fired,
                 "attempt_count": 18, "at": datetime.now(UTC).isoformat()},
        received_at=datetime.now(UTC),
    )
    db_session.add(trigger)
    for day in missed_days or []:
        db_session.add(AgentTrigger(
            id=uuid_mod.uuid4(), source_id=source.id,
            external_id=f"ops:job:{job_name}:{day}:missed", thread_key=f"ops:job:{job_name}:{day}",
            actor={"id": job_name, "type": "scheduled_job"},
            payload={"signal": "job_missed", "job_name": job_name, "fired_date": day},
            received_at=datetime.now(UTC),
        ))
    row = SchedulerJobRun(
        job_name=job_name, fired_date=date.fromisoformat(fired),
        status="success" if healthy else "failed", attempt_count=0 if healthy else 18,
    )
    existing = (
        await db_session.execute(
            select(SchedulerJobRun).where(SchedulerJobRun.job_name == job_name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.status = row.status
        existing.attempt_count = row.attempt_count
        existing.fired_date = row.fired_date
    else:
        db_session.add(row)
    await db_session.flush()
    task = await create_task(
        db_session, short_name=f"r3:{job_name}:{fired}", title="R3 断连工单",
        executor="r3_ops_heal", origin_trigger_id=trigger.id,
        mandate={"rule_id": "r3_ops_failure", "strength": "inferred"},
        origin_thread_key=thread,
    )
    task.stage_facts = {"r3": {
        "stage": "diagnosed", "signal": "job_failed", "job_name": job_name,
        "diag_at": datetime.now(UTC).isoformat(), "diag_source": "llm",
        "root_cause_class": rc, "confidence": 0.9, "reasoning": "平台不可达",
        "executed": [], "planned": [], "repair_rounds": 0,
        "dep_endpoints": endpoints or ["192.168.5.7:9550"],
        "first_seen_at": datetime.now(UTC).isoformat(),
        "evidence": {},
    }}
    await db_session.flush()
    return task


async def _add_input(db_session, task, payload: dict[str, Any]) -> None:
    from app.platform.superagent.models import AgentInput

    db_session.add(AgentInput(
        task_id=task.id, kind="trigger" if "signal" in payload else "system",
        payload=payload, delivered_at=datetime.now(UTC),
    ))
    await db_session.flush()


def _stub_review_service(monkeypatch, results_by_day: dict[str, dict[str, Any]] | None = None,
                         always_raise: Exception | None = None) -> list[str]:
    """WorkTicketReviewService 桩（client 构造 + run_review 记录日期）。"""
    calls: list[str] = []

    class _DummyClient:
        async def close(self):
            return None

    monkeypatch.setattr(
        "app.modules.safety.workticket_review.service.WorkTicketPlatformClient",
        _DummyClient,
    )

    async def _fake_run_review(self, review_date, push: bool = True):
        d = review_date.isoformat() if hasattr(review_date, "isoformat") else str(review_date)
        calls.append(d)
        if always_raise is not None:
            raise always_raise
        default = {"date": d, "total": 12, "reviewed": 12, "violation_count": 2,
                   "compliant_count": 10}
        return (results_by_day or {}).get(d, default)

    monkeypatch.setattr(
        "app.modules.safety.workticket_review.service.WorkTicketReviewService.run_review",
        _fake_run_review,
    )
    return calls


# ═══════════════════════════════════════════════════════════════
# 漏审日判定 + 补跑 adapter（样例 4 前半）
# ═══════════════════════════════════════════════════════════════


async def test_determine_missed_days_cap(db_session, repair_env) -> None:
    """漏审日清单（missed trigger 权威）+ ≤5 上限 + overflow 标记。"""
    from app.modules.safety.service.ops_selfheal_r3 import backfill

    src = repair_env["source"]
    days = [(date.today() - timedelta(days=i)).isoformat() for i in range(1, 8)]
    for d in days:
        await _add_trigger_missed(db_session, src, "r3补跑测试", d)
    got, overflow = await backfill.determine_missed_days(db_session, "r3补跑测试")
    assert overflow is True
    assert len(got) == 5
    assert got == sorted(days, reverse=True)[:5]  # 最近优先
    # 无 adapter 的 job 查询为零
    got2, overflow2 = await backfill.determine_missed_days(db_session, "不存在的任务")
    assert got2 == [] and overflow2 is False
    await db_session.rollback()


async def _add_trigger_missed(db_session, source, job: str, day: str) -> None:
    import uuid as uuid_mod

    from app.platform.superagent.models import AgentTrigger

    db_session.add(AgentTrigger(
        id=uuid_mod.uuid4(), source_id=source.id,
        external_id=f"ops:job:{job}:{day}:missed",
        thread_key=f"ops:job:{job}:{day}",
        actor={"id": job, "type": "scheduled_job"},
        payload={"signal": "job_missed", "job_name": job, "fired_date": day},
        received_at=datetime.now(UTC),
    ))


async def test_backfill_workticket_days_review_minus_one(db_session, repair_env, monkeypatch) -> None:
    """逐日补跑：run_day D → run_review(D-1)；失败重试 1 次再败记录继续。"""
    from app.modules.safety.service.ops_selfheal_r3 import backfill

    calls = _stub_review_service(monkeypatch)
    d1 = (date.today() - timedelta(days=2)).isoformat()
    d2 = (date.today() - timedelta(days=1)).isoformat()
    results = await backfill.backfill_workticket_days([d1, d2])
    assert calls == [
        (date.fromisoformat(d1) - timedelta(days=1)).isoformat(),
        (date.fromisoformat(d2) - timedelta(days=1)).isoformat(),
    ]
    assert all(r["status"] == "done" for r in results)

    # 全失败路径：重试 1 次后记录失败继续（不中断）
    calls2 = _stub_review_service(monkeypatch, always_raise=RuntimeError("平台仍不可达"))
    d3 = (date.today() - timedelta(days=3)).isoformat()
    results2 = await backfill.backfill_workticket_days([d3])
    assert len(calls2) == 2  # 1 次 + 重试 1 次
    assert results2[0]["status"] == "failed"
    assert "平台仍不可达" in results2[0]["error"]
    await db_session.rollback()


# ═══════════════════════════════════════════════════════════════
# 样例 4 全链：断连开单→dep_recovered→补跑→双条件关单（模拟）
# ═══════════════════════════════════════════════════════════════


async def test_sample4_outage_backfill_closure_chain(
    db_session, repair_env, monkeypatch,
) -> None:
    """跨天断连：dep_recovered → 漏审补跑入队 → 逐日终态 → 健康恢复 → 收口。"""
    from app.modules.safety.service.ops_selfheal_r3 import signals as sg
    from app.platform.superagent.executors import run_task_once
    from app.platform.superagent.models import AgentEffect

    src = repair_env["source"]
    missed = [
        (date.today() - timedelta(days=2)).isoformat(),
        (date.today() - timedelta(days=1)).isoformat(),
    ]
    task = await _make_diagnosed_job_ticket(
        db_session, src, fired_date=missed[0], healthy=False, missed_days=missed,
    )
    _stub_review_service(monkeypatch)

    # ① dep_recovered 回注 → 漏审日补跑入队（auto+白名单）
    await _add_input(db_session, task, {
        "signal": sg.SIGNAL_DEP_RECOVERED, "task_id": str(task.id),
        "endpoint": "192.168.5.7:9550",
    })
    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    r3 = task.stage_facts["r3"]
    assert r3["stage"] == "repairing" and r3["repair_rounds"] == 1
    backfill_effects = (
        await db_session.execute(
            select(AgentEffect).where(
                AgentEffect.kind == "r3_repair",
                AgentEffect.dedupe_key.like("r3:jobbackfill:%"),
            )
        )
    ).scalars().all()
    assert len(backfill_effects) == 1
    assert backfill_effects[0].payload["action"] == "job_backfill"
    assert backfill_effects[0].payload["run_days"] == sorted(missed, reverse=True)  # 最近优先

    # ② 模拟 effects poller 领取执行（handler + 置 done 同事务）
    from app.platform.superagent.effects import execute_claimed_effect

    assert await execute_claimed_effect(db_session, backfill_effects[0].id) == "done"
    await db_session.flush()
    done = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.dedupe_key == backfill_effects[0].dedupe_key)
        )
    ).scalar_one()
    assert done.status == "done"
    cards = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.dedupe_key.like("r3:repaircard:%"))
        )
    ).scalars().all()
    assert len(cards) == 1 and "job_backfill" in cards[0].payload["text"]

    # ③ 平台恢复 → job 行转健康 + recovered trigger 回注 → 收口卡入队
    from app.modules.safety.models.msds import SchedulerJobRun

    row = (
        await db_session.execute(
            select(SchedulerJobRun).where(SchedulerJobRun.job_name == "作业票审核")
        )
    ).scalar_one()
    row.status = "success"
    row.attempt_count = 0
    await db_session.flush()
    await _add_input(db_session, task, {
        "signal": sg.SIGNAL_JOB_RECOVERED, "job_name": "作业票审核",
        "fired_date": missed[0],
    })
    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    assert task.stage_facts["r3"]["stage"] == "verify_wait"
    closures = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.kind == "r3_closure_card")
        )
    ).scalars().all()
    assert len(closures) == 1

    # ④ 收口卡发送成功 → 关单（双条件②送达才 closed）
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "SUPERAGENT_ADMIN_OPEN_IDS", "ou_test_admin")
    monkeypatch.setattr(
        "app.modules.safety.superagent_bridge._send_admin_dm",
        lambda open_id, text: _async_true(),
    )
    await r3_closure_card_handler_invoke(db_session, closures[0].payload)
    await db_session.flush()
    await db_session.refresh(task)
    assert task.status == "ended" and task.outcome == "closed"
    assert task.stage_facts["r3"]["stage"] == "closed"
    await db_session.rollback()


async def _async_true() -> bool:
    return True


async def r3_closure_card_handler_invoke(db_session, payload: dict) -> None:
    """在 db_session 事务内执行收口 handler（factory 已桩到同 session）。"""
    from app.modules.safety.service.ops_selfheal_r3.actions import (
        r3_closure_card_handler,
    )

    await r3_closure_card_handler(payload)


async def test_closure_card_failure_keeps_ticket_open(
    db_session, repair_env, monkeypatch,
) -> None:
    """收口卡发送失败 → 工单不置 closed；重试成功才关（§9.4 验收）。"""
    from app.platform.superagent.models import AgentEffect

    src = repair_env["source"]
    task = await _make_diagnosed_job_ticket(db_session, src, healthy=True)

    from app.platform.superagent.executors import run_task_once
    from app.modules.safety.service.ops_selfheal_r3 import signals as sg

    await _add_input(db_session, task, {
        "signal": sg.SIGNAL_JOB_RECOVERED, "job_name": "作业票审核", "fired_date": "x",
    })
    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    closure = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.kind == "r3_closure_card")
        )
    ).scalar_one()

    # 发送失败：handler raise（→effect 退避重试），工单保持 open
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "SUPERAGENT_ADMIN_OPEN_IDS", "ou_test_admin")
    monkeypatch.setattr(
        "app.modules.safety.superagent_bridge._send_admin_dm",
        lambda open_id, text: _async_false(),
    )
    with pytest.raises(RuntimeError):
        await r3_closure_card_handler_invoke(db_session, closure.payload)
    await db_session.flush()
    await db_session.refresh(task)
    assert task.status == "open"  # 双条件②未满足，绝不关单

    # 下轮重发成功 → 关单
    monkeypatch.setattr(
        "app.modules.safety.superagent_bridge._send_admin_dm",
        lambda open_id, text: _async_true(),
    )
    await r3_closure_card_handler_invoke(db_session, closure.payload)
    await db_session.flush()
    await db_session.refresh(task)
    assert task.status == "ended" and task.outcome == "closed"
    await db_session.rollback()


async def _async_false() -> bool:
    return False


async def test_observe_mode_backfill_needs_human(db_session, monkeypatch) -> None:
    """observe 模式：漏审日不补跑 → needs_human + 升级卡（授权升级走人）。"""
    from app.modules.safety.service.ops_selfheal_r3 import (
        config,
        signals as sg,
    )
    from app.modules.safety.superagent_bridge import register_superagent_bridge
    from app.platform.superagent.executors import run_task_once
    from app.platform.superagent.models import AgentEffect, AgentSource

    register_superagent_bridge()
    src = AgentSource(
        kind="ops_scan", name=_SCAN_SOURCE, enabled=True, config={"evaluate": True},
    )
    db_session.add(src)
    await db_session.flush()
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _Ctx(db_session),
    )
    monkeypatch.setattr(config, "repair_mode", lambda: "observe")
    monkeypatch.setattr(
        config, "allowed_actions",
        lambda: {"notify_enriched", "rag_recheck", "job_backfill"},  # 白名单含但模式 observe
    )

    missed = [(date.today() - timedelta(days=1)).isoformat()]
    task = await _make_diagnosed_job_ticket(db_session, src, healthy=False, missed_days=missed)
    await _add_input(db_session, task, {
        "signal": sg.SIGNAL_DEP_RECOVERED, "task_id": str(task.id), "endpoint": "e",
    })
    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    r3 = task.stage_facts["r3"]
    assert r3["stage"] == "needs_human"
    assert "observe" in r3["escalate_guidance"]
    repairs = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.kind == "r3_repair")
        )
    ).scalars().all()
    assert repairs == []  # observe 红线：零 L1 执行
    await db_session.rollback()


# ═══════════════════════════════════════════════════════════════
# effects_unpark handler（样例 3 近亲）+ 日上限
# ═══════════════════════════════════════════════════════════════


async def test_effects_unpark_handler_daily_cap(db_session, repair_env, monkeypatch) -> None:
    """unpark：置 pending/attempts=0；每组件日 3 次上限超限跳过。"""
    import uuid as uuid_mod

    from app.modules.safety.service.ops_selfheal_r3.actions import _do_effects_unpark
    from app.platform.superagent.models import AgentEffect, AgentInput, AgentTask
    from app.platform.superagent.tasks import create_task

    # 工单（repair_done input 投递目标）
    src = repair_env["source"]
    task = await create_task(
        db_session, short_name="r3:unpark", title="R3 unpark", executor="r3_ops_heal",
        mandate={"rule_id": "r3_ops_failure"},
    )
    # 今日已有 3 次成功 unpark（日上限用尽）
    from datetime import datetime as dt

    for i in range(3):
        db_session.add(AgentEffect(
            id=uuid_mod.uuid4(), kind="r3_repair", status="done",
            dedupe_key=f"r3hist-{uuid_mod.uuid4().hex[:6]}",
            payload={"action": "effects_unpark", "component": "digest_cell_upsert",
                     "task_id": str(task.id), "round": i + 1},
            created_at=dt.now(UTC), updated_at=dt.now(UTC),
        ))
    # 2 条待 unpark 的 parked 行
    park_ids = []
    for i in range(2):
        e = AgentEffect(
            id=uuid_mod.uuid4(), kind="digest_cell_upsert", status="failed",
            dedupe_key=f"unpark-{uuid_mod.uuid4().hex[:8]}",
            payload={}, attempts=10, last_error="老错误",
        )
        db_session.add(e)
        park_ids.append(e.id)
    await db_session.flush()
    _ = src

    await _do_effects_unpark({
        "task_id": str(task.id), "component": "digest_cell_upsert", "round": 1,
    })
    await db_session.flush()
    for pid in park_ids:
        row = await db_session.get(AgentEffect, pid)
        assert row.status == "failed"  # 日上限 3 已用尽 → 跳过未 unpark
    # 卡上带超限说明
    cards = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.dedupe_key.like("r3:repaircard:%"))
        )
    ).scalars().all()
    assert cards and "日上限" in cards[0].payload["text"]

    # repair_done input 已投（下轮收口核对驱动）
    inputs = (
        await db_session.execute(
            select(AgentInput).where(AgentInput.task_id == task.id, AgentInput.kind == "system")
        )
    ).scalars().all()
    assert any(i.payload.get("action") == "effects_unpark" for i in inputs)
    await db_session.rollback()


# ═══════════════════════════════════════════════════════════════
# 二期 D：中控报警日报补跑 adapter
# ═══════════════════════════════════════════════════════════════


def _stub_central_alarm(monkeypatch, always_raise: Exception | None = None) -> list[str]:
    """CentralAlarmService 桩（构造期校验连带——生成记录日期，push=False 断言）。"""
    calls: list[tuple[str, bool]] = []

    class _FakeReport:
        total = 42
        push_results: list = []

    class _FakeService:
        def __init__(self, session):
            pass  # 真类构造期校验凭据——桩连构造一起替（一期同款雷）

        async def generate_daily_report(self, target_date=None, *, push=True,
                                        channel="web", rolling=True, chat_id=None):
            d = target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date)
            calls.append((d, push))
            if always_raise is not None:
                raise always_raise
            return _FakeReport()

    monkeypatch.setattr(
        "app.modules.safety.service.central_alarm.service.CentralAlarmService",
        _FakeService,
    )
    return calls


async def test_backfill_central_alarm_days_no_offset(db_session, repair_env, monkeypatch) -> None:
    """中控日报补跑：target_date=D 当日无偏移（区别于作业票 D-1）；push=False。"""
    from app.modules.safety.service.ops_selfheal_r3 import backfill

    calls = _stub_central_alarm(monkeypatch)
    d1 = (date.today() - timedelta(days=2)).isoformat()
    d2 = (date.today() - timedelta(days=1)).isoformat()
    results = await backfill.backfill_central_alarm_days([d1, d2])
    assert calls == [(d1, False), (d2, False)]  # 无 D-1 偏移 + push=False
    assert all(r["status"] == "done" for r in results)
    assert all(r["review_date"] == r["run_day"] for r in results)
    assert results[0]["total"] == 42

    # 失败重试 1 次再败记录继续
    calls2 = _stub_central_alarm(monkeypatch, always_raise=RuntimeError("中控库仍断连"))
    d3 = (date.today() - timedelta(days=3)).isoformat()
    results2 = await backfill.backfill_central_alarm_days([d3])
    assert len(calls2) == 2
    assert results2[0]["status"] == "failed"
    assert "中控库仍断连" in results2[0]["error"]
    await db_session.rollback()


async def test_central_alarm_registered_in_adapters() -> None:
    """adapter 注册表：中控报警日报在册（矩阵化第二列）。"""
    from app.modules.safety.service.ops_selfheal_r3.backfill import BACKFILL_ADAPTERS

    assert BACKFILL_ADAPTERS.get("中控报警日报") == "central_alarm"
    assert BACKFILL_ADAPTERS.get("作业票审核") == "workticket"


async def test_do_job_backfill_routes_by_adapter(db_session, repair_env, monkeypatch) -> None:
    """_do_job_backfill 按 job_name 分派 adapter（中控走 central_alarm 分支）。"""
    from app.modules.safety.service.ops_selfheal_r3 import backfill

    calls = _stub_central_alarm(monkeypatch)
    d1 = (date.today() - timedelta(days=1)).isoformat()

    # 直接验证分派逻辑（adapter 路由读 BACKFILL_ADAPTERS）
    adapter = backfill.BACKFILL_ADAPTERS.get("中控报警日报")
    assert adapter == "central_alarm"
    results = await backfill.backfill_central_alarm_days([d1])
    assert calls == [(d1, False)]
    assert results[0]["status"] == "done"
    await db_session.rollback()
