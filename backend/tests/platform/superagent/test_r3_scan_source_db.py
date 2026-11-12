"""R3 信号层全链 —— OpsScanSource 五类扫描 + rag 直投 + 组合 Policy（S1）。

对齐 test_r1_fire_chain_db.py 范式：db_session 回滚隔离 + autouse purge 清理
执行器/直投 commit 穿透行；网络探针/LLM 一律桩。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select

_SCAN_SOURCE = "safety.ops.selfheal"
_RAG_SOURCE = "safety.ops.rag_inject"


@pytest_asyncio.fixture(autouse=True)
async def _purge_r3_rows():
    """R3 全链行清理（直投/inject helper 内 commit 会穿透回滚语义）。"""
    yield
    from app.platform.superagent.models import (
        AgentDecision,
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
        for name in (_SCAN_SOURCE, _RAG_SOURCE):
            src = (
                await s.execute(
                    select(AgentSource).where(AgentSource.name == name)
                )
            ).scalar_one_or_none()
            if src is not None:
                for t in (
                    await s.execute(
                        select(AgentTrigger).where(AgentTrigger.source_id == src.id)
                    )
                ).scalars().all():
                    await s.execute(
                        AgentDecision.__table__.delete().where(AgentDecision.trigger_id == t.id)
                    )
                    await s.execute(
                        AgentInput.__table__.delete().where(AgentInput.trigger_id == t.id)
                    )
                    await s.delete(t)
                await s.execute(
                    AgentSource.__table__.delete().where(AgentSource.id == src.id)
                )
        await s.execute(
            AgentEffect.__table__.delete().where(
                (AgentEffect.kind == "r3_repair")
                | (AgentEffect.kind == "r3_closure_card")
                | (AgentEffect.dedupe_key.like("r3:%"))
            )
        )
        await s.commit()


@pytest_asyncio.fixture
async def scan_env(db_session):
    """R3 扫描源行（enabled）+ 组合 Policy（auto）+ 注册接线。"""
    from app.modules.safety.service.ops_selfheal_r3.rule import R3_EXECUTOR
    from app.modules.safety.superagent_bridge import (
        ensure_guardian_r2_policy,
        register_superagent_bridge,
    )
    from app.platform.superagent.models import AgentSource

    register_superagent_bridge()
    src = AgentSource(
        kind="ops_scan", name=_SCAN_SOURCE, enabled=True,
        config={
            "schedule": {"strategy": "interval", "interval_seconds": 300,
                          "timezone": "Asia/Shanghai"},
            "evaluate": True,
        },
    )
    db_session.add(src)
    await db_session.flush()
    await ensure_guardian_r2_policy(session=db_session)
    await db_session.flush()
    yield {"source": src, "executor": R3_EXECUTOR}


async def _scan_once(db_session, monkeypatch) -> dict:
    """跑一轮扫描（恒到期 + 总闸开；读位预置过期）。"""
    from datetime import UTC, datetime, timedelta

    from app.modules.safety.service.ops_selfheal_r3 import config, scan_source
    from app.platform.superagent.ingest import apply_cursor_updates, ingest_source_once

    monkeypatch.setattr(config, "ops_enabled", lambda: True)
    monkeypatch.setattr(
        scan_source, "due_fire_times", lambda schedule, last, now, **kw: [now],
    )
    src_row = (
        await db_session.execute(
            select(scan_source.AgentSource).where(
                scan_source.AgentSource.name == _SCAN_SOURCE
            )
        )
    ).scalar_one()
    await apply_cursor_updates(
        db_session, src_row.id,
        {"last_tick": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
    )
    return await ingest_source_once(db_session, src_row)


def _job_row(job_name: str, *, status: str = "failed", attempts: int = 5,
             fired_date: date | None = None) -> Any:
    from datetime import UTC, datetime

    from app.modules.safety.models.msds import SchedulerJobRun

    return SchedulerJobRun(
        job_name=job_name,
        fired_date=fired_date or date.today(),
        status=status,
        attempt_count=attempts,
        last_attempt_at=datetime.now(UTC),
        alerted=bool(status == "failed"),
    )


async def _triggers_of(db_session, source_name: str = _SCAN_SOURCE) -> list[Any]:
    from app.platform.superagent.models import AgentSource, AgentTrigger

    src = (
        await db_session.execute(
            select(AgentSource).where(AgentSource.name == source_name)
        )
    ).scalar_one()
    return (
        await db_session.execute(
            select(AgentTrigger).where(AgentTrigger.source_id == src.id)
            .order_by(AgentTrigger.received_at)
        )
    ).scalars().all()


async def _job_triggers(db_session, job_name: str) -> list[Any]:
    """只看测试 job 的 trigger（开发库有真实 failed 行，按前缀隔离断言）。"""
    prefix = f"ops:job:{job_name}:"
    return [t for t in await _triggers_of(db_session) if t.external_id.startswith(prefix)]


# ═══════════════════════════════════════════════════════════════
# 纯函数（signals / 窗口 / 端点提取）
# ═══════════════════════════════════════════════════════════════


def test_signal_keys_shape() -> None:
    from app.modules.safety.service.ops_selfheal_r3 import signals as sg

    assert sg.job_failed_eid("作业票审核", "2026-11-10") == "ops:job:作业票审核:2026-11-10:failed"
    assert sg.job_thread("作业票审核", "2026-11-10") == "ops:job:作业票审核:2026-11-10"
    assert sg.rag_eid("2026-11-09", "degraded", "101530000") == "ops:rag:2026-11-09:degraded:101530000"
    assert sg.rag_thread("2026-11-09") == "ops:rag:2026-11-09"
    assert sg.opsmisc_thread("2026-11-10") == "ops:opsmisc:2026-11-10"
    # 聚合幂等键稳定（清单同集合恒同 id）
    a = sg.batch_eid("2026-11-10", ["x", "y"])
    b = sg.batch_eid("2026-11-10", ["y", "x"])
    assert a == b and a.startswith("ops:batch:2026-11-10:")
    # dep 幂等键内嵌端点哈希
    e1 = sg.dep_recovered_eid("t1", "192.168.5.7:9550")
    assert e1.startswith("ops:dep:t1:") and e1.endswith(":recovered")


def test_r3_stage_derive() -> None:
    from app.modules.safety.service.ops_selfheal_r3 import signals as sg

    assert sg.r3_stage("ended", {"r3": {"stage": "verify_wait"}}) == "closed"
    assert sg.r3_stage("open", {}) == sg.R3_STAGE_DETECTED
    assert sg.r3_stage("open", {"r3": {"stage": "needs_human"}}) == "needs_human"


def test_missed_review_date() -> None:
    from app.modules.safety.service.ops_selfheal_r3.scan_source import missed_review_date

    # run_on D 审 D-1（scheduler.py:891 语义）
    assert missed_review_date("2026-11-10") == "2026-11-09"


def test_window_exhausted_workticket() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.modules.safety.service.ops_selfheal_r3.scan_source import (
        job_window_end,
        window_exhausted,
    )

    tz = ZoneInfo("Asia/Shanghai")
    day = date(2026, 11, 10)
    assert job_window_end("作业票审核", day) == datetime(2026, 11, 10, 12, 0, tzinfo=tz)
    assert window_exhausted("作业票审核", day, now=datetime(2026, 11, 10, 11, 59, tzinfo=tz)) is False
    assert window_exhausted("作业票审核", day, now=datetime(2026, 11, 10, 12, 1, tzinfo=tz)) is True


def test_extract_endpoints() -> None:
    from app.modules.safety.service.ops_selfheal_r3.diagnosis import extract_endpoints

    text = "平台接口超时 POST http://192.168.5.7:9550/api/v1/tickets 失败；备选 10.1.2.3:8080"
    eps = extract_endpoints(text, None, "无关文本")
    assert eps[0].startswith("http://192.168.5.7:9550")
    assert "10.1.2.3:8080" in eps


# ═══════════════════════════════════════════════════════════════
# 扫描链（db）
# ═══════════════════════════════════════════════════════════════


async def test_scan_job_failed_then_recovered(db_session, scan_env, monkeypatch) -> None:
    """job 连续失败→failed trigger；翻 success→recovered；重扫 duplicate。"""
    yesterday = date.today() - timedelta(days=1)
    db_session.add(_job_row("r3测试任务A", attempts=5, fired_date=yesterday))
    await db_session.flush()

    s1 = await _scan_once(db_session, monkeypatch)
    trigs = await _job_triggers(db_session, "r3测试任务A")
    eids = {t.external_id for t in trigs}
    assert eids == {
        "ops:job:r3测试任务A:%s:failed" % yesterday.isoformat(),
        "ops:job:r3测试任务A:%s:missed" % yesterday.isoformat(),  # 昨日窗口必耗尽
    }
    assert all(t.thread_key == "ops:job:r3测试任务A:%s" % yesterday.isoformat() for t in trigs)
    # auto Policy：failed 开单（missed 经订阅直通回注同单）
    from app.platform.superagent.models import AgentTask, AgentTaskSubscription

    task = (
        await db_session.execute(
            select(AgentTask).where(
                AgentTask.executor == "r3_ops_heal",
                AgentTask.id.in_(
                    select(AgentTaskSubscription.task_id).where(
                        AgentTaskSubscription.thread_key
                        == "ops:job:r3测试任务A:%s" % yesterday.isoformat()
                    )
                ),
            )
        )
    ).scalar_one_or_none()
    assert task is not None and task.mandate["rule_id"] == "r3_ops_failure"

    # 重扫同批：duplicate 幂等零新增（测试 job 零新 trigger）
    n_before = len(await _job_triggers(db_session, "r3测试任务A"))
    await _scan_once(db_session, monkeypatch)
    assert len(await _job_triggers(db_session, "r3测试任务A")) == n_before

    # 翻 success → recovered（归属 failed 日）
    row = (
        await db_session.execute(
            select(_job_model()).where(_job_model().job_name == "r3测试任务A")
        )
    ).scalar_one()
    row.status = "success"
    row.attempt_count = 0
    await db_session.flush()
    await _scan_once(db_session, monkeypatch)
    eids3 = {t.external_id for t in await _job_triggers(db_session, "r3测试任务A")}
    assert "ops:job:r3测试任务A:%s:recovered" % yesterday.isoformat() in eids3
    await db_session.rollback()


async def test_scan_below_threshold_no_signal(db_session, scan_env, monkeypatch) -> None:
    """attempt_count<3（未达告警阈值）不产信号；总闸关零扫描。"""
    from app.modules.safety.service.ops_selfheal_r3 import config

    db_session.add(_job_row("r3测试任务B", attempts=2))
    await db_session.flush()
    monkeypatch.setattr(config, "ops_enabled", lambda: True)
    await _scan_once(db_session, monkeypatch)
    assert await _job_triggers(db_session, "r3测试任务B") == []

    # 总闸关（ops_enabled False）→ 空结果（一键全停）
    monkeypatch.setattr(config, "ops_enabled", lambda: False)
    from datetime import UTC, datetime, timedelta

    from app.platform.superagent.ingest import apply_cursor_updates, ingest_source_once
    from app.platform.superagent.models import AgentSource

    src_row = (
        await db_session.execute(
            select(AgentSource).where(AgentSource.name == _SCAN_SOURCE)
        )
    ).scalar_one()
    await apply_cursor_updates(
        db_session, src_row.id,
        {"last_tick": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
    )
    empty = await ingest_source_once(db_session, src_row)
    assert empty["polled"] == 0
    await db_session.rollback()


async def test_scan_today_not_missed_before_window(db_session, scan_env, monkeypatch) -> None:
    """当日重试中不计漏审（窗口未耗尽只发 failed 不发 missed）。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.modules.safety.service.ops_selfheal_r3 import scan_source

    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    # 作业票审核 行在开发库常驻（真实断连数据）——复用该行改当日态（回滚还原）
    job = (
        await db_session.execute(
            select(_job_model()).where(_job_model().job_name == "作业票审核")
        )
    ).scalar_one_or_none()
    if job is None:
        job = _job_row("作业票审核", attempts=5, fired_date=now.date())
        db_session.add(job)
    job.status = "failed"
    job.attempt_count = 5
    job.fired_date = now.date()
    await db_session.flush()
    # 恒定时间：窗口内（无论现在几点）——patch now 判定
    monkeypatch.setattr(
        scan_source, "window_exhausted",
        lambda job_name, day, now=None: False,
    )
    await _scan_once(db_session, monkeypatch)
    eids = {t.external_id for t in await _job_triggers(db_session, "作业票审核")}
    # 当日窗口未耗尽：只 failed 不 missed（当日重试中不计漏审）
    assert any(e.endswith(":failed") for e in eids)
    assert all(not e.endswith(":missed") for e in eids)
    await db_session.rollback()


