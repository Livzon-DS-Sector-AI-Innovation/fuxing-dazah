"""观测面 + 冒烟③测试 —— watchdog 三规则 / decisions 转正 / 需要人快照 / 消防规则矩阵。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.safety.superagent_bridge import fire_candidate_rule
from app.platform.superagent.ingest import ingest_draft
from app.platform.superagent.models import (
    AgentDecision,
    AgentEffect,
    AgentSource,
    AgentTask,
)
from app.platform.superagent.policy import (
    apply_new_policy,
)
from app.platform.superagent.sources import TriggerDraft
from app.platform.superagent.tasks import create_task
from app.platform.superagent.watchdog import (
    build_needs_human_snapshot,
    collect_watchdog_findings,
    has_findings,
    render_findings_text,
    run_watchdog_round,
)

# ═══════════════════════════════════════════════════════════════
# 冒烟③ A 层：消防候选规则矩阵（R1 §1.2 口径全覆盖）
# ═══════════════════════════════════════════════════════════════


def _fire_hit(nature: str, cause: str) -> bool:
    from app.platform.superagent.policy import evaluate_rule

    hit, _ = evaluate_rule(fire_candidate_rule(), {
        "fields": {"报警性质": nature, "原因分类": cause},
    })
    return hit


def test_fire_rule_whitelist_hits() -> None:
    """白名单四值命中（性质非排除集）。"""
    for cause in ("现场着火", "硫化氢引发", "氨水引发", "甲烷引发"):
        assert _fire_hit("泄漏报警", cause), cause
    # 白名单原因即使被标误报也进（矛盾标记留给人工——坑②口径）
    assert _fire_hit("误报", "氨水引发")


def test_fire_rule_excluded_natures() -> None:
    """性质 ∈ 排除集一律不进（即使原因在白名单——测试/演练计划内）。"""
    for nature in ("测试报警", "测试性质", "演练引发"):
        assert not _fire_hit(nature, "现场着火"), nature


def test_fire_rule_fault_subrule() -> None:
    """坑①故障子规则：性质=故障报警 且 原因∉{测试,演练} → 命中。"""
    assert _fire_hit("故障报警", "设备误报")
    assert _fire_hit("故障报警", "现场施工")
    assert not _fire_hit("故障报警", "测试")       # 坑①的漏网修复：故障|测试 不进
    assert not _fire_hit("故障报警", "演练引发")


def test_fire_rule_noise_rejected() -> None:
    """纯噪音不进：误报+蒸汽 / 误报+设备误报（单条不进，聚合口径是二期）。"""
    assert not _fire_hit("误报", "蒸汽引发")
    assert not _fire_hit("误报", "设备误报")
    assert not _fire_hit("误报", "氧气变化")


# ═══════════════════════════════════════════════════════════════
# B 层：watchdog 三规则 + 需要人快照 + 转正
# ═══════════════════════════════════════════════════════════════


async def _blocked_task(db_session, *, hours: float = 30) -> AgentTask:
    task = await create_task(db_session, short_name="t-blk", title="受阻任务",
                             executor="noop_exec")
    task.stage_facts = {
        "latest_report": "blocked",
        "latest_report_at": (datetime.now(UTC) - timedelta(hours=hours)).isoformat(),
        "human_after_report": False,
        "has_active_assignment": True,
    }
    await db_session.flush()
    return task


@pytest.fixture(autouse=True)
async def _purge_unresolved_observe_decisions():
    """observe decisions 清前缀（2026-11-13 T2：钉死 dev 库残留态噪声）。

    observe_backlog / observe_replay 口径是全表 would_accept∧¬replay∧resolution
    IS NULL 计数——dev 库 11-03 observe 冒烟残留 24 行（hardware_alert_urge /
    hardware_digest_push）会污染绝对断言（51→75、0→2）。autouse 在用例前后
    清掉本测试域外的未处置 observe 决策（按 id 精确删除，不动用例内新写行）。
    """
    from sqlalchemy import delete as _delete

    from tests.conftest import _test_session_factory

    async def _purge() -> None:
        async with _test_session_factory() as s:
            ids = (
                await s.execute(
                    select(AgentDecision.id).where(
                        AgentDecision.would_accept.is_(True),
                        AgentDecision.replay.is_(False),
                        AgentDecision.resolution.is_(None),
                        AgentDecision.rule_id != "fire_alarm_candidate",
                    )
                )
            ).scalars().all()
            if ids:
                await s.execute(
                    _delete(AgentDecision).where(AgentDecision.id.in_(ids))
                )
                await s.commit()

    await _purge()
    yield
    await _purge()


async def test_watchdog_blocked_over_24h(db_session) -> None:
    await _blocked_task(db_session, hours=30)
    findings = await collect_watchdog_findings(db_session)
    assert len(findings["blocked_stale"]) == 1
    assert has_findings(findings)
    assert "受阻超时" in render_findings_text(findings)


async def test_watchdog_blocked_recent_not_flagged(db_session) -> None:
    """受阻 2h（未超阈）不报——一次网络抖动不打扰人。"""
    await _blocked_task(db_session, hours=2)
    findings = await collect_watchdog_findings(db_session)
    assert findings["blocked_stale"] == []


async def test_watchdog_blocked_with_human_message_not_flagged(db_session) -> None:
    """受阻但此后有人的消息 → 不报（人已在处理）。"""
    task = await _blocked_task(db_session, hours=30)
    task.stage_facts = {**task.stage_facts, "human_after_report": True}
    await db_session.flush()
    findings = await collect_watchdog_findings(db_session)
    assert findings["blocked_stale"] == []


async def test_watchdog_queued_over_threshold(db_session) -> None:
    """排队超 2h（created_at 老）→ 报。

    排队=无执行器空位（一期程序执行器常驻绑定，此事实由未来 worker 域
    产生；测试显式构造 has_active_assignment=False）。
    """
    task = await create_task(db_session, short_name="t-q", title="排队任务",
                             executor="noop_exec")
    task.stage_facts = {**(task.stage_facts or {}), "has_active_assignment": False}
    task.created_at = datetime.now(UTC) - timedelta(hours=3)
    await db_session.flush()
    findings = await collect_watchdog_findings(db_session)
    assert len(findings["queued_stale"]) == 1


async def test_watchdog_observe_backlog(db_session) -> None:
    """observe 积压超阈值 → 报 + dm_admin effect 入队（先存后发）。"""
    src = AgentSource(kind="test_echo", name=f"test.wd.{uuid.uuid4().hex[:6]}",
                      config={}, enabled=True)
    db_session.add(src)
    await db_session.flush()
    policy, _ = await apply_new_policy(db_session, rules=[], accept_mode="observe")
    for i in range(51):
        _, trigger = await ingest_draft(db_session, src, TriggerDraft(
            external_id=f"wd-{i}", thread_key=f"t:wd-{i}",
            payload={"fields": {"报警性质": "泄漏报警"}},
        ))
        db_session.add(AgentDecision(
            trigger_id=trigger.id, rule_id="fire_alarm_candidate", outcome="accept",
            would_accept=True, policy_version=policy.version_hash, mode="observe",
        ))
    await db_session.flush()

    findings = await run_watchdog_round(db_session)
    assert findings["observe_backlog"] == 51
    alerts = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.kind == "dm_admin",
                                      AgentEffect.dedupe_key.like("watchdog:%"))
        )
    ).scalars().all()
    assert len(alerts) == 1  # 按日幂等：一轮一条


async def test_needs_human_snapshot_sections(db_session) -> None:
    """快照四段：待验收/待回答/受阻超时/observe 回放（stage 现算口径）。"""
    t1 = await create_task(db_session, short_name="t-ok", title="等验收", executor="x")
    t1.stage_facts = {"latest_report": "ready", "has_active_assignment": True}
    t2 = await create_task(db_session, short_name="t-ask", title="等回答", executor="x")
    t2.stage_facts = {"attention_pending": True}
    await _blocked_task(db_session)

    snapshot = await build_needs_human_snapshot(db_session)
    assert snapshot["await_accept"]["count"] == 1
    assert snapshot["await_answer"]["count"] == 1
    assert snapshot["blocked_stale"]["count"] == 1
    assert snapshot["observe_replay"]["count"] == 0


async def test_promote_decision_opens_task_and_marks(db_session) -> None:
    """转正：按当时决策开任务（strength=promoted），决策标记 resolved；重复处置 409 语义。"""
    from app.platform.superagent.policy import resolve_decision

    src = AgentSource(kind="test_echo", name=f"test.pm.{uuid.uuid4().hex[:6]}",
                      config={}, enabled=True)
    db_session.add(src)
    await db_session.flush()
    policy, _ = await apply_new_policy(db_session, rules=[], accept_mode="observe")
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="pm-1", thread_key="t:pm-1",
        payload={"fields": {"报警性质": "火警", "部门": "车间一"}},
    ))
    decision = AgentDecision(
        trigger_id=trigger.id, rule_id="fire_alarm_candidate", outcome="accept",
        would_accept=True, policy_version=policy.version_hash, mode="observe",
    )
    db_session.add(decision)
    await db_session.flush()

    task = await resolve_decision(db_session, decision, resolution="promoted",
                                  resolved_by="admin-1")
    assert task is not None
    assert task.mandate["strength"] == "promoted"
    assert task.mandate["policy_version"] == decision.policy_version
    assert decision.resolution == "promoted"

    again = await resolve_decision(db_session, decision, resolution="dismissed")
    assert again is None  # 幂等：已处置不再动


async def test_snapshot_excludes_resolved_decisions(db_session) -> None:
    """已处置（promoted/dismissed）决策不再出现在回放。"""
    from app.platform.superagent.policy import resolve_decision

    src = AgentSource(kind="test_echo", name=f"test.rs.{uuid.uuid4().hex[:6]}",
                      config={}, enabled=True)
    db_session.add(src)
    await db_session.flush()
    policy, _ = await apply_new_policy(db_session, rules=[], accept_mode="observe")
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="rs-1", thread_key="t:rs-1",
        payload={"fields": {"报警性质": "火警"}},
    ))
    decision = AgentDecision(
        trigger_id=trigger.id, rule_id="fire_alarm_candidate", outcome="accept",
        would_accept=True, policy_version=policy.version_hash, mode="observe",
    )
    db_session.add(decision)
    await db_session.flush()
    await resolve_decision(db_session, decision, resolution="dismissed")

    snapshot = await build_needs_human_snapshot(db_session)
    assert snapshot["observe_replay"]["count"] == 0
