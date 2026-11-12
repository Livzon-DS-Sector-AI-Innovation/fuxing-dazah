"""r3_ops_heal 程序执行器 —— 三段编排 + 工单生命周期（§4.3/§4.5）。

事务边界（R1 范式）：run_task_once 持 task 行锁事务外调用（自开 session）；
**本执行器绝不 UPDATE agent_tasks 行**（与外层行锁死锁 + 外层回写覆盖），
阶段事实一律经 ``Report(output={"r3": …})`` 由 run_task_once 合并落库。
effects/outbox/inputs 只 INSERT，不冲突。

阶段机（stage_facts["r3"]["stage"]）：
detected → diagnosed → repairing → verify_wait → closed（=task ended，
由 r3_closure_card handler 发送成功后置）；任一点可 → needs_human
（2 轮未收口 / 处方 human / L2 建议未决 / observe 无 L1 权限）。

关单双条件：恢复分支核对「处方已执行 + 信号已清除 + 漏审日全终态」→
入队 ``r3_closure_card``（发送成功才关单；失败工单保持 open 由 effects
退避重发）。上游断连类无 dep_recovered 永不进收口（跨天持有）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.modules.safety.service.ops_selfheal_r3 import (
    actions,
    backfill,
    cards,
    config,
    diagnosis,
    signals,
)
from app.platform.superagent.executors import Report

logger = logging.getLogger(__name__)

#: 需等恢复的根因（不立即升级；上游断连跨天持有/网络等自愈）
_WAIT_RECOVERY_CLASSES = frozenset({"upstream_outage", "network"})

#: 本地不可修根因 → 直接升级人工
_HUMAN_CLASSES = frozenset({"quota_exhausted", "config_error", "code_bug"})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _load_origin_payload(session: Any, task: Any) -> dict[str, Any]:
    """开单 Trigger payload（create_task 首条 Input 为空壳，信号在 Trigger 上）。"""
    if task.origin_trigger_id is None:
        return {}
    from app.platform.superagent.models import AgentTrigger

    trigger = await session.get(AgentTrigger, task.origin_trigger_id)
    return dict(trigger.payload or {}) if trigger is not None else {}


def _is_recovery_input(payload: dict[str, Any]) -> bool:
    if payload.get("signal") in signals.RECOVERY_SIGNALS:
        return True
    return payload.get("type") in ("repair_done", "retry")


async def r3_ops_heal(task_dict: dict[str, Any], inputs: list[dict[str, Any]]) -> Report:
    """R3 工单执行入口（诊断管线 / 收口核对两分支）。"""
    from app.core.database import async_session_factory

    task_id = uuid.UUID(str(task_dict["id"]))
    async with async_session_factory() as session:
        from app.platform.superagent.models import AgentTask

        task = await session.get(AgentTask, task_id)
        if task is None:
            return Report(kind="failed", end_task=True, note="任务不存在（已终态清理？）")
        r3 = signals.r3_facts(task.stage_facts)

        latest = dict(inputs[-1]) if inputs else {}
        if "signal" not in latest and "type" not in latest:
            latest = await _load_origin_payload(session, task)

        if not r3.get("diag_at") or (latest.get("signal") in signals.FAILURE_SIGNALS
                                     and latest.get("signal") != signals.SIGNAL_BATCH
                                     and _is_new_flap(r3, latest)):
            report = await _phase_diagnose(session, task_id, r3, latest)
        elif _is_recovery_input(latest) or latest.get("signal") in signals.FAILURE_SIGNALS:
            report = await _phase_verify(session, task_id, r3, latest)
        else:
            report = await _phase_diagnose(session, task_id, r3, latest)
        await session.commit()
        return report


def _is_new_flap(r3: dict[str, Any], latest: dict[str, Any]) -> bool:
    """同 thread 新故障输入（rag 抖动等）：信号时间晚于上次诊断 → 重诊断一轮。"""
    if r3.get("signal") != latest.get("signal"):
        return True
    return bool(latest.get("at")) and str(latest.get("at")) > str(r3.get("last_signal_at") or "")


# ═══════════════════════════════════════════════════════════════
# 诊断管线（A 证据 → B 归因 → C 处方四道闸）
# ═══════════════════════════════════════════════════════════════


async def _phase_diagnose(
    session: Any, task_id: uuid.UUID, r3: dict[str, Any], payload: dict[str, Any],
) -> Report:
    from app.platform.superagent.effects import enqueue_effect

    signal = str(payload.get("signal") or signals.SIGNAL_BATCH)
    evidence = await diagnosis.collect_evidence(session, payload)
    diag = await diagnosis.diagnose(signal, evidence)
    mode = config.repair_mode()
    rounds = int(r3.get("repair_rounds") or 0)

    executed: list[str] = []
    planned: list[str] = []
    suggestions: list[str] = []
    blocked_by_rounds = False
    for p in diag.get("prescriptions") or []:
        action, args, urgency = str(p.get("action") or ""), p.get("args") or {}, str(p.get("urgency"))
        if action == "notify_enriched":
            continue  # 诊断卡本体（总发）
        if action == "rag_recheck":
            if action in config.allowed_actions():
                evidence["rag_recheck"] = await diagnosis._probe_rag_raw()
            continue
        if action == "job_backfill":
            # 补跑在恢复分支按漏审日定局执行（诊断期窗口未耗尽，无日可补）
            suggestions.append("恢复后自动补跑漏审日（job_backfill）")
            continue
        if action == "job_window_extend" or urgency == "human":
            if action != "notify_enriched":
                suggestions.append(f"{action}（需人工）")
            continue
        ok, reason = actions.check_gates(action, args=args)
        if ok and mode == "auto" and rounds < config.max_repair_rounds():
            await enqueue_effect(
                session, "r3_repair",
                {"task_id": str(task_id), "action": action, "args": args,
                 "round": rounds + 1,
                 "component": (evidence.get("component") or ""),
                 "subject": str(evidence.get("job_name") or evidence.get("component") or signal)},
                dedupe_key=f"r3:repair:{task_id}:{action}:{rounds + 1}",
            )
            executed.append(action)
        elif ok and mode == "auto":
            blocked_by_rounds = True  # 过闸但轮上限已到：可修而不得修 → 升级
        elif ok:
            planned.append(action)
        else:
            suggestions.append(f"{action} 未过闸（{reason}）")

    if executed:
        rounds += 1

    rc = str(diag.get("root_cause_class") or "unknown")
    human_urgent = (
        rc in _HUMAN_CLASSES
        or (diag.get("urgency_hint") == "human" and diag.get("source") == "rules" and rc == "unknown")
    )
    stage = signals.R3_STAGE_DIAGNOSED
    if executed:
        stage = signals.R3_STAGE_REPAIRING
    escalate_guidance = ""
    if human_urgent and rc not in _WAIT_RECOVERY_CLASSES:
        stage = signals.R3_STAGE_NEEDS_HUMAN
        escalate_guidance = _human_guidance(rc, evidence)
    elif blocked_by_rounds:
        stage = signals.R3_STAGE_NEEDS_HUMAN
        escalate_guidance = f"已达修复轮上限（{config.max_repair_rounds()} 轮）未收口，可修动作被轮闸拦下"

    dep_endpoints = [str(e) for e in (evidence.get("dep_endpoints") or [])]
    new_r3: dict[str, Any] = {
        **r3,
        "stage": stage,
        "signal": signal,
        "job_name": payload.get("job_name") or r3.get("job_name"),
        "component": payload.get("component") or r3.get("component"),
        "first_seen_at": r3.get("first_seen_at") or payload.get("at") or _now_iso(),
        "last_signal_at": payload.get("at") or payload.get("recovered_at") or _now_iso(),
        "diag_at": _now_iso(),
        "diag_source": diag.get("source"),
        "root_cause_class": rc,
        "confidence": diag.get("confidence"),
        "reasoning": diag.get("reasoning"),
        "prescriptions": diag.get("prescriptions"),
        "executed": executed or r3.get("executed") or [],
        "planned": planned,
        "suggestions": suggestions,
        "dep_endpoints": dep_endpoints,
        "repair_rounds": rounds,
        "repair_mode_at_diag": mode,
        "evidence": evidence,
    }

    # 诊断卡（总发；先存后发）
    await enqueue_effect(
        session, "dm_admin",
        {"text": cards.build_diagnosis_card(new_r3, evidence, repair_mode=mode)},
        dedupe_key=f"r3:diag:{task_id}:{new_r3['diag_at'][:19]}",
    )
    if stage == signals.R3_STAGE_NEEDS_HUMAN and escalate_guidance:
        new_r3["escalate_guidance"] = escalate_guidance
        await enqueue_effect(
            session, "dm_admin",
            {"text": cards.build_escalation_card(new_r3, escalate_guidance)},
            dedupe_key=f"r3:escalate:{task_id}:{new_r3['diag_at'][:19]}",
        )

    logger.info(
        "R3 诊断完成: task=%s signal=%s rc=%s(%s) 执行=%s 建议=%d 阶段=%s",
        task_id, signal, rc, diag.get("source"), executed or "无", len(suggestions), stage,
    )
    return Report(
        kind="blocked" if stage == signals.R3_STAGE_NEEDS_HUMAN else "progress",
        note=f"R3 诊断：{rc}（{diag.get('source')}），动作 {'、'.join(executed) or '无'}",
        output={"r3": new_r3},
    )


def _human_guidance(rc: str, evidence: dict[str, Any]) -> str:
    if rc == "quota_exhausted":
        return "API 余额/配额耗尽：请充值对应账号（充值后探活将自动确认恢复并收口）"
    if rc == "config_error":
        return "配置错误：请核对 app_config / 环境变量后人工处置"
    if rc == "code_bug":
        return "疑似代码缺陷：请开发排查（工单留有证据快照）"
    return "证据不足以归因，请人工排查（工单留有证据快照）"


# ═══════════════════════════════════════════════════════════════
# 收口核对（recovered / dep_recovered / missed / repair_done / retry）
# ═══════════════════════════════════════════════════════════════


async def _phase_verify(
    session: Any, task_id: uuid.UUID, r3: dict[str, Any], payload: dict[str, Any],
) -> Report:
    signal = str(r3.get("signal") or "")
    if signal == signals.SIGNAL_JOB_FAILED:
        return await _verify_job(session, task_id, r3)
    if signal in (signals.SIGNAL_RAG_DEGRADED,):
        return await _verify_rag(session, task_id, r3)
    if signal == signals.SIGNAL_PARKED:
        return await _verify_parked(session, task_id, r3)
    if signal == signals.SIGNAL_DEADLETTER:
        return await _verify_deadletter(session, task_id, r3)
    if signal == signals.SIGNAL_BATCH:
        return await _verify_batch(session, task_id, r3)
    return await _verify_generic(session, task_id, r3)


async def _set_stage_enqueue_closure(
    session: Any, task_id: uuid.UUID, r3: dict[str, Any], *, note: str,
) -> Report:
    """全绿收口：入队 r3_closure_card（双条件②；发送成功才关单）。"""
    from app.platform.superagent.models import AgentEffect
    from app.platform.superagent.effects import enqueue_effect

    dedupe = f"r3:closure:{task_id}"
    existing = (
        await session.execute(
            select(AgentEffect.id).where(
                AgentEffect.kind == "r3_closure_card",
                AgentEffect.dedupe_key == dedupe,
                AgentEffect.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        await enqueue_effect(
            session, "r3_closure_card",
            {"task_id": str(task_id), "text": cards.build_closure_card(r3)},
            dedupe_key=dedupe,
        )
    new_r3 = {**r3, "stage": signals.R3_STAGE_VERIFY_WAIT}
    return Report(kind="progress", note=note, output={"r3": new_r3})


async def _needs_human(
    session: Any, task_id: uuid.UUID, r3: dict[str, Any], guidance: str,
) -> Report:
    """升级人工（升级卡 🔴；处置后恢复信号可复活重入收口）。"""
    from app.platform.superagent.effects import enqueue_effect

    stamp = _now_iso()[:19]
    new_r3 = {**r3, "stage": signals.R3_STAGE_NEEDS_HUMAN, "escalate_guidance": guidance}
    await enqueue_effect(
        session, "dm_admin",
        {"text": cards.build_escalation_card(new_r3, guidance)},
        dedupe_key=f"r3:escalate:{task_id}:{stamp}",
    )
    return Report(
        kind="blocked", note=f"R3 需人工：{guidance[:120]}", output={"r3": new_r3},
    )


async def _verify_job(session: Any, task_id: uuid.UUID, r3: dict[str, Any]) -> Report:
    """job 工单收口核对：健康 ∧ 漏审日全终态 → 收口。"""
    from app.modules.safety.models.msds import SchedulerJobRun

    job = str(r3.get("job_name") or "")
    row = (
        await session.execute(
            select(SchedulerJobRun).where(SchedulerJobRun.job_name == job)
        )
    ).scalar_one_or_none()
    healthy = row is None or row.status != "failed"

    missed, overflow = await backfill.determine_missed_days(session, job)
    covered = await backfill.backfilled_run_days(session, job)
    uncovered = [d for d in missed if d not in covered["pending"] | covered["done"]]

    if overflow:
        r3 = {**r3, "backfill_overflow": True}

    if uncovered:
        if job not in backfill.BACKFILL_ADAPTERS:
            return await _needs_human(
                session, task_id, r3,
                f"任务「{job}」存在 {len(uncovered)} 个漏审日但无补跑 adapter，需人工补跑："
                f"{'、'.join(uncovered)}",
            )
        ok, reason = actions.check_gates("job_backfill", args={"run_days": uncovered})
        rounds = int(r3.get("repair_rounds") or 0)
        if not ok and reason.startswith("gate2"):
            return await _needs_human(
                session, task_id, r3,
                f"漏审日待补跑（{ '、'.join(uncovered) }）——修复层 {config.repair_mode()} 模式"
                "不执行 job_backfill，请人工补跑或翻 auto 后重试",
            )
        if rounds >= config.max_repair_rounds():
            return await _needs_human(
                session, task_id, r3,
                f"漏审日补跑达轮上限（{config.max_repair_rounds()}），需人工：{'、'.join(uncovered)}",
            )
        if not ok:
            return await _needs_human(session, task_id, r3, f"job_backfill 未过闸（{reason}）")
        from app.platform.superagent.effects import enqueue_effect

        key_days = ",".join(uncovered)
        await enqueue_effect(
            session, "r3_repair",
            {"task_id": str(task_id), "action": "job_backfill", "job_name": job,
             "run_days": uncovered, "round": rounds + 1, "subject": job},
            dedupe_key=f"r3:jobbackfill:{job}:{key_days}",
        )
        new_r3 = {**r3, "stage": signals.R3_STAGE_REPAIRING,
                  "repair_rounds": rounds + 1,
                  "missed_days": missed,
                  "backfill_summary": f"补跑入队：{'、'.join(uncovered)}"}
        return Report(
            kind="progress", note=f"漏审日补跑已入队：{key_days}", output={"r3": new_r3},
        )

    if missed and not set(missed) <= covered["done"]:
        # 补跑 effect 仍在 pending（repair_done 会回注重核对）
        new_r3 = {**r3, "stage": signals.R3_STAGE_VERIFY_WAIT, "missed_days": missed}
        return Report(kind="progress", note="漏审日补跑执行中，等待逐日结果",
                      output={"r3": new_r3})

    if not healthy:
        new_r3 = {**r3, "stage": signals.R3_STAGE_VERIFY_WAIT,
                  "missed_days": missed,
                  "backfill_summary": r3.get("backfill_summary") or (
                      f"漏审日已补齐：{'、'.join(missed)}" if missed else "")}
        return Report(
            kind="progress",
            note="漏审日已终态；等当日定时任务成功（recovered trigger）后收口",
            output={"r3": new_r3},
        )

    return await _set_stage_enqueue_closure(
        session, task_id, r3, note=f"job「{job}」恢复已验证，漏审日全终态，收口",
    )


async def _verify_rag(session: Any, task_id: uuid.UUID, r3: dict[str, Any]) -> Report:
    """rag 工单收口核对：原始探针复测全绿 → 收口（复测仍故障=继续等）。"""
    rag = await diagnosis._probe_rag_raw()
    healthy = rag.get("embedding_ok") and (
        rag.get("ragplus") is None or bool((rag.get("ragplus") or {}).get("ok"))
    )
    if not healthy:
        new_r3 = {**r3, "stage": signals.R3_STAGE_VERIFY_WAIT,
                  "evidence": {**(r3.get("evidence") or {}), "rag_recheck": rag}}
        return Report(kind="progress", note="RAG 复测仍故障，继续等待恢复",
                      output={"r3": new_r3})
    return await _set_stage_enqueue_closure(session, task_id, r3, note="RAG 探针复测全绿，收口")


async def _verify_parked(session: Any, task_id: uuid.UUID, r3: dict[str, Any]) -> Report:
    """parked 工单收口核对：组件无 parked 残留 → 收口；有残留按轮次 unpark/升级。"""
    from app.platform.superagent.models import AgentEffect

    component = str(r3.get("component") or "")
    rows = (
        await session.execute(
            select(AgentEffect.id).where(
                AgentEffect.status == "failed", AgentEffect.kind == component,
            )
        )
    ).scalars().all()
    if not rows:
        return await _set_stage_enqueue_closure(
            session, task_id, r3, note=f"组件 {component} 无 parked 残留，收口",
        )
    rounds = int(r3.get("repair_rounds") or 0)
    ok, reason = actions.check_gates("effects_unpark")
    if ok and rounds < config.max_repair_rounds():
        from app.platform.superagent.effects import enqueue_effect

        await enqueue_effect(
            session, "r3_repair",
            {"task_id": str(task_id), "action": "effects_unpark", "component": component,
             "round": rounds + 1, "subject": component},
            dedupe_key=f"r3:repair:{task_id}:effects_unpark:{rounds + 1}",
        )
        new_r3 = {**r3, "stage": signals.R3_STAGE_REPAIRING, "repair_rounds": rounds + 1}
        return Report(kind="progress", note=f"仍 parked {len(rows)} 条，再次 unpark",
                      output={"r3": new_r3})
    return await _needs_human(
        session, task_id, r3,
        f"组件 {component} 仍有 {len(rows)} 条 parked 未清（{reason if not ok else '轮上限'}），需人工",
    )


async def _verify_deadletter(session: Any, task_id: uuid.UUID, r3: dict[str, Any]) -> Report:
    """死信工单收口核对：清零 → 收口；未清按闸重灌/升级。"""
    try:
        from app.modules.safety.service.hazard_direct.failure_ledger import (
            list_dead_letters,
        )

        dead = await list_dead_letters(limit=50)
    except Exception:  # noqa: BLE001 — fail-open：Redis 不可达无法核对，等下轮
        new_r3 = {**r3, "stage": signals.R3_STAGE_VERIFY_WAIT}
        return Report(kind="progress", note="死信核对 fail-open（Redis 不可达），等下轮",
                      output={"r3": new_r3})
    if not dead:
        return await _set_stage_enqueue_closure(session, task_id, r3, note="死信已清零，收口")
    rounds = int(r3.get("repair_rounds") or 0)
    ok, reason = actions.check_gates("hazard_dead_letter_rerun")
    if ok and rounds < config.max_repair_rounds():
        from app.platform.superagent.effects import enqueue_effect

        await enqueue_effect(
            session, "r3_repair",
            {"task_id": str(task_id), "action": "hazard_dead_letter_rerun",
             "round": rounds + 1, "subject": "hazard_ai"},
            dedupe_key=f"r3:repair:{task_id}:dead_letter_rerun:{rounds + 1}",
        )
        new_r3 = {**r3, "stage": signals.R3_STAGE_REPAIRING, "repair_rounds": rounds + 1}
        return Report(kind="progress", note=f"死信 {len(dead)} 条，重灌已入队",
                      output={"r3": new_r3})
    return await _needs_human(
        session, task_id, r3,
        f"死信 {len(dead)} 条未清（{reason if not ok else '轮上限'}），需人工重灌",
    )


async def _verify_batch(session: Any, task_id: uuid.UUID, r3: dict[str, Any]) -> Report:
    """聚合工单收口核对：逐项按类型核对，全清 → 收口。"""
    evidence = r3.get("evidence") or {}
    pending: list[str] = []
    for item in (evidence.get("items") or []):
        item_signal = str(item.get("signal") or "")
        if item_signal == signals.SIGNAL_JOB_FAILED:
            from app.modules.safety.models.msds import SchedulerJobRun

            job = str(item.get("job_name") or "")
            row = (
                await session.execute(
                    select(SchedulerJobRun).where(SchedulerJobRun.job_name == job)
                )
            ).scalar_one_or_none()
            if row is not None and row.status == "failed":
                pending.append(f"job:{job}")
        elif item_signal == signals.SIGNAL_PARKED:
            from app.platform.superagent.models import AgentEffect

            n = (
                await session.execute(
                    select(AgentEffect.id).where(
                        AgentEffect.status == "failed",
                        AgentEffect.kind == str(item.get("component") or ""),
                    )
                )
            ).scalars().all()
            if n:
                pending.append(f"parked:{item.get('component')}")
        elif item_signal == signals.SIGNAL_DEADLETTER:
            try:
                from app.modules.safety.service.hazard_direct.failure_ledger import (
                    list_dead_letters,
                )

                if await list_dead_letters(limit=10):
                    pending.append("deadletter")
            except Exception:  # noqa: BLE001 — fail-open
                pending.append("deadletter:?")
    if pending:
        new_r3 = {**r3, "stage": signals.R3_STAGE_VERIFY_WAIT,
                  "batch_pending": pending}
        return Report(
            kind="progress",
            note=f"聚合单仍有未清项：{'、'.join(pending[:5])}，继续等待",
            output={"r3": new_r3},
        )
    return await _set_stage_enqueue_closure(session, task_id, r3, note="聚合单全部子项已清，收口")


async def _verify_generic(session: Any, task_id: uuid.UUID, r3: dict[str, Any]) -> Report:
    """兜底核对（未知信号形态）：仅当有恢复类输入才收口。"""
    return await _set_stage_enqueue_closure(session, task_id, r3, note="恢复信号已核对，收口")