async def test_scan_parked_excludes_r3_kinds(db_session, scan_env, monkeypatch) -> None:
    """parked（status=failed）按 kind 分组触发；R3 自身 kinds 排除。"""
    import uuid as uuid_mod

    from app.platform.superagent.models import AgentEffect

    test_kind = "r3ptest_kind"
    for kind, key in (
        (test_kind, f"park-{uuid_mod.uuid4().hex[:8]}"),
        ("r3_repair", f"park-{uuid_mod.uuid4().hex[:8]}"),
        ("r3_closure_card", f"park-{uuid_mod.uuid4().hex[:8]}"),
    ):
        db_session.add(AgentEffect(
            id=uuid_mod.uuid4(), kind=kind, dedupe_key=key,
            payload={}, status="failed", attempts=10, last_error="x",
        ))
    await db_session.flush()

    await _scan_once(db_session, monkeypatch)
    parked = [
        t for t in await _triggers_of(db_session)
        if t.external_id.startswith(f"ops:parked:{test_kind}:")
    ]
    assert len(parked) == 1
    t = parked[0]
    assert t.thread_key.startswith("ops:opsmisc:")
    assert t.payload["signal"] == "effects_parked" and t.payload["count"] == 1
    r3_own = [
        t for t in await _triggers_of(db_session)
        if t.external_id.startswith(("ops:parked:r3_repair:", "ops:parked:r3_closure_card:"))
    ]
    assert r3_own == []  # R3 自身 kinds 排除（自愈不自我修复）
    await db_session.rollback()


