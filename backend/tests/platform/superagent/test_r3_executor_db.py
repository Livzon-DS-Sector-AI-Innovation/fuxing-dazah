"""R3 诊断执行器 —— 三段编排 + observe 红线 + 升级 + LLM 契约（S2）。

LLM 一律桩（llm_diagnose / 原始探针），DM 只断言入队不真发。
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

_SCAN_SOURCE = "safety.ops.selfheal"


@pytest_asyncio.fixture(autouse=True)
async def _purge_r3_rows():
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
        for name in (_SCAN_SOURCE, "safety.ops.rag_inject"):
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
                AgentEffect.dedupe_key.like("r3:%")
                | AgentEffect.dedupe_key.like("r3hist-%")
                | AgentEffect.kind.in_(("r3_repair", "r3_closure_card"))
            )
        )
        await s.commit()


class _Ctx:
    """执行器自开 session → 复用 db_session（R1 范式）。"""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest_asyncio.fixture
async def exec_env(db_session, monkeypatch):
    """源行 + 桩（探针/LLM/factory）+ 接线；默认 observe。"""
    from app.modules.safety.service.ops_selfheal_r3 import config, diagnosis
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

    async def _rag_ok():
        return {"embedding_ok": True, "embedding_detail": "ok",
                "ragplus": {"ok": True, "detail": "ok"}}

    async def _feishu_ok():
        return {"ok": True}

    monkeypatch.setattr(diagnosis, "_probe_rag_raw", _rag_ok)
    monkeypatch.setattr(diagnosis, "_probe_feishu", _feishu_ok)
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _Ctx(db_session),
    )
    yield {"source": src, "monkeypatch": monkeypatch}
    # 恢复模式闸（防泄漏到其他用例）
    monkeypatch.setattr(config, "repair_mode", lambda: "observe")
    monkeypatch.setattr(
        config, "allowed_actions",
        lambda: {"notify_enriched", "rag_recheck"},
    )


async def _make_job_ticket(
    db_session, source, *, job_name: str = "r3执行测试任务", fired_date: str = "2026-11-10",
    error_text: str = "httpx.ConnectError: 无法连接 http://192.168.5.7:9550/api/v1/tickets",
    signal: str = "job_failed",
):
    """建信号 Trigger + 工单（模拟 Policy auto 开单形态）+ 订阅。"""
    import uuid as uuid_mod
    from datetime import UTC, datetime

    from app.platform.superagent.models import AgentTrigger
    from app.platform.superagent.tasks import create_task

    thread = f"ops:job:{job_name}:{fired_date}"
    trigger = AgentTrigger(
        id=uuid_mod.uuid4(),
        source_id=source.id,
        external_id=f"ops:job:{job_name}:{fired_date}:failed",
        thread_key=thread,
        actor={"id": job_name, "type": "scheduled_job"},
        payload={
            "signal": signal, "job_name": job_name, "fired_date": fired_date,
            "attempt_count": 5,
            "at": datetime.now(UTC).isoformat(),
            "channel": {"kind": "ops_job", "job_name": job_name},
        },
        received_at=datetime.now(UTC),
    )
    db_session.add(trigger)
    await db_session.flush()

    from app.modules.safety.models.scheduler_run_log import SchedulerTaskRunLog

    db_session.add(SchedulerTaskRunLog(
        job_name=job_name, started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
        status="failed", error=error_text,
    ))
    task = await create_task(
        db_session,
        short_name=f"r3:{job_name}:{fired_date}",
        title=f"R3：{job_name} {fired_date} 失败",
        executor="r3_ops_heal",
        origin_trigger_id=trigger.id,
        mandate={"policy_version": "test", "strength": "inferred",
                 "rule_id": "r3_ops_failure"},
        origin_thread_key=thread,
    )
    await db_session.flush()
    return task, trigger


def _llm_stub(monkeypatch, result: dict[str, Any] | None) -> list[dict[str, Any]]:
    """LLM 归因桩（记录调用；result=None 模拟降级）。"""
    from app.modules.safety.service.ops_selfheal_r3 import diagnosis

    calls: list[dict[str, Any]] = []

    async def _fake(signal: str, evidence: dict[str, Any]):
        calls.append({"signal": signal, "evidence": evidence})
        return result

    monkeypatch.setattr(diagnosis, "llm_diagnose", _fake)
    return calls


# ═══════════════════════════════════════════════════════════════
# LLM 契约与规则降级（纯函数）
# ═══════════════════════════════════════════════════════════════


def test_validate_llm_output_contract() -> None:
    from app.modules.safety.service.ops_selfheal_r3.diagnosis import (
        validate_llm_output,
    )

    ok = validate_llm_output({
        "root_cause_class": "upstream_outage", "confidence": 0.9,
        "reasoning": "连接类错误且提取到端点",
        "prescriptions": [
            {"action": "rag_recheck", "args": {}, "urgency": "now"},
            {"action": "rm -rf /", "args": {}, "urgency": "now"},  # 枚举外→丢弃
        ],
    })
    assert ok is not None and ok["root_cause_class"] == "upstream_outage"
    assert [p["action"] for p in ok["prescriptions"]] == ["rag_recheck"]

    assert validate_llm_output({"root_cause_class": "炸了", "confidence": 1}) is None
    assert validate_llm_output({"root_cause_class": "network", "confidence": "高"}) is None
    assert validate_llm_output({"root_cause_class": "network", "confidence": 2.0}) is not None  # 钳制


def test_rule_based_diagnosis_keywords() -> None:
    from app.modules.safety.service.ops_selfheal_r3 import signals as sg
    from app.modules.safety.service.ops_selfheal_r3.diagnosis import rule_based_diagnosis

    quota = rule_based_diagnosis(sg.SIGNAL_RAG_DEGRADED, {"detail": "HTTP 429: 1113 余额不足"})
    assert quota["root_cause_class"] == "quota_exhausted"
    assert all(p["action"] in ("notify_enriched", "rag_recheck") for p in quota["prescriptions"])

    upstream = rule_based_diagnosis(sg.SIGNAL_JOB_FAILED, {
        "dep_endpoints": ["192.168.5.7:9550"], "errors": [{"error": "ConnectTimeout"}],
    })
    assert upstream["root_cause_class"] == "upstream_outage"


# ═══════════════════════════════════════════════════════════════
# 四道闸（纯函数）
# ═══════════════════════════════════════════════════════════════


def test_check_gates_matrix(monkeypatch) -> None:
    from app.modules.safety.service.ops_selfheal_r3 import config
    from app.modules.safety.service.ops_selfheal_r3.actions import check_gates

    monkeypatch.setattr(config, "allowed_actions", lambda: {"notify_enriched", "rag_recheck"})
    monkeypatch.setattr(config, "repair_mode", lambda: "observe")
    # ① 白名单：L1 不在 → 拒
    assert check_gates("effects_unpark")[0] is False
    # ② 模式闸：L0 放行
    assert check_gates("rag_recheck") == (True, "ok")

    monkeypatch.setattr(
        config, "allowed_actions",
        lambda: {"notify_enriched", "rag_recheck", "effects_unpark", "job_backfill",
                 "job_window_extend"},
    )
    monkeypatch.setattr(config, "repair_mode", lambda: "observe")
    # ② observe 拦 L1（gate2 标注由 check_gates 返回原因携带——此处断言拒绝）
    assert check_gates("effects_unpark")[0] is False
    monkeypatch.setattr(config, "repair_mode", lambda: "auto")
    assert check_gates("effects_unpark") == (True, "ok")
    # L2 恒拒（job_window_extend 只上卡建议）
    assert check_gates("job_window_extend") == (False, "gate2_l2_manual_only")
    # ③ 前置：job_backfill 无日可补 → 拒
    assert check_gates("job_backfill", args={"run_days": []}) == (False, "gate3_no_missed_days")
    assert check_gates("job_backfill", args={"run_days": ["2026-11-09"]}) == (True, "ok")
    # 未知动作
    assert check_gates("rm -rf") == (False, "unknown_action:rm -rf")


# ═══════════════════════════════════════════════════════════════
# 诊断管线（db；observe 红线）
# ═══════════════════════════════════════════════════════════════


async def test_diagnose_observe_zero_l1_effects(db_session, exec_env) -> None:
    """样例 1/2 observe 路径：诊断落 stage_facts + 诊断卡；零 r3_repair effect。"""
    from app.platform.superagent.executors import run_task_once
    from app.platform.superagent.models import AgentEffect

    src = exec_env["source"]
    monkeypatch = exec_env["monkeypatch"]
    task, _trigger = await _make_job_ticket(db_session, src)
    calls = _llm_stub(monkeypatch, {
        "root_cause_class": "upstream_outage", "confidence": 0.9,
        "reasoning": "平台接口连接失败，本机其他链路正常",
        "cross_signals": [],
        "prescriptions": [
            {"action": "rag_recheck", "args": {}, "urgency": "now"},
            {"action": "job_backfill", "args": {}, "urgency": "next_scan"},
        ],
        "source": "llm",
    })

    outcome = await run_task_once(db_session, task.id)
    assert outcome == "ran"

    # LLM 单次调用 + 证据已采集（含端点提取）
    assert len(calls) == 1 and calls[0]["signal"] == "job_failed"
    # 注意：执行器中途 commit 后 stage_facts 后写不走 refresh（会丢待写态），用 flush
    await db_session.flush()
    r3 = task.stage_facts["r3"]
    assert r3["root_cause_class"] == "upstream_outage"
    assert r3["confidence"] == 0.9
    assert r3["dep_endpoints"] == ["http://192.168.5.7:9550/api/v1/tickets"]
    assert r3["stage"] == "diagnosed"  # 等恢复（upstream 不立即升级）
    assert task.stage_facts["latest_report"] == "progress"

    # 诊断卡已入队（dm_admin 先存后发）；observe 红线：零 r3_repair
    effects = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.dedupe_key.like("r3:%"))
        )
    ).scalars().all()
    kinds = [e.kind for e in effects]
    assert "dm_admin" in kinds
    assert all(e.kind != "r3_repair" for e in effects)
    diag = next(e for e in effects if e.dedupe_key.startswith("r3:diag:"))
    assert "上游依赖断连" in diag.payload["text"]
    await db_session.rollback()


async def test_diagnose_llm_degraded_quota_escalates(db_session, exec_env) -> None:
    """LLM 降级 + 余额类证据 → 规则表 quota_exhausted → needs_human + 升级卡。"""
    from app.platform.superagent.executors import run_task_once
    from app.platform.superagent.models import AgentEffect

    src = exec_env["source"]
    monkeypatch = exec_env["monkeypatch"]
    task, _ = await _make_job_ticket(
        db_session, src, error_text="HTTP 429: {\"code\":1113,\"msg\":\"余额不足\"}",
    )
    _llm_stub(monkeypatch, None)  # 模拟 LLM 失败 → 降级

    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    r3 = task.stage_facts["r3"]
    assert r3["root_cause_class"] == "quota_exhausted"
    assert r3["stage"] == "needs_human"
    assert task.stage_facts["latest_report"] == "blocked"
    effects = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.dedupe_key.like("r3:escalate:%"))
        )
    ).scalars().all()
    assert len(effects) == 1 and "充值" in effects[0].payload["text"]
    await db_session.rollback()


async def test_diagnose_auto_enqueues_l1_unpark(db_session, exec_env) -> None:
    """repair_mode=auto + 白名单含 unpark → r3_repair effect 先存后做。"""
    import uuid as uuid_mod

    from app.modules.safety.service.ops_selfheal_r3 import config
    from app.platform.superagent.executors import run_task_once
    from app.platform.superagent.models import AgentEffect

    src = exec_env["source"]
    monkeypatch = exec_env["monkeypatch"]
    monkeypatch.setattr(config, "repair_mode", lambda: "auto")
    monkeypatch.setattr(
        config, "allowed_actions",
        lambda: {"notify_enriched", "rag_recheck", "effects_unpark"},
    )
    # parked 信号工单（含一条 parked effect 行；dedupe 唯一防开发库残留冲突）
    db_session.add(AgentEffect(
        id=uuid_mod.uuid4(), kind="digest_cell_upsert",
        dedupe_key=f"park-{uuid_mod.uuid4().hex[:8]}",
        payload={}, status="failed", attempts=10, last_error="总是失败",
    ))
    await db_session.flush()

    import uuid as uuid_mod2
    from datetime import UTC, datetime

    from app.platform.superagent.models import AgentTrigger
    from app.platform.superagent.tasks import create_task

    trigger = AgentTrigger(
        id=uuid_mod2.uuid4(), source_id=src.id,
        external_id="ops:parked:digest_cell_upsert:2026-11-12",
        thread_key="ops:opsmisc:2026-11-12",
        actor={"id": "digest_cell_upsert", "type": "effect_kind"},
        payload={"signal": "effects_parked", "component": "digest_cell_upsert",
                 "count": 1, "samples": [], "at": datetime.now(UTC).isoformat()},
        received_at=datetime.now(UTC),
    )
    db_session.add(trigger)
    await db_session.flush()
    task = await create_task(
        db_session, short_name="r3:parked", title="R3 parked", executor="r3_ops_heal",
        origin_trigger_id=trigger.id,
        mandate={"rule_id": "r3_ops_failure", "strength": "inferred"},
        origin_thread_key="ops:opsmisc:2026-11-12",
    )
    _llm_stub(monkeypatch, {
        "root_cause_class": "data_issue", "confidence": 0.7, "reasoning": "r",
        "prescriptions": [{"action": "effects_unpark", "args": {}, "urgency": "now"}],
        "source": "llm",
    })

    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    r3 = task.stage_facts["r3"]
    assert r3["stage"] == "repairing" and r3["executed"] == ["effects_unpark"]
    repairs = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.kind == "r3_repair")
        )
    ).scalars().all()
    assert len(repairs) == 1
    assert repairs[0].payload["action"] == "effects_unpark"
    assert repairs[0].payload["component"] == "digest_cell_upsert"
    await db_session.rollback()


# ═══════════════════════════════════════════════════════════════
# 二期扩面：四类新信号证据采集
# ═══════════════════════════════════════════════════════════════


async def test_evidence_aicall_push_ragflow_event(db_session, exec_env) -> None:
    """四类新信号 collect_evidence 各抓针对性证据（LLM 入参含关键字段）。"""
    import uuid as uuid_mod
    from datetime import UTC, datetime, timedelta

    from app.modules.safety.ai_audit.models import AICallAudit
    from app.modules.safety.service.ops_selfheal_r3 import diagnosis, signals
    from app.platform.superagent.models import AgentEffect, AgentOutboxMessage

    monkeypatch = exec_env["monkeypatch"]

    # ── ① ai_call_failed：窗口内 3 failed 1 success ──
    now = datetime.now(UTC)
    for i in range(3):
        db_session.add(AICallAudit(
            scenario="agent_chat", model="deepseek-flash", status="failed",
            error=f"超时 boom-{i}", created_at=now - timedelta(minutes=i + 1),
        ))
    db_session.add(AICallAudit(
        scenario="other_scn", model="m", status="success", created_at=now,
    ))
    await db_session.flush()
    ev = await diagnosis.collect_evidence(db_session, {
        "signal": signals.SIGNAL_AICALL_FAILED, "scenario": "agent_chat",
        "failed_count": 3,
    })
    assert ev["scenario"] == "agent_chat"
    assert ev["failed_count"] == 3
    assert ev["success_count_in_window"] >= 0
    assert len(ev["samples"]) == 3
    assert all("boom" in (s.get("error") or "") for s in ev["samples"])

    # ── ② push_failed（outbox dropped）──
    db_session.add(AgentOutboxMessage(
        conversation="r3ev-conv", purpose="message", channel={"chat_id": "oc_x"},
        body={}, status="dropped", attempts=10,
        dropped_reason="api error", last_error="conn reset",
    ))
    db_session.add(AgentEffect(
        id=uuid_mod.uuid4(), kind="dm_admin", dedupe_key=f"dm-{uuid_mod.uuid4().hex[:8]}",
        payload={}, status="failed", attempts=5, last_error="send failed",
    ))
    await db_session.flush()
    ev2 = await diagnosis.collect_evidence(db_session, {
        "signal": signals.SIGNAL_PUSH_FAILED, "component": "outbox",
    })
    assert ev2["component"] == "outbox"
    assert ev2["dropped_count"] >= 1
    # dev 库有真实 dropped 行（hw_urge 等）——samples 为 dropped 行集合，断言非空即可
    assert isinstance(ev2["samples"], list) and len(ev2["samples"]) >= 1
    ev3 = await diagnosis.collect_evidence(db_session, {
        "signal": signals.SIGNAL_PUSH_FAILED, "component": "dm_admin",
    })
    assert ev3["component"] == "dm_admin"
    assert ev3["failed_effect_count"] >= 1

    # ── ④ ragflow_batch_fail ──
    ev4 = await diagnosis.collect_evidence(db_session, {
        "signal": signals.SIGNAL_RAGFLOW_FAILED, "failed_doc_count": 6,
        "failed_run_count": 0,
    })
    assert ev4["failed_doc_count"] == 6
    assert ev4["failed_run_count"] == 0

    # ── ③ feishu_event_failed ──
    ev5 = await diagnosis.collect_evidence(db_session, {
        "signal": signals.SIGNAL_EVENT_FAILED, "event_type": "bitable.record.changed",
        "handler": "handle_x", "error": "ValueError: bad",
    })
    assert ev5["event_type"] == "bitable.record.changed"
    assert ev5["handler"] == "handle_x"
    assert "ValueError" in ev5["error"]
    await db_session.rollback()


def test_rule_based_diagnosis_new_signals() -> None:
    """四类新信号规则降级：余额/连接类证据直出 quota/upstream，不抛异常。"""
    from app.modules.safety.service.ops_selfheal_r3 import signals as sg
    from app.modules.safety.service.ops_selfheal_r3.diagnosis import rule_based_diagnosis

    q = rule_based_diagnosis(sg.SIGNAL_AICALL_FAILED, {
        "scenario": "agent_chat", "samples": [{"error": "429 余额不足"}],
        "dep_endpoints": [],
    })
    assert q["root_cause_class"] == "quota_exhausted"

    n = rule_based_diagnosis(sg.SIGNAL_EVENT_FAILED, {
        "handler": "h", "error": "ConnectTimeout", "dep_endpoints": [],
    })
    assert n["root_cause_class"] == "network"

    g = rule_based_diagnosis(sg.SIGNAL_RAGFLOW_FAILED, {
        "failed_doc_count": 5, "samples": [{"last_error": "连接超时"}],
    })
    assert g["root_cause_class"] == "network"

    p = rule_based_diagnosis(sg.SIGNAL_PUSH_FAILED, {"component": "outbox", "samples": []})
    assert p["root_cause_class"] in sg.ROOT_CAUSE_CLASSES
    # 降级路径处方只含 L0
    for diag in (q, n, g, p):
        assert all(x["action"] in ("notify_enriched", "rag_recheck") for x in diag["prescriptions"])
