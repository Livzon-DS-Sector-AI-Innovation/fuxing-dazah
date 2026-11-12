"""OpsScanSource —— R3 运维信号扫描源（kind=ops_scan，interval 门控）。

设计 §4.1：五类结构化信号全部只读扫描，Trigger 幂等（external_id 内嵌
状态），单轮故障类 trigger ≤5 条超限聚合。R1 cron_scan 的 interval 变体：

- 门控：``last_tick`` 读位 + ``due_fire_times``（interval=SAFETY_R3_SCAN_
  INTERVAL_SECONDS 每轮热读，首见 rebase 不回溯）；
- job 信号：``scheduler_job_runs`` failed 且 attempt_count≥3（对齐
  ALERT_AFTER_FAILURES）→ ``ops:job:<job>:<fired_date>:failed``；行翻
  success/no_source → 对读位中每个未恢复 failed_date 发 ``:recovered``；
  窗口耗尽仍 failed → ``:missed``（漏审定局，补跑与收口的确定性输入）；
- parked：``agent_effects`` status=failed（park 语义）按 kind 分组，排除
  R3 自身 kinds（自愈不自我修复，§13）；每组件每日一条；
- dead letter：Redis 计数 fail-open（不可达跳过本轮该项，不算故障）；
- 依赖探测：open 且 root_cause=upstream_outage 的 R3 工单，逐端点探测，
  读位记录不可达首见，不可达→可达翻转发 ``ops:dep:<task>:<hash>:recovered``
  回注原工单线程。

job/dep 翻转状态走读位（``job_state``/``dep_state``），与所覆盖 Trigger
同事务推进（底座不变量：crash → 重扫同批 → duplicate，不重放不漏单）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date as date_type
from datetime import datetime, time as dtime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from app.modules.safety.service.ops_selfheal_r3 import config, signals
from app.platform.scheduler import ScheduleConfig
from app.platform.superagent.models import AgentSource
from app.platform.superagent.sources import (
    DEFAULT_MAX_CATCHUP_SECONDS,
    PollResult,
    Source,
    TriggerDraft,
    due_fire_times,
)

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Shanghai")

#: 与既有告警阈值对齐（scheduler.ALERT_AFTER_FAILURES；不直接 import 防热区耦合）
JOB_ALERT_AFTER_FAILURES = 3

#: R3 自身 effect kinds（unpark 排除集：自愈不自我修复）
R3_OWN_EFFECT_KINDS = frozenset({"r3_repair", "r3_closure_card"})

#: 单轮故障类 trigger 上限（防风暴；超限聚合成一条批量 trigger）
SCAN_TRIGGER_CAP = 5

#: 读位中每 job 保留的日期数上限（防 JSONB 无界增长）
_JOB_STATE_DATE_CAP = 30

#: 依赖探测上限（端点/工单；诊断侧已限每工单 ≤5 端点）
_DEP_PROBE_TASK_CAP = 10


def _today() -> date_type:
    return datetime.now(_TZ).date()


def _schedule_jobs_index() -> dict[str, dict[str, Any]]:
    """SCHEDULED_JOBS name → 声明行（窗口/schedule 信息；DB 覆写不进窗口口径）。"""
    from app.modules.safety.scheduler import SCHEDULED_JOBS

    return {str(j.get("name")): j for j in SCHEDULED_JOBS}


def job_window_end(job_name: str, day: date_type) -> datetime:
    """D 日补发窗口截止（北京时间；未配置按当天 23:59）。"""
    job = _schedule_jobs_index().get(job_name) or {}
    hour = job.get("retry_until_hour")
    minute = job.get("retry_until_minute")
    return datetime.combine(
        day, dtime(int(hour if hour is not None else 23),
                   int(minute if minute is not None else 59)),
        tzinfo=_TZ,
    )


def window_exhausted(job_name: str, day: date_type, *, now: datetime | None = None) -> bool:
    """D 日补发窗口是否已耗尽（当日重试中=未耗尽，不计漏审）。"""
    now = now or datetime.now(_TZ)
    return now > job_window_end(job_name, day)


# ── 依赖探测（纯网络探测，供扫描与诊断共用）──


async def probe_endpoint(endpoint: str, *, timeout: float = 4.0) -> bool:
    """探测端点可达性：http(s) URL 任意 HTTP 响应=可达；host:port TCP 连通=可达。"""
    try:
        if endpoint.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                try:
                    await client.head(endpoint)
                except httpx.HTTPStatusError:
                    return True  # 有响应即服务在（4xx/5xx 也是可达）
            return True
        host, _, port = endpoint.partition(":")
        kwargs: dict[str, Any] = {}
        if port.isdigit():
            kwargs["port"] = int(port)
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, **kwargs), timeout=timeout,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001 — 关闭残留不影响判定
            pass
        return True
    except Exception:  # noqa: BLE001 — 探测任何异常都=不可达
        return False


def _prune_job_state(job_state: dict[str, Any]) -> dict[str, Any]:
    """每 job 日期清单裁剪到最近 30 条（保留日期序）。"""
    out: dict[str, Any] = {}
    for job, st in job_state.items():
        keep = dict(st or {})
        for key in ("failed_dates", "recovered", "missed"):
            dates = sorted(keep.get(key) or [])
            keep[key] = dates[-_JOB_STATE_DATE_CAP:]
        out[job] = keep
    return out


async def _scan_jobs(session: Any, job_state: dict[str, Any]) -> list[TriggerDraft]:
    """job 信号三态：failed（新失败日）/ recovered（行转健康）/ missed（窗口耗尽）。"""
    from app.modules.safety.models.msds import SchedulerJobRun

    rows = (
        await session.execute(select(SchedulerJobRun))
    ).scalars().all()
    today = _today()
    now = datetime.now(_TZ)
    sched = _schedule_jobs_index()
    drafts: list[TriggerDraft] = []

    for row in rows:
        st = job_state.setdefault(row.job_name, {"failed_dates": [], "recovered": [], "missed": []})
        failed: list[str] = list(st.get("failed_dates") or [])
        recovered: list[str] = list(st.get("recovered") or [])
        missed: list[str] = list(st.get("missed") or [])
        day_iso = row.fired_date.isoformat() if isinstance(row.fired_date, date_type) else str(row.fired_date)
        job_cfg = sched.get(row.job_name) or {}

        if row.status == "failed" and row.attempt_count >= JOB_ALERT_AFTER_FAILURES:
            if day_iso not in failed:
                failed.append(day_iso)
                drafts.append(TriggerDraft(
                    external_id=signals.job_failed_eid(row.job_name, day_iso),
                    thread_key=signals.job_thread(row.job_name, day_iso),
                    actor={"id": row.job_name, "type": "scheduled_job"},
                    payload={
                        "signal": signals.SIGNAL_JOB_FAILED,
                        "job_name": row.job_name,
                        "fired_date": day_iso,
                        "attempt_count": row.attempt_count,
                        "last_attempt_at": row.last_attempt_at.isoformat()
                        if row.last_attempt_at else None,
                        "alerted": row.alerted,
                        "schedule": {
                            "hour": job_cfg.get("hour"), "minute": job_cfg.get("minute"),
                            "retry_until_hour": job_cfg.get("retry_until_hour"),
                            "retry_until_minute": job_cfg.get("retry_until_minute"),
                        },
                        "channel": {"kind": "ops_job", "job_name": row.job_name},
                    },
                ))
        elif row.status in ("success", "no_source"):
            # 行转健康 → 每个「已发过 failed 且未恢复」的日期各发一条收口信号
            for day in [d for d in failed if d not in recovered]:
                recovered.append(day)
                drafts.append(TriggerDraft(
                    external_id=signals.job_recovered_eid(row.job_name, day),
                    thread_key=signals.job_thread(row.job_name, day),
                    actor={"id": row.job_name, "type": "scheduled_job"},
                    payload={
                        "signal": signals.SIGNAL_JOB_RECOVERED,
                        "job_name": row.job_name,
                        "fired_date": day,
                        "recovered_at": now.isoformat(),
                        "row_status": row.status,
                        "channel": {"kind": "ops_job", "job_name": row.job_name},
                    },
                ))

        # 漏审定局：已发过 failed、窗口已耗尽、仍未恢复且未定局 → 确定性输入
        for day in list(failed):
            if day in recovered or day in missed:
                continue
            try:
                day_date = date_type.fromisoformat(day)
            except ValueError:
                continue
            if day_date < today or window_exhausted(row.job_name, day_date, now=now):
                missed.append(day)
                drafts.append(TriggerDraft(
                    external_id=signals.job_missed_eid(row.job_name, day),
                    thread_key=signals.job_thread(row.job_name, day),
                    actor={"id": row.job_name, "type": "scheduled_job"},
                    payload={
                        "signal": signals.SIGNAL_JOB_MISSED,
                        "job_name": row.job_name,
                        "fired_date": day,
                        "window_exhausted_at": now.isoformat(),
                        "channel": {"kind": "ops_job", "job_name": row.job_name},
                    },
                ))

        st["failed_dates"] = failed
        st["recovered"] = recovered
        st["missed"] = missed
        job_state[row.job_name] = st
    return drafts


async def _scan_parked(session: Any) -> list[TriggerDraft]:
    """parked effects（status=failed 即 park 语义）按 kind 分组，每组件每日一条。"""
    from app.platform.superagent.models import AgentEffect

    rows = (
        await session.execute(
            select(AgentEffect).where(AgentEffect.status == "failed")
        )
    ).scalars().all()
    by_kind: dict[str, list[AgentEffect]] = {}
    for row in rows:
        if row.kind in R3_OWN_EFFECT_KINDS:
            continue  # 自愈自身故障走 effects 健康告警既有通道，不自我修复
        by_kind.setdefault(row.kind, []).append(row)

    today_iso = _today().isoformat()
    drafts: list[TriggerDraft] = []
    for kind, items in sorted(by_kind.items()):
        samples = [
            {
                "effect_id": str(x.id), "dedupe_key": x.dedupe_key,
                "attempts": x.attempts,
                "last_error": (x.last_error or "")[:300] or None,
            }
            for x in items[:5]
        ]
        drafts.append(TriggerDraft(
            external_id=signals.parked_eid(kind, today_iso),
            thread_key=signals.opsmisc_thread(today_iso),
            actor={"id": kind, "type": "effect_kind"},
            payload={
                "signal": signals.SIGNAL_PARKED,
                "component": kind,
                "count": len(items),
                "samples": samples,
                "channel": {"kind": "ops_parked", "component": kind},
            },
        ))
    return drafts


async def _scan_deadletter() -> list[TriggerDraft]:
    """死信计数（fail-open：Redis 不可达跳过本轮，不算故障）。"""
    try:
        from app.modules.safety.service.hazard_direct.failure_ledger import (
            list_dead_letters,
        )

        items = await list_dead_letters(limit=50)
    except Exception:  # noqa: BLE001 — fail-open 红线（§13）
        logger.warning("R3 死信扫描 fail-open 跳过本轮（Redis 不可达？）")
        return []
    if not items:
        return []
    today_iso = _today().isoformat()
    samples = [
        {"record_id": str(x.get("record_id") or ""), "reason": str(x.get("reason") or "")[:200]}
        for x in items[:5] if isinstance(x, dict)
    ]
    return [TriggerDraft(
        external_id=signals.deadletter_eid(today_iso),
        thread_key=signals.opsmisc_thread(today_iso),
        actor={"id": "hazard_ai", "type": "dead_letter"},
        payload={
            "signal": signals.SIGNAL_DEADLETTER,
            "count": len(items),
            "samples": samples,
            "channel": {"kind": "ops_deadletter"},
        },
    )]


async def _scan_dependencies(session: Any, dep_state: dict[str, Any]) -> list[TriggerDraft]:
    """上游依赖探测：open 且 upstream_outage 的工单逐端点探测，翻转回注。

    探测并发（gather + 全局信号量 5）——最坏 10 工单×5 端点全不可达时
    串行可阻塞 poll ~200s，挂住同引擎其他源。
    """
    from app.platform.superagent.models import AgentTask, AgentTaskSubscription

    tasks = (
        await session.execute(
            select(AgentTask).where(
                AgentTask.status == "open",
                AgentTask.executor == "r3_ops_heal",
            )
        )
    ).scalars().all()
    probe_targets: list[tuple[AgentTask, str, str]] = []  # (task, endpoint, thread)
    for task in tasks:
        facts = signals.r3_facts(task.stage_facts)
        if facts.get("root_cause_class") != "upstream_outage":
            continue
        endpoints = [str(e) for e in (facts.get("dep_endpoints") or [])][:5]
        if not endpoints or len(probe_targets) >= _DEP_PROBE_TASK_CAP:
            continue
        thread = (
            await session.execute(
                select(AgentTaskSubscription.thread_key)
                .where(AgentTaskSubscription.task_id == task.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if not thread:
            continue
        for endpoint in endpoints:
            probe_targets.append((task, endpoint, thread))
    if not probe_targets:
        _prune_dep_state(dep_state, tasks)
        return []

    semaphore = asyncio.Semaphore(5)

    async def _probe_one(endpoint: str) -> bool:
        async with semaphore:
            return await probe_endpoint(endpoint)

    reachables = await asyncio.gather(*(
        _probe_one(endpoint) for _task, endpoint, _thread in probe_targets
    ))

    drafts: list[TriggerDraft] = []
    for (task, endpoint, thread), reachable in zip(probe_targets, reachables):
        task_id = str(task.id)
        key = f"{task_id}|{endpoint}"
        if not reachable:
            dep_state.setdefault(key, {"unreachable_at": datetime.now(_TZ).isoformat()})
            continue
        if key not in dep_state:
            continue  # 一直可达（或首见即恢复）——无翻转不触发
        unreachable_since = (dep_state.get(key) or {}).get("unreachable_at")
        del dep_state[key]
        drafts.append(TriggerDraft(
            external_id=signals.dep_recovered_eid(task_id, endpoint),
            thread_key=thread,
            actor={"id": endpoint, "type": "dependency_endpoint"},
            payload={
                "signal": signals.SIGNAL_DEP_RECOVERED,
                "task_id": task_id,
                "endpoint": endpoint,
                "recovered_at": datetime.now(_TZ).isoformat(),
                "unreachable_since": unreachable_since,
                "channel": {"kind": "ops_dep", "task_id": task_id},
            },
        ))
    _prune_dep_state(dep_state, tasks)
    return drafts


def _prune_dep_state(dep_state: dict[str, Any], tasks: list[Any]) -> None:
    """清理已关工单的探测读位（防读位泄漏）。"""
    if not dep_state:
        return
    open_ids = {str(t.id) for t in tasks}
    for key in [k for k in dep_state if k.split("|", 1)[0] not in open_ids]:
        del dep_state[key]


class OpsScanSource(Source):
    """R3 运维信号扫描源（safety 侧定义，SourceRegistry 注册制挂入底座）。

    config 约定（迁移播种）：
    - ``schedule``：兜底 ScheduleConfig（interval 300s；生效值以
      SAFETY_R3_SCAN_INTERVAL_SECONDS 每轮热读为准）
    - ``evaluate``：true=落库后走 Slow Path 研判（开单走 Policy auto）

    读位：``last_tick``（interval 网格）+ ``job_state``（job 三态翻转）+
    ``dep_state``（依赖端点不可达首见）。
    """

    kind = "ops_scan"

    async def poll(
        self,
        session: Any,
        source_row: AgentSource,
        cursors: dict[str, Any],
    ) -> PollResult:
        if not config.ops_enabled():
            return PollResult()  # R3 总闸关：零扫描零读位推进（一键全停）

        cfg = source_row.config or {}
        raw_schedule = dict(cfg.get("schedule") or {})
        raw_schedule["strategy"] = "interval"
        raw_schedule["interval_seconds"] = config.scan_interval_seconds()
        schedule = ScheduleConfig(**raw_schedule)
        now = datetime.now(_TZ)
        max_catchup = int(cfg.get("max_catchup_seconds", DEFAULT_MAX_CATCHUP_SECONDS))

        # ── interval 门控（语义与 CronTickSource/R1 cron_scan 对齐）──
        last_raw = cursors.get("last_tick")
        if isinstance(last_raw, dict):
            last_raw = last_raw.get("value")
        if not last_raw:
            return PollResult(rebase=True, cursor_updates={"last_tick": now.isoformat()})
        last = datetime.fromisoformat(str(last_raw))
        fires = due_fire_times(schedule, last, now, max_catchup_seconds=max_catchup)
        if not fires:
            if (now - last).total_seconds() > max_catchup:
                return PollResult(rebase=True, cursor_updates={"last_tick": now.isoformat()})
            return PollResult()

        # ── 到期：五类扫描（全只读）──
        job_state: dict[str, Any] = dict(cursors.get("job_state") or {})
        dep_state: dict[str, Any] = dict(cursors.get("dep_state") or {})

        drafts: list[TriggerDraft] = []
        routing: list[TriggerDraft] = []  # 恢复/漏审/依赖类不占风暴配额、不聚合
        routing.extend(await _scan_jobs(session, job_state))

        failure_drafts: list[TriggerDraft] = []
        failure_drafts.extend(await _scan_parked(session))
        failure_drafts.extend(await _scan_deadletter())
        routing.extend(await _scan_dependencies(session, dep_state))

        # ── 防风暴：故障类 >5 → 一条聚合 trigger（payload 带清单）──
        if len(failure_drafts) > SCAN_TRIGGER_CAP:
            today_iso = _today().isoformat()
            failure_drafts = [TriggerDraft(
                external_id=signals.batch_eid(
                    today_iso, [d.external_id for d in failure_drafts],
                ),
                thread_key=signals.opsmisc_thread(today_iso),
                actor={"id": "ops_scan", "type": "aggregator"},
                payload={
                    "signal": signals.SIGNAL_BATCH,
                    "count": len(failure_drafts),
                    "items": [dict(d.payload or {}) for d in failure_drafts[:20]],
                    "channel": {"kind": "ops_batch"},
                },
            )]
        drafts.extend(failure_drafts)
        drafts.extend(routing)

        logger.info(
            "ops_scan 一轮：故障类 %d（聚合=%s）+ 路由类 %d → %d drafts",
            len(failure_drafts), len(failure_drafts) > SCAN_TRIGGER_CAP,
            len(routing), len(drafts),
        )
        return PollResult(
            drafts=drafts,
            cursor_updates={
                "last_tick": fires[-1].isoformat(),
                "job_state": _prune_job_state(job_state),
                "dep_state": dep_state,
            },
        )


def missed_review_date(run_day: str) -> str:
    """漏审日 → 补跑审核日期（run_on D 审 D-1；设计 §4.4 判定规则）。"""
    return (date_type.fromisoformat(run_day) - timedelta(days=1)).isoformat()