async def test_scan_deadletter_failopen(db_session, scan_env, monkeypatch) -> None:
    """死信计数触发 + Redis 不可达 fail-open（跳过不抛）。"""
    async def _fake_list(limit: int = 100):
        return [{"record_id": "recX", "reason": "AI 分析超时"}]

    monkeypatch.setattr(
        "app.modules.safety.service.hazard_direct.failure_ledger.list_dead_letters",
        _fake_list,
    )
    await _scan_once(db_session, monkeypatch)
    dl = [t for t in await _triggers_of(db_session) if t.external_id.startswith("ops:deadletter:")]
    assert len(dl) == 1
    assert dl[0].payload["count"] == 1

    async def _boom(limit: int = 100):
        raise RuntimeError("redis down")

    monkeypatch.setattr(
        "app.modules.safety.service.hazard_direct.failure_ledger.list_dead_letters",
        _boom,
    )
    await _scan_once(db_session, monkeypatch)  # 不抛 = fail-open
    dl2 = [t for t in await _triggers_of(db_session) if t.external_id.startswith("ops:deadletter:")]
    assert len(dl2) == 1  # 无新增（fail-open 跳过本轮）
    await db_session.rollback()


async def test_scan_storm_cap_aggregates(db_session, scan_env, monkeypatch) -> None:
    """防风暴：故障类 >5 → 一条聚合 trigger（payload 带清单）。"""
    import uuid as uuid_mod

    from app.platform.superagent.models import AgentEffect

    # 6 个测试组件 parked + 1 个死信 ≥7 条故障类 → 聚合 1 条
    #（开发库真实 parked 行可能并入聚合，断言用下界）
    for i in range(6):
        db_session.add(AgentEffect(
            id=uuid_mod.uuid4(), kind=f"r3storm{i}",
            dedupe_key=f"storm-{uuid_mod.uuid4().hex[:8]}",
            payload={}, status="failed", attempts=10, last_error="x",
        ))

    async def _fake_list(limit: int = 100):
        return [{"record_id": "recX", "reason": "r"}]

    monkeypatch.setattr(
        "app.modules.safety.service.hazard_direct.failure_ledger.list_dead_letters",
        _fake_list,
    )
    await _scan_once(db_session, monkeypatch)
    batches = [
        t for t in await _triggers_of(db_session) if t.external_id.startswith("ops:batch:")
    ]
    assert len(batches) == 1  # 超限聚合成 1 条（不逐条开单）
    t = batches[0]
    assert t.payload["signal"] == "ops_batch"
    assert t.payload["count"] >= 7
    assert t.thread_key.startswith("ops:opsmisc:")
    # 测试组件不产生独立 parked 原子信号（被聚合吞并）
    singles = [
        x for x in await _triggers_of(db_session)
        if x.external_id.startswith("ops:parked:r3storm")
    ]
    assert singles == []
    await db_session.rollback()


