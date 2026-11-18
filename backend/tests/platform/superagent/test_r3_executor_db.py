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
    """R3 行清理（快照差集法，R3 三期 T1）——旧全删 purge 会误删真机工单/源行。"""
    from tests.platform.superagent._r3_snapshot_purge import (
        purge_new_r3_rows,
        snapshot_r3_rows,
    )

    snap = await snapshot_r3_rows()
    yield
    await purge_new_r3_rows(snap)


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
    from tests.platform.superagent._r3_snapshot_purge import ensure_r3_source

    src = await ensure_r3_source(
        db_session, name=_SCAN_SOURCE, kind="ops_scan",
        config={"schedule": {"strategy": "interval", "interval_seconds": 300,
                              "timezone": "Asia/Shanghai"}, "evaluate": True},
    )

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
    # （按 task.id 圈定——开闸后 dev 库有真机 r3:% effect，裸 LIKE 会泄入）
    task_prefix = f"r3:diag:{task.id}"
    effects = [
        e for e in (
            await db_session.execute(
                select(AgentEffect).where(AgentEffect.dedupe_key.like("r3:%"))
            )
        ).scalars().all()
        if str(task.id) in e.dedupe_key
    ]
    kinds = [e.kind for e in effects]
    assert "dm_admin" in kinds
    assert all(e.kind != "r3_repair" for e in effects)
    diag = next(e for e in effects if e.dedupe_key.startswith(task_prefix))
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
    effects = [
        e for e in (
            await db_session.execute(
                select(AgentEffect).where(AgentEffect.dedupe_key.like("r3:escalate:%"))
            )
        ).scalars().all()
        if str(task.id) in e.dedupe_key  # 按 task 圈定（开闸后真机 escalate 常驻）
    ]
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


# ═══════════════════════════════════════════════════════════════
# 四信号恢复判定 —— 工单级全清 + verify 分支（三期 T2）
# ═══════════════════════════════════════════════════════════════

_MISC_EID_PREFIX = {
    "ai_call_failed": "aicall", "push_failed": "push",
    "ragflow_batch_fail": "ragflow", "feishu_event_failed": "event",
    "effects_parked": "parked", "hazard_deadletter": "deadletter",
    "ops_batch": "batch",
}


async def _make_misc_ticket(
    db_session, source, *, signal: str, minutes_ago: float = 5,
    signals_seen: list[str] | None = None, extra_r3: dict[str, Any] | None = None,
):
    """已诊断 opsmisc 族工单（stage_facts 直填，跳过诊断段）+ 开单 trigger。

    minutes_ago 控制 r3.last_signal_at（安静窗口锚：仅故障类输入推进它）。
    """
    import uuid as uuid_mod
    from datetime import UTC, datetime, timedelta

    from app.platform.superagent.models import AgentTrigger
    from app.platform.superagent.tasks import create_task

    tag = uuid_mod.uuid4().hex[:8]
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "signal": signal, "at": now.isoformat(), "channel": {"kind": "ops_misc"},
    }
    if signal == "ai_call_failed":
        payload["scenario"] = f"r3t场景{tag}"
    elif signal == "push_failed":
        payload["component"] = "outbox"
    elif signal == "feishu_event_failed":
        payload["handler"] = f"r3t_handler_{tag}"
    thread = f"ops:opsmisc:2030-01-01"
    trigger = AgentTrigger(
        id=uuid_mod.uuid4(), source_id=source.id,
        external_id=f"ops:{_MISC_EID_PREFIX[signal]}:{tag}:2030-01-01:failed",
        thread_key=thread, actor={"id": tag, "type": "test"},
        payload=payload, received_at=now,
    )
    db_session.add(trigger)
    await db_session.flush()
    task = await create_task(
        db_session, short_name=f"r3:misc:{tag}", title=f"R3 misc {signal}",
        executor="r3_ops_heal", origin_trigger_id=trigger.id,
        mandate={"rule_id": "r3_ops_failure", "strength": "inferred"},
        origin_thread_key=thread,
    )
    r3: dict[str, Any] = {
        "stage": "diagnosed", "signal": signal,
        "diag_at": now.isoformat(), "diag_source": "rules",
        "root_cause_class": "unknown", "confidence": 0.5,
        "executed": [], "planned": [], "repair_rounds": 0,
        "first_seen_at": (now - timedelta(minutes=minutes_ago)).isoformat(),
        "last_signal_at": (now - timedelta(minutes=minutes_ago)).isoformat(),
        "evidence": {},
        "signals_seen": signals_seen or [signal],
    }
    if signal == "ai_call_failed":
        r3["scenario"] = payload["scenario"]
    elif signal == "push_failed":
        r3["component"] = "outbox"
    if extra_r3:
        r3.update(extra_r3)
    task.stage_facts = {"r3": r3}
    await db_session.flush()
    return task, trigger


