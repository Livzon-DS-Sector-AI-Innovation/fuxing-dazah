"""Watchdog —— 组件健康之上的「实质进展」巡检。

不只查进程存活——按任务查「同阶段停留超阈值」；命中 DM 管理员结构化清单。
巡检本身走 effects（先存后发）——自举不裸奔（红线④）。
健康态不占速递版面（仓库面板原则⑥）。

一期三条阈值规则（core settings 可配）：
1. blocked 超 24h 且此后无人的消息
2. queued 超 2h（无执行空位）
3. observe 积压超 N（默认 50）条未回放
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.platform.superagent.effects import enqueue_effect, report_state
from app.platform.superagent.models import AgentDecision, AgentTask
from app.platform.superagent.tasks import STAGE_BLOCKED, STAGE_QUEUED, derive_stage

logger = logging.getLogger(__name__)


def _thresholds() -> dict[str, float]:
    from app.core.config import get_settings

    s = get_settings()
    return {
        "blocked_hours": s.SUPERAGENT_BLOCKED_ALERT_HOURS,
        "queued_hours": s.SUPERAGENT_QUEUED_ALERT_HOURS,
        "observe_backlog": s.SUPERAGENT_OBSERVE_BACKLOG_ALERT,
    }


async def collect_watchdog_findings(session: Any) -> dict[str, Any]:
    """纯查询：收集三条规则的命中清单（不发任何消息——由调用方走 effects）。"""
    now = datetime.now(UTC)
    th = _thresholds()

    open_tasks = (
        await session.execute(select(AgentTask).where(AgentTask.status == "open"))
    ).scalars().all()

    blocked_stale: list[dict[str, Any]] = []
    queued_stale: list[dict[str, Any]] = []
    for task in open_tasks:
        stage = derive_stage(task.stage_facts)
        facts = task.stage_facts or {}
        report_at = facts.get("latest_report_at")
        anchor = None
        if report_at:
            try:
                anchor = datetime.fromisoformat(report_at)
            except (TypeError, ValueError):
                anchor = None
        if stage == STAGE_BLOCKED and not facts.get("human_after_report"):
            base = anchor or task.created_at
            if base is not None and now - base > timedelta(hours=th["blocked_hours"]):
                blocked_stale.append({
                    "task": str(task.id), "name": task.short_name,
                    "since": base.isoformat(), "report": facts.get("latest_report"),
                })
        elif stage == STAGE_QUEUED:
            base = task.created_at
            if base is not None and now - base > timedelta(hours=th["queued_hours"]):
                queued_stale.append({
                    "task": str(task.id), "name": task.short_name,
                    "since": base.isoformat(),
                })

    unresolved = (
        await session.execute(
            select(func.count()).select_from(AgentDecision).where(
                AgentDecision.would_accept.is_(True),
                AgentDecision.replay.is_(False),
                AgentDecision.resolution.is_(None),
            )
        )
    ).scalar_one()

    return {
        "blocked_stale": blocked_stale,
        "queued_stale": queued_stale,
        "observe_backlog": int(unresolved),
        "observe_backlog_threshold": int(th["observe_backlog"]),
    }


def has_findings(findings: dict[str, Any]) -> bool:
    return bool(
        findings.get("blocked_stale")
        or findings.get("queued_stale")
        or findings.get("observe_backlog", 0) > findings.get("observe_backlog_threshold", 0)
    )


def render_findings_text(findings: dict[str, Any]) -> str:
    lines = ["[Super-agent Watchdog] 需要人关注："]
    for item in findings.get("blocked_stale", [])[:10]:
        lines.append(f"· 受阻超时 {item['name']}（{item['report']}，自 {item['since']}）")
    for item in findings.get("queued_stale", [])[:10]:
        lines.append(f"· 排队超时 {item['name']}（自 {item['since']}）")
    backlog = findings.get("observe_backlog", 0)
    if backlog > findings.get("observe_backlog_threshold", 0):
        lines.append(f"· observe 回放积压 {backlog} 条未处置（阈值 {findings['observe_backlog_threshold']}）")
    return "\n".join(lines)


async def run_watchdog_round(session: Any) -> dict[str, Any]:
    """一轮巡检：查询 → 有命中才 DM（dm_admin effect 先存后发，按日幂等）。"""
    try:
        findings = await collect_watchdog_findings(session)
        if has_findings(findings):
            await enqueue_effect(
                session, "dm_admin",
                {"text": render_findings_text(findings)},
                dedupe_key=f"watchdog:{datetime.now(UTC).date().isoformat()}",
            )
            await report_state(session, "superagent:watchdog", "error",
                               f"巡检命中：受阻 {len(findings['blocked_stale'])} / "
                               f"排队 {len(findings['queued_stale'])} / "
                               f"积压 {findings['observe_backlog']}")
        else:
            await report_state(session, "superagent:watchdog", "ready")
        return findings
    except Exception:
        logger.exception("Watchdog 巡检异常")
        await report_state(session, "superagent:watchdog", "error", "巡检异常（见日志）")
        return {"error": "watchdog_failed"}


# ═══════════════════════════════════════════════════════════════
# 「需要人」格快照（一期唯一 UI 落点；健康态不占版面）
# ═══════════════════════════════════════════════════════════════


async def build_needs_human_snapshot(session: Any, *, days: int = 1) -> dict[str, Any]:
    """待验收 + 待回答 + 受阻超时 + observe 回放摘要（stage 现算为口径源）。"""
    from sqlalchemy import or_

    from app.platform.superagent.models import AgentTrigger
    from app.platform.superagent.tasks import (
        STAGE_AWAIT_ACCEPT,
        STAGE_AWAIT_ANSWER,
        STAGE_BLOCKED,
    )

    open_tasks = (
        await session.execute(select(AgentTask).where(AgentTask.status == "open"))
    ).scalars().all()
    by_stage: dict[str, list[AgentTask]] = {}
    for t in open_tasks:
        by_stage.setdefault(derive_stage(t.stage_facts), []).append(t)

    now = datetime.now(UTC)
    blocked_stale = [
        t for t in by_stage.get(STAGE_BLOCKED, [])
        if not (t.stage_facts or {}).get("human_after_report")
    ]

    replay_rows = (
        await session.execute(
            select(AgentDecision, AgentTrigger)
            .join(AgentTrigger, AgentDecision.trigger_id == AgentTrigger.id)
            .where(
                AgentDecision.would_accept.is_(True),
                AgentDecision.replay.is_(False),
                AgentDecision.resolution.is_(None),
                or_(
                    AgentDecision.created_at >= now - timedelta(days=days),
                    AgentDecision.created_at.is_(None),
                ),
            )
            .order_by(AgentDecision.created_at.desc())
            .limit(20)
        )
    ).all()

    def _task_line(t: AgentTask) -> str:
        return f"{t.short_name}（{t.title}）"

    return {
        "await_accept": {
            "count": len(by_stage.get(STAGE_AWAIT_ACCEPT, [])),
            "items": [_task_line(t) for t in by_stage.get(STAGE_AWAIT_ACCEPT, [])[:10]],
        },
        "await_answer": {
            "count": len(by_stage.get(STAGE_AWAIT_ANSWER, [])),
            "items": [_task_line(t) for t in by_stage.get(STAGE_AWAIT_ANSWER, [])[:10]],
        },
        "blocked_stale": {
            "count": len(blocked_stale),
            "items": [_task_line(t) for t in blocked_stale[:10]],
        },
        "observe_replay": {
            "count": len(replay_rows),
            "items": [
                {
                    "decision_id": str(d.id),
                    "rule_id": d.rule_id,
                    "trigger_key": t.external_id,
                    # 摘要渲染归 host 应用（平台不硬编码业务字段名）；
                    # payload 字段仅作展示数据，永不参与授权（红线⑦）
                    "fields": dict((t.payload or {}).get("fields") or {}),
                }
                for d, t in replay_rows
            ],
        },
        "backlog_total": 0,
    }