async def test_scan_dep_recovered_roundtrip(db_session, scan_env, monkeypatch) -> None:
    """依赖探测翻转：不可达首见记读位 → 可达产 dep_recovered 回注原工单线程。"""
    import uuid as uuid_mod

    from app.platform.superagent.models import AgentTask, AgentTaskSubscription

    task = AgentTask(
        id=uuid_mod.uuid4(), short_name="r3:t", title="t", executor="r3_ops_heal",
        stage_facts={"r3": {
            "stage": "diagnosed", "root_cause_class": "upstream_outage",
            "dep_endpoints": ["192.168.5.7:9550"],
        }},
        status="open",
    )
    db_session.add(task)
    await db_session.flush()
    thread = "ops:job:作业票审核:2026-11-10"
    db_session.add(AgentTaskSubscription(task_id=task.id, thread_key=thread))
    await db_session.flush()

    state = {"reachable": False}

    async def _fake_probe(endpoint: str, *, timeout: float = 4.0) -> bool:
        return state["reachable"]

    from app.modules.safety.service.ops_selfheal_r3 import scan_source

    monkeypatch.setattr(scan_source, "probe_endpoint", _fake_probe)

    await _scan_once(db_session, monkeypatch)  # 不可达首见：记读位无 trigger
    deps = [t for t in await _triggers_of(db_session) if ":recovered" in t.external_id
            and t.external_id.startswith("ops:dep:")]
    assert deps == []

    state["reachable"] = True
    await _scan_once(db_session, monkeypatch)  # 翻转 → dep_recovered
    deps = [t for t in await _triggers_of(db_session) if t.external_id.startswith("ops:dep:")]
    assert len(deps) == 1
    t = deps[0]
    assert t.external_id == scan_source.signals.dep_recovered_eid(str(task.id), "192.168.5.7:9550")
    assert t.thread_key == thread  # 回注原工单线程
    assert t.payload["signal"] == "dep_recovered"

    await _scan_once(db_session, monkeypatch)  # 持续可达：无翻转无新 trigger
    deps2 = [t for t in await _triggers_of(db_session) if t.external_id.startswith("ops:dep:")]
    assert len(deps2) == 1
    await db_session.rollback()