async def _deliver(db_session, task, payload: dict[str, Any]) -> None:
    """已送达输入（run_task_once 只消费 delivered 且未读的）。"""
    from datetime import UTC, datetime

    from app.platform.superagent.models import AgentInput

    db_session.add(AgentInput(
        task_id=task.id, kind="trigger", payload=payload,
        delivered_at=datetime.now(UTC),
    ))
    await db_session.flush()


def _stub_misc_scanners(monkeypatch, *, drafts_by: dict[str, list] | None = None) -> None:
    """钉死 scan_source 四扫描器（现势 firing 判定同源点）——测试外生行防污染。"""
    from app.modules.safety.service.ops_selfheal_r3 import scan_source

    drafts_by = drafts_by or {}
    for fn in ("_scan_ai_calls", "_scan_push_failures", "_scan_ragflow"):
        ret = drafts_by.get(fn, [])

        async def _fixed(session, _ret=list(ret)):
            return list(_ret)

        monkeypatch.setattr(scan_source, fn, _fixed)


async def _closure_effects(db_session, task) -> list[Any]:
    from app.platform.superagent.models import AgentEffect

    return [
        e for e in (
            await db_session.execute(
                select(AgentEffect).where(AgentEffect.dedupe_key == f"r3:closure:{task.id}")
            )
        ).scalars().all()
    ]


async def test_verify_misc_aicall_positive_recovers(db_session, exec_env) -> None:
    """ai_call 正向证据快路：scenario 出现晚于最后 failed 的 success → 收口。"""
    from datetime import UTC, datetime, timedelta

    from app.modules.safety.ai_audit.models import AICallAudit
    from app.platform.superagent.executors import run_task_once

    src = exec_env["source"]
    task, _ = await _make_misc_ticket(db_session, src, signal="ai_call_failed", minutes_ago=90)
    scenario = task.stage_facts["r3"]["scenario"]
    now = datetime.now(UTC)
    db_session.add(AICallAudit(
        scenario=scenario, model="test", input_truncated=False, output_truncated=False,
        status="failed", error="429", created_at=now - timedelta(minutes=80),
    ))
    db_session.add(AICallAudit(
        scenario=scenario, model="test", input_truncated=False, output_truncated=False,
        status="success", created_at=now - timedelta(minutes=10),
    ))
    await db_session.flush()
    _stub_misc_scanners(exec_env["monkeypatch"])
    await _deliver(db_session, task, {"signal": "ops_recovered", "task_id": str(task.id)})

    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    assert await _closure_effects(db_session, task), "正向证据应入队收口卡"
    assert task.stage_facts["r3"]["stage"] == "verify_wait"
    await db_session.rollback()


async def test_verify_misc_quiet_gate_blocks_early(db_session, exec_env) -> None:
    """push 安静门：last_signal_at 5min 前（未满 60min）→ 不收口继续等。"""
    from app.platform.superagent.executors import run_task_once

    src = exec_env["source"]
    task, _ = await _make_misc_ticket(db_session, src, signal="push_failed", minutes_ago=5)
    _stub_misc_scanners(exec_env["monkeypatch"])
    await _deliver(db_session, task, {"signal": "ops_recovered", "task_id": str(task.id)})

    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    assert not await _closure_effects(db_session, task), "安静窗口未满不得收口"
    assert task.stage_facts["r3"]["stage"] == "verify_wait"
    await db_session.rollback()


async def test_verify_misc_quiet_elapsed_closes(db_session, exec_env) -> None:
    """push 安静门：61min 前最后故障 + 现势不 firing → 收口。"""
    from app.platform.superagent.executors import run_task_once

    src = exec_env["source"]
    task, _ = await _make_misc_ticket(db_session, src, signal="push_failed", minutes_ago=61)
    _stub_misc_scanners(exec_env["monkeypatch"])
    await _deliver(db_session, task, {"signal": "ops_recovered", "task_id": str(task.id)})

    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    assert await _closure_effects(db_session, task), "安静窗口已满且现势全清应收口"
    await db_session.rollback()


async def test_verify_misc_event_quiet_closes(db_session, exec_env) -> None:
    """event 无恢复证据：纯安静门（61min）→ 收口（D10 已知限制口径）。"""
    from app.platform.superagent.executors import run_task_once

    src = exec_env["source"]
    task, _ = await _make_misc_ticket(db_session, src, signal="feishu_event_failed", minutes_ago=61)
    _stub_misc_scanners(exec_env["monkeypatch"])
    await _deliver(db_session, task, {"signal": "ops_recovered", "task_id": str(task.id)})

    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    assert await _closure_effects(db_session, task)
    await db_session.rollback()


async def test_verify_parked_gated_by_other_seen_signals(db_session, exec_env) -> None:
    """混合日常单：parked 自身已清但同单 push 未满安静 → 不收口（旧路径会收口）。"""
    from app.platform.superagent.executors import run_task_once

    src = exec_env["source"]
    task, _ = await _make_misc_ticket(
        db_session, src, signal="effects_parked", minutes_ago=5,
        signals_seen=["effects_parked", "push_failed"],
        extra_r3={"component": f"r3t_kind_{__import__('uuid').uuid4().hex[:6]}"},
    )
    _stub_misc_scanners(exec_env["monkeypatch"])  # push 现势不 firing；仅安静门未满
    await _deliver(db_session, task, {"signal": "ops_recovered", "task_id": str(task.id)})

    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    assert not await _closure_effects(db_session, task), "同单其他已见信号未清不得收口"
    assert task.stage_facts["r3"]["stage"] == "verify_wait"
    await db_session.rollback()


