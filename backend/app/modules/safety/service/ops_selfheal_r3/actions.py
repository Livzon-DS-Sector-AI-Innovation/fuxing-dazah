"""R3 修复动作 —— 注册表 + 四道闸 + r3_repair/r3_closure_card effect handlers。

四道闸（§4.3 C，程序校验，LLM 输出永不直接执行）：
① ``SAFETY_R3_ALLOWED_ACTIONS`` 白名单 → ② repair_mode（L1/L2 须 auto；
L2 一期永不自动=建议）→ ③ 前置条件 → ④ 日上限。

- L0（notify_enriched=诊断卡本体、rag_recheck=只读探针）总放行不设限；
- L1 一期即刻：effects_unpark / job_backfill（作业票 adapter）；
  hazard_dead_letter_rerun / hazard_stale_rerun 已实现但不预置白名单
  （依赖 P3-2 真机 --confirm 验证已过，白名单加入是人工动作）；
- L2 job_window_extend 只上卡建议；L3（游标重置/删数据/写 Bitable/重启
  进程）永不注册（红线）。

执行通道：全部 ``enqueue_effect(kind=r3_repair)`` 先存后做（禁裸
asyncio.create_task）；handler 完成后自行入队修复结果卡并向工单重投
``repair_done`` system input（驱动下一轮收口核对）。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.modules.safety.service.ops_selfheal_r3 import backfill, cards, config, signals

logger = logging.getLogger(__name__)

#: 每组件 unpark 日上限（设计 §4.4）
UNPARK_DAILY_CAP = 3

#: 补跑每事件漏审日上限（拍板 #4）
BACKFILL_DAY_CAP = 5


@dataclass(frozen=True)
class ActionDef:
    """动作元数据（级别/日上限/描述；前置条件在 gate ③ 逐动作实现）。"""

    kind: str
    level: int          # 0=只读/通知 1=本地修复 2=敏感（永不自动）
    desc: str


ACTION_DEFS: dict[str, ActionDef] = {
    "notify_enriched": ActionDef("notify_enriched", 0, "诊断报告卡（总发）"),
    "rag_recheck": ActionDef("rag_recheck", 0, "立即跑一轮 RAG 原始探针刷新证据"),
    "effects_unpark": ActionDef("effects_unpark", 1, "parked effect 重置 pending（attempts 清零）"),
    "job_backfill": ActionDef("job_backfill", 1, "漏审日逐日补跑（一期 adapter=作业票审核）"),
    "hazard_dead_letter_rerun": ActionDef("hazard_dead_letter_rerun", 1, "死信重灌（rerun 核心）"),
    "hazard_stale_rerun": ActionDef("hazard_stale_rerun", 1, "stale 按需重算（rerun 核心）"),
    "job_window_extend": ActionDef("job_window_extend", 2, "延长当日补发窗口（仅卡上建议，人工执行）"),
    # L3（cursor_reset/删数据/写 Bitable/重启进程）永不注册——红线
}


def check_gates(action: str, *, args: dict[str, Any] | None = None) -> tuple[bool, str]:
    """四道闸校验（纯程序；返回 (是否放行, 原因)）。

    ① 白名单 → ② repair_mode（L1/L2 须 auto；L2 恒拒=建议）→ ③ 前置 → ④ 日上限。
    """
    args = args or {}
    def_ = ACTION_DEFS.get(action)
    if def_ is None:
        return False, f"unknown_action:{action}"
    # ① 白名单
    if action not in config.allowed_actions():
        return False, "gate1_not_in_whitelist"
    # ② 模式闸（L0 总放行；L1 须 auto；L2 一期永不自动）
    if def_.level == 2:
        return False, "gate2_l2_manual_only"
    if def_.level >= 1 and config.repair_mode() != "auto":
        return False, f"gate2_repair_mode_{config.repair_mode()}"
    # ③ 前置条件（同步可判部分；异步前置在 executor 路径内查库判定）
    if action == "job_backfill":
        days = args.get("run_days") or []
        if not days:
            return False, "gate3_no_missed_days"
        if len(days) > BACKFILL_DAY_CAP:
            return False, "gate3_over_day_cap"
    # ④ 日上限在 handler/入队侧按当日 agent_effects 计数执行（见 _daily_count）
    return True, "ok"


# ═══════════════════════════════════════════════════════════════
# effect handlers（先存后做的「做」侧）
# ═══════════════════════════════════════════════════════════════


async def _enqueue_dm_card(session: Any, text: str, dedupe_key: str) -> None:
    """诊断/结果/升级卡：dm_admin effect 先存后发（§4.6 通道）。"""
    from app.platform.superagent.effects import enqueue_effect

    await enqueue_effect(session, "dm_admin", {"text": text}, dedupe_key=dedupe_key)


async def _notify_repair_done(session: Any, task_id: str, payload: dict[str, Any]) -> None:
    """向工单重投 repair_done system input（驱动下轮收口核对；幂等由读侧消费保证）。"""
    from app.platform.superagent.models import AgentInput

    session.add(AgentInput(
        task_id=uuid.UUID(task_id), kind="system",
        payload={"type": "repair_done", **payload},
        delivered_at=datetime.now(UTC),
    ))


async def _finish_repair(
    session: Any, *, task_id: str, action: str, text: str,
    round_no: Any, suffix: str, notify: dict[str, Any] | None,
) -> None:
    """修复收尾样板（四个 _do_* 共用）：结果卡 + repair_done 回注 + commit。"""
    await _enqueue_dm_card(
        session, text,
        dedupe_key=f"r3:repaircard:{task_id}:{round_no}:{suffix}",
    )
    if task_id and notify is not None:
        await _notify_repair_done(session, task_id, notify)
    await session.commit()


async def _do_effects_unpark(payload: dict[str, Any]) -> None:
    from app.core.database import async_session_factory
    from app.platform.superagent.models import AgentEffect

    task_id = str(payload.get("task_id") or "")
    component = str(payload.get("component") or "")
    results: list[dict[str, Any]] = []
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(AgentEffect).where(
                    AgentEffect.status == "failed",
                    AgentEffect.kind == component,
                )
            )
        ).scalars().all()
        # 日上限④二次钳制（每组件日 3 次；按当日该组件已 unpark 的修复 effect 计）
        already = await _daily_unpark_count(session, component)
        for row in rows[: max(0, UNPARK_DAILY_CAP - already)]:
            row.status = "pending"
            row.attempts = 0
            row.next_due_at = datetime.now(UTC)
            results.append({
                "ok": True, "label": f"{row.kind}:{row.dedupe_key[:40]}", "detail": "已重置 pending",
            })
        skipped = len(rows) - len(results)
        if skipped > 0:
            results.append({
                "ok": False, "label": f"{component}（超出日上限 {UNPARK_DAILY_CAP}）",
                "detail": f"跳过 {skipped} 条", "will_retry": False,
            })
        await _finish_repair(
            session, task_id=task_id, action="effects_unpark",
            text=cards.build_repair_result_card("effects_unpark", results),
            round_no=payload.get("round"), suffix="unpark",
            notify={"action": "effects_unpark", "component": component,
                    "unparked": len(results), "skipped": skipped},
        )
    logger.info("R3 effects_unpark: component=%s unparked=%d", component, len(results))


async def _daily_unpark_count(session: Any, component: str) -> int:
    """当日该组件已被 unpark 的次数（成功 done 的 r3_repair effect 计数）。"""
    return await _daily_done_count(
        session, "effects_unpark", component_key=component,
    )


async def _daily_done_count(
    session: Any, action: str, *, component_key: str | None = None,
) -> int:
    """当日某 action 已成功执行的 r3_repair effect 数（日「1 次」上限口径）。

    component_key 传入时按 payload.component 收窄（unpark 每组件维度）；
    缺省为全局动作维度（死信/stale 重灌日 1 次）。
    """
    from app.platform.superagent.models import AgentEffect

    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        await session.execute(
            select(AgentEffect).where(
                AgentEffect.kind == "r3_repair",
                AgentEffect.status == "done",
                AgentEffect.created_at >= day_start,
            )
        )
    ).scalars().all()
    return sum(
        1 for r in rows
        if (r.payload or {}).get("action") == action
        and (component_key is None or (r.payload or {}).get("component") == component_key)
    )


async def _do_job_backfill(payload: dict[str, Any]) -> None:
    """漏审日逐日补跑（作业票 adapter；逐日执行逐日结果，失败重试 1 次再败记录继续）。"""
    from app.core.database import async_session_factory

    task_id = str(payload.get("task_id") or "")
    job_name = str(payload.get("job_name") or "")
    run_days = [str(d) for d in (payload.get("run_days") or [])][:BACKFILL_DAY_CAP]
    results = await backfill.backfill_workticket_days(run_days)

    async with async_session_factory() as session:
        await _finish_repair(
            session, task_id=task_id, action="job_backfill",
            text=cards.build_repair_result_card(
                f"job_backfill（{job_name}）",
                [
                    {
                        "ok": r["status"] == "done",
                        "label": f"漏审日 {r['run_day']}（审核 {r['review_date']}）",
                        "detail": r.get("detail") or r.get("error") or "",
                        "will_retry": False,
                    }
                    for r in results
                ],
            ),
            round_no=payload.get("round"), suffix="backfill",
            notify={"action": "job_backfill", "job_name": job_name,
                    "days": {r["run_day"]: r["status"] for r in results}},
        )
    logger.info("R3 job_backfill: job=%s days=%s", job_name, run_days)


async def _do_dead_letter_rerun(payload: dict[str, Any]) -> None:
    """死信重灌（hazard_direct/rerun 核心；日 1 次 ≤ min(50, DAILY_RERUN_CAP) 条）。"""
    from app.core.database import async_session_factory

    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.hazard_direct.failure_ledger import (
        list_dead_letters,
    )
    from app.modules.safety.service.hazard_direct.rerun import rerun_record

    task_id = str(payload.get("task_id") or "")
    cap = min(50, config.daily_rerun_cap())
    results: list[dict[str, Any]] = []
    async with async_session_factory() as session:
        # 日上限④：死信重灌日 1 次（当日已有成功重灌 → 跳过并注明）
        if await _daily_done_count(session, "hazard_dead_letter_rerun") >= 1:
            results.append({
                "ok": False, "label": "hazard_dead_letter_rerun（日 1 次上限）",
                "detail": "当日已重灌过，跳过（下轮死信扫描仍积压再判）", "will_retry": False,
            })
            text = cards.build_repair_result_card("hazard_dead_letter_rerun", results)
        else:
            dead = await list_dead_letters(limit=cap)
            client = SafetyBitableClient()
            try:
                for item in dead[:cap]:
                    rid = str(item.get("record_id") or "")
                    if not rid:
                        continue
                    try:
                        status, detail = await rerun_record(client, rid, confirm=True)
                        ok = status == "done"
                        if ok:
                            from app.modules.safety.service.hazard_direct import failure_ledger

                            await failure_ledger.record_success(rid)
                    except Exception as exc:  # noqa: BLE001 — 逐条隔离
                        status, detail, ok = "failed", f"{type(exc).__name__}: {exc}"[:200], False
                    results.append({
                        "ok": ok, "label": rid, "detail": detail,
                        "will_retry": status == "failed",
                    })
            finally:
                await client.close()
            text = cards.build_repair_result_card("hazard_dead_letter_rerun", results)
        await _finish_repair(
            session, task_id=task_id, action="hazard_dead_letter_rerun", text=text,
            round_no=payload.get("round"), suffix="deadletter",
            notify={"action": "hazard_dead_letter_rerun",
                    "done": sum(1 for r in results if r["ok"]),
                    "failed": sum(1 for r in results if not r["ok"])},
        )
    logger.info("R3 dead_letter_rerun: %d 项（成功 %d）",
                len(results), sum(1 for r in results if r["ok"]))


async def _do_stale_rerun(payload: dict[str, Any]) -> None:
    """stale 按需重算（rerun.stale_rerun 核心；ai_edited 保护由核心保证）。"""
    from app.core.database import async_session_factory

    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.hazard_direct.rerun import stale_rerun

    task_id = str(payload.get("task_id") or "")
    limit = min(50, config.daily_rerun_cap())
    async with async_session_factory() as session:
        # 日上限④：stale 重算日 1 次（当日已有成功重算 → 跳过并注明）
        if await _daily_done_count(session, "hazard_stale_rerun") >= 1:
            report = None
            results: list[dict[str, Any]] = [{
                "ok": False, "label": "hazard_stale_rerun（日 1 次上限）",
                "detail": "当日已重算过，跳过", "will_retry": False,
            }]
            text = cards.build_repair_result_card("hazard_stale_rerun", results)
            done_n = failed_n = protected_n = 0
        else:
            client = SafetyBitableClient()
            try:
                records = await _stale_candidates(client, limit)
                report = await stale_rerun(
                    client, records, limit=limit, registry_cap=limit, confirm=True,
                )
            finally:
                await client.close()
            results = [
                {"ok": True, "label": rid, "detail": detail}
                for rid, detail in (report.details or {}).items()
            ][:50]
            text = cards.build_repair_result_card(
                "hazard_stale_rerun",
                [
                    *results,
                    * [{"ok": False, "label": f"保护（ai_edited）{rid}", "detail": "永不重算"}
                       for rid in (report.protected or [])[:10]],
                ],
            )
            done_n, failed_n, protected_n = report.done, report.failed, len(report.protected or [])
        await _finish_repair(
            session, task_id=task_id, action="hazard_stale_rerun", text=text,
            round_no=payload.get("round"), suffix="stale",
            notify={"action": "hazard_stale_rerun", "done": done_n, "failed": failed_n},
        )
    logger.info("R3 stale_rerun: done=%d failed=%d protected=%d",
                done_n, failed_n, protected_n)


async def _stale_candidates(client: Any, limit: int) -> list[dict[str, Any]]:
    """stale input_changed 候选拉取（督办 A∪B 活跃集 = stale 扫描的输入面）。"""
    from app.modules.safety.service.hazard_direct import stale_state
    from app.modules.safety.service.hazard_direct.supervision import _fetch_targets

    records = await _fetch_targets(client)
    scan = await stale_state.scan_records(records or [])
    ids = [c.record_id for c in scan.input_changed][:limit]
    by_id = {r.get("record_id"): r for r in (records or [])}
    return [by_id[rid] for rid in ids if rid in by_id]


async def r3_repair_handler(payload: dict[str, Any]) -> None:
    """r3_repair effect 总分发（执行侧四道闸已过，此处按 action 派发）。"""
    action = str(payload.get("action") or "")
    if action == "effects_unpark":
        await _do_effects_unpark(payload)
    elif action == "job_backfill":
        await _do_job_backfill(payload)
    elif action == "hazard_dead_letter_rerun":
        await _do_dead_letter_rerun(payload)
    elif action == "hazard_stale_rerun":
        await _do_stale_rerun(payload)
    else:
        raise ValueError(f"r3_repair: 未实现动作 {action}")


async def r3_closure_card_handler(payload: dict[str, Any]) -> None:
    """收口卡：先发 DM，发送成功才关单（双条件②；失败 raise 走退避重试，
    工单保持 open 下轮重发——§4.5）。

    顺序语义：发送失败 → 本行退避重试（不关单）；发送成功后关单失败（极小
    概率 DB 抖动）→ 重试会重发一次卡（重复卡优于「已关单未通知」）。
    """
    from sqlalchemy import select as _select

    from app.core.config import get_settings
    from app.core.database import async_session_factory
    from app.platform.superagent.models import AgentTask

    task_id = uuid.UUID(str(payload.get("task_id") or ""))
    text = str(payload.get("text") or "")

    recipients = [
        x.strip()
        for x in (get_settings().SUPERAGENT_ADMIN_OPEN_IDS or "").split(",")
        if x.strip()
    ]
    if not recipients:
        # 双条件②红线：无收件人 = 通知无法送达 = 不关单（走 effects 退避，配好后重发）
        raise RuntimeError(
            "R3 收口卡无收件人（SUPERAGENT_ADMIN_OPEN_IDS 空），工单保持 open 不关单"
        )
    from app.modules.safety.superagent_bridge import _send_admin_dm

    failed = [r for r in recipients if not await _send_admin_dm(r, text)]
    if failed:
        raise RuntimeError(f"R3 收口卡发送失败（工单保持 open）: {failed}")

    async with async_session_factory() as session:
        task = (
            await session.execute(
                _select(AgentTask).where(AgentTask.id == task_id)
            )
        ).scalar_one_or_none()
        if task is not None and task.status == "open":
            task.status = "ended"
            task.outcome = "closed"
            task.ended_at = datetime.now(UTC)
            facts = dict(task.stage_facts or {})
            facts["r3"] = {**(facts.get("r3") or {}), "stage": "closed",
                           "closed_at": datetime.now(UTC).isoformat()}
            task.stage_facts = facts
        await session.commit()
    logger.info("R3 收口卡送达并关单: task=%s", task_id)