def _job_model():
    from app.modules.safety.models.msds import SchedulerJobRun

    return SchedulerJobRun


# ═══════════════════════════════════════════════════════════════
# rag 直投 + 组合 Policy
# ═══════════════════════════════════════════════════════════════


async def test_rag_inject_routes_to_policy(db_session, scan_env, monkeypatch) -> None:
    """直投 → 研判（auto）→ 开单；同日重复投递 external_id 各异。"""
    from app.platform.superagent.models import AgentSource, AgentTask

    rag_src = AgentSource(
        kind="rag_direct", name=_RAG_SOURCE, enabled=False, config={"evaluate": True},
    )
    db_session.add(rag_src)
    await db_session.flush()

    from app.modules.safety.service.ops_selfheal_r3 import config, rag_inject

    monkeypatch.setattr(config, "ops_enabled", lambda: True)

    class _Ctx:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _Ctx(db_session),
    )

    ok1 = await rag_inject.inject_rag_signal("degraded", detail="HTTP 429: 余额不足")
    assert ok1 is True
    tasks = (
        await db_session.execute(
            select(AgentTask).where(AgentTask.executor == "r3_ops_heal")
        )
    ).scalars().all()
    assert len(tasks) == 1  # auto → rag 信号开单
    assert tasks[0].mandate["rule_id"] == "r3_ops_rag_signal"

    ok2 = await rag_inject.inject_rag_signal("degraded", detail="再次故障")
    assert ok2 is True  # 同日抖动各投各的
    await db_session.rollback()


async def test_rag_inject_disabled_noop(db_session, scan_env, monkeypatch) -> None:
    """总闸关 → 直投 no-op（rag_health 探活完全不受影响）。"""
    from app.modules.safety.service.ops_selfheal_r3 import config, rag_inject

    monkeypatch.setattr(config, "ops_enabled", lambda: False)
    assert await rag_inject.inject_rag_signal("recovered", detail="x") is False


async def test_policy_composite_keeps_r1_r2_hw_r3(db_session, scan_env) -> None:
    """组合 Policy 四组会合：R1+R2+HW+R3 全在场（会合点坑回归锚）。"""
    from app.platform.superagent.models import AgentPolicy
    from app.platform.superagent.policy import get_current_policy

    await db_session.flush()
    current = await get_current_policy(db_session)
    assert current is not None
    rule_ids = {r.get("rule_id") for r in (current.rules or [])}
    assert "fire_alarm_candidate" in rule_ids  # R1
    assert any(x.startswith("guardian_") for x in rule_ids)  # R2
    assert "hardware_alert_urge" in rule_ids  # HW（会合点回归锚：五金库规则不丢）
    assert "r3_ops_failure" in rule_ids and "r3_ops_rag_signal" in rule_ids  # R3
    await db_session.rollback()