async def test_diagnose_accumulates_signals_seen(db_session, exec_env) -> None:
    """同日多信号日常单：新信号输入重诊断 → signals_seen 累积（全清判定依据）。"""
    from app.platform.superagent.executors import run_task_once

    src = exec_env["source"]
    task, _ = await _make_misc_ticket(db_session, src, signal="ai_call_failed", minutes_ago=30)
    _stub_misc_scanners(exec_env["monkeypatch"])
    await _deliver(db_session, task, {"signal": "push_failed", "component": "outbox",
                                      "at": __import__("datetime").datetime.now(
                                          __import__("datetime").UTC).isoformat()})

    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    seen = task.stage_facts["r3"].get("signals_seen") or []
    assert "ai_call_failed" in seen and "push_failed" in seen
    assert task.stage_facts["r3"]["signal"] == "push_failed"  # 最新信号
    await db_session.rollback()


async def test_verify_batch_gated_by_four_type_items(db_session, exec_env) -> None:
    """聚合单含四类型子项：子项未清（安静门未满）→ 不收口；全清 → 收口。"""
    from app.platform.superagent.executors import run_task_once

    src = exec_env["source"]
    items = [{"signal": "push_failed", "component": "outbox"},
             {"signal": "feishu_event_failed", "handler": "r3t_h"}]
    task, _ = await _make_misc_ticket(
        db_session, src, signal="ops_batch", minutes_ago=5,
        signals_seen=["ops_batch", "push_failed", "feishu_event_failed"],
        extra_r3={"evidence": {"items": items}},
    )
    _stub_misc_scanners(exec_env["monkeypatch"])
    await _deliver(db_session, task, {"signal": "ops_recovered", "task_id": str(task.id)})
    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    assert not await _closure_effects(db_session, task), "四类型子项未清不得收口"

    # 同单推进时钟到安静窗口外，再触发一轮核对 → 收口
    from datetime import UTC, datetime, timedelta

    task.stage_facts["r3"]["last_signal_at"] = (
        datetime.now(UTC) - timedelta(minutes=61)
    ).isoformat()
    await db_session.flush()
    await _deliver(db_session, task, {"signal": "ops_recovered", "task_id": str(task.id)})
    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    assert await _closure_effects(db_session, task)
    await db_session.rollback()


async def test_verify_misc_firing_blocks_despite_quiet(db_session, exec_env) -> None:
    """现势复测半门（审查 Spec 补）：安静已满但扫描器仍产同信号 draft → 不收口。"""
    from app.platform.superagent.executors import run_task_once
    from app.platform.superagent.sources import TriggerDraft

    src = exec_env["source"]
    task, _ = await _make_misc_ticket(db_session, src, signal="push_failed", minutes_ago=61)
    _stub_misc_scanners(exec_env["monkeypatch"], drafts_by={
        "_scan_push_failures": [TriggerDraft(
            external_id="ops:push:outbox:2030-01-01:failed",
            thread_key="ops:opsmisc:2030-01-01",
            actor={"id": "outbox", "type": "push_channel"},
            payload={"signal": "push_failed", "component": "outbox",
                     "channel": {"kind": "ops_push", "component": "outbox"}},
        )],
    })
    await _deliver(db_session, task, {"signal": "ops_recovered", "task_id": str(task.id)})

    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    assert not await _closure_effects(db_session, task), "现势仍 firing 不得收口"
    assert "push_failed" in (task.stage_facts["r3"].get("recovery_pending") or [])
    await db_session.rollback()


async def test_recovery_fallback_no_signals_seen(db_session, exec_env) -> None:
    """老工单收编：无 signals_seen → 回退 [r3.signal] 判定（T2 验收5 补）。"""
    from app.platform.superagent.executors import run_task_once

    src = exec_env["source"]
    task, _ = await _make_misc_ticket(
        db_session, src, signal="feishu_event_failed", minutes_ago=61,
        signals_seen=["__drop__"],  # 占位：构造后删键模拟老工单
    )
    r3 = dict(task.stage_facts["r3"])
    r3.pop("signals_seen", None)
    task.stage_facts = {"r3": r3}
    await db_session.flush()
    _stub_misc_scanners(exec_env["monkeypatch"])
    await _deliver(db_session, task, {"signal": "ops_recovered", "task_id": str(task.id)})

    assert await run_task_once(db_session, task.id) == "ran"
    await db_session.flush()
    assert await _closure_effects(db_session, task), "回退口径应按 [signal] 判定并收口"
    await db_session.rollback()
