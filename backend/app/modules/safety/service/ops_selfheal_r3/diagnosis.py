"""R3 诊断 —— A 证据采集（只读 checklist）+ B LLM 归因（单次调用 JSON 契约）。

程序抓证据、LLM 开处方、程序抓药（§4.3）：

- 证据按信号类固定 checklist，纯只读；错误原文是**证据**（供 LLM 归因与
  端点提取），永不参与授权判定（红线⑦）；
- LLM 单次调用 deepseek-flash（``ai_call_audits`` scenario=r3_ops_diagnosis
  留痕计费）；输出契约严格校验（root_cause_class 七枚举 / confidence 区间 /
  prescriptions.action 枚举），解析失败/超时/关闸 → 降级 unknown 纯规则直出，
  不重试不抛；
- 规则降级表 = 关键词启发（余额类/连接类一眼可辨），处方只出 L0 与
  urgency=human 标注——降级路径绝不产出 L1 自动处方。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.modules.safety.service.ops_selfheal_r3 import config, signals

logger = logging.getLogger(__name__)

#: 处方动作枚举（LLM 只能从中选；与 actions.ACTIONS 键一致）
PRESCRIPTION_ACTIONS = (
    "notify_enriched", "rag_recheck", "effects_unpark", "job_backfill",
    "hazard_dead_letter_rerun", "hazard_stale_rerun", "job_window_extend",
)

#: urgency 枚举
URGENCIES = ("now", "next_scan", "human")

#: LLM 单次调用超时（秒；超时即降级，不重试）
LLM_TIMEOUT_SECONDS = 45

_URGENCY_HINTS = ("余额", "欠费", "429", "1113", "quota", "arrear")
_CONNECT_HINTS = (
    "ConnectError", "ConnectTimeout", "Connection refused", "connect timeout",
    "连接", "超时", "timeout", "timed out", "unreachable", "Reset",
)
_URL_RE = re.compile(r"https?://[^\s'\"<>）)]+")
_HOSTPORT_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}\b")


def extract_endpoints(*texts: str | None) -> list[str]:
    """从错误原文提取依赖端点（http URL / IP:port；去重保序，≤5）。

    URL 已命中时其内 host:port 不再重复提取（同一端点两种形态只取 URL）。
    """
    seen: list[str] = []
    url_text = ""
    for text in texts:
        if not text:
            continue
        for m in _URL_RE.findall(text) or []:
            cand = m.rstrip(".,;")
            if cand not in seen:
                seen.append(cand)
                url_text += cand + " "
        for m in _HOSTPORT_RE.findall(text) or []:
            if m not in seen and m not in url_text:
                seen.append(m)
    return seen[:5]


def _bj_today_iso() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


# ═══════════════════════════════════════════════════════════════
# A. 证据采集（只读）
# ═══════════════════════════════════════════════════════════════


async def _probe_rag_raw() -> dict[str, Any]:
    """RAG 原始探针（直调 probe_*，禁走 run_rag_health_probe 状态机——
    共享状态机会吃掉翻转导致直投丢信号）。"""
    from app.modules.safety.knowledge.rag_health import probe_embedding, probe_ragplus

    embedding, ragplus = await asyncio.gather(probe_embedding(), probe_ragplus())
    return {
        "embedding_ok": embedding[0],
        "embedding_detail": embedding[1][:200],
        "ragplus": None if ragplus is None else {"ok": ragplus[0], "detail": ragplus[1][:200]},
    }


async def _probe_feishu() -> dict[str, Any]:
    """飞书连通性（tenant token 获取即探活）。"""
    try:
        from app.modules.safety.feishu.client import get_safety_tenant_token

        token = await get_safety_tenant_token()
        return {"ok": bool(token)}
    except Exception as exc:  # noqa: BLE001 — 探测失败即证据
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}


async def collect_evidence(session: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """按信号类采集结构化证据（纯只读；文本仅作证据快照）。"""
    signal = str(payload.get("signal") or "")
    evidence: dict[str, Any] = {"signal": signal, "at": payload.get("at")}

    if signal == signals.SIGNAL_JOB_FAILED:
        evidence.update(await _evidence_job(session, payload))
    elif signal in (signals.SIGNAL_RAG_DEGRADED, signals.SIGNAL_RAG_RECOVERED):
        evidence.update(await _evidence_rag(session, payload))
    elif signal == signals.SIGNAL_PARKED:
        evidence.update(await _evidence_parked(session, payload))
    elif signal == signals.SIGNAL_DEADLETTER:
        evidence.update(await _evidence_deadletter(payload))
    elif signal == signals.SIGNAL_BATCH:
        evidence["items"] = list(payload.get("items") or [])[:20]
        evidence["count"] = payload.get("count")
    elif signal == signals.SIGNAL_AICALL_FAILED:
        evidence.update(await _evidence_aicall(session, payload))
    elif signal == signals.SIGNAL_PUSH_FAILED:
        evidence.update(await _evidence_push(session, payload))
    elif signal == signals.SIGNAL_EVENT_FAILED:
        evidence.update(_evidence_event(payload))
    elif signal == signals.SIGNAL_RAGFLOW_FAILED:
        evidence.update(await _evidence_ragflow(session, payload))
    return evidence


async def _evidence_job(session: Any, payload: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.modules.safety.models.msds import SchedulerJobRun
    from app.modules.safety.models.scheduler_run_log import SchedulerTaskRunLog
    from sqlalchemy import select

    job = str(payload.get("job_name") or "")
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    since = now - timedelta(days=2)

    logs = (
        await session.execute(
            select(SchedulerTaskRunLog)
            .where(
                SchedulerTaskRunLog.job_name == job,
                SchedulerTaskRunLog.started_at >= since,
            )
            .order_by(SchedulerTaskRunLog.started_at.desc())
            .limit(10)
        )
    ).scalars().all()
    error_rows = [
        {
            "started_at": x.started_at.isoformat() if x.started_at else None,
            "error": (x.error or "")[:500] or None,
        }
        for x in logs if x.status != "success"
    ][:3]
    attempts_today = sum(
        1 for x in logs
        if x.started_at and x.started_at.astimezone(tz).date() == now.date()
    )

    # 跨任务关联：同窗其他 failed job
    other_failed = [
        {"job_name": r.job_name, "fired_date": r.fired_date.isoformat(),
         "attempt_count": r.attempt_count}
        for r in (
            await session.execute(
                select(SchedulerJobRun).where(
                    SchedulerJobRun.status == "failed",
                    SchedulerJobRun.job_name != job,
                )
            )
        ).scalars().all()
    ][:5]

    error_texts = [str(r.get("error") or "") for r in error_rows]
    rag, feishu = await asyncio.gather(_probe_rag_raw(), _probe_feishu())
    return {
        "job_name": job,
        "fired_date": payload.get("fired_date"),
        "attempt_count": payload.get("attempt_count"),
        "errors": error_rows,
        "attempts_recent": attempts_today,
        "other_failed_jobs": other_failed,
        "rag": rag,
        "feishu": feishu,
        "dep_endpoints": extract_endpoints(*error_texts),
    }


async def _evidence_rag(session: Any, payload: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import func, select

    from app.modules.safety.service.ops_selfheal_r3.rule import R3_RAG_SOURCE_NAME
    from app.platform.superagent.models import AgentSource, AgentTrigger

    # 当日抖动次数（同 thread trigger 计数）
    day = _bj_today_iso()
    src = (
        await session.execute(
            select(AgentSource).where(AgentSource.name == R3_RAG_SOURCE_NAME)
        )
    ).scalar_one_or_none()
    flaps = 0
    if src is not None:
        flaps = (
            await session.execute(
                select(func.count()).select_from(AgentTrigger).where(
                    AgentTrigger.source_id == src.id,
                    AgentTrigger.thread_key == signals.rag_thread(day),
                )
            )
        ).scalar_one()
    return {
        "detail": str(payload.get("detail") or "")[:600],
        "duration": payload.get("duration"),
        "flaps_today": flaps,
    }


async def _evidence_parked(session: Any, payload: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.platform.superagent.models import AgentEffect

    kinds = [str(payload.get("component") or "")]
    rows = (
        await session.execute(
            select(AgentEffect).where(
                AgentEffect.status == "failed",
                AgentEffect.kind.in_(kinds),
            )
        )
    ).scalars().all()
    return {
        "component": payload.get("component"),
        "count": len(rows),
        "samples": [
            {"dedupe_key": x.dedupe_key, "attempts": x.attempts,
             "last_error": (x.last_error or "")[:300] or None}
            for x in rows[:3]
        ],
    }


async def _evidence_deadletter(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "count": payload.get("count"),
        "samples": list(payload.get("samples") or [])[:5],
    }


# ── 二期扩面：四类新信号证据 checklist（全只读，fail-open 惯例）──


async def _evidence_aicall(session: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """①AI 调用失败：窗口内成功/失败分布 + 失败样本 error 摘要。"""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from app.modules.safety.ai_audit.models import AICallAudit
    from app.modules.safety.service.ops_selfheal_r3.scan_source import (
        AI_FAILURE_WINDOW_MIN,
    )

    scenario = str(payload.get("scenario") or "")
    window_start = datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(
        minutes=AI_FAILURE_WINDOW_MIN,
    )
    try:
        success_n = (
            await session.execute(
                select(AICallAudit.id).where(
                    AICallAudit.scenario == scenario,
                    AICallAudit.status == "success",
                    AICallAudit.created_at >= window_start,
                )
            )
        ).scalars().all()
        samples = (
            await session.execute(
                select(AICallAudit.error, AICallAudit.model, AICallAudit.latency_ms)
                .where(
                    AICallAudit.scenario == scenario,
                    AICallAudit.status == "failed",
                    AICallAudit.created_at >= window_start,
                )
                .limit(5)
            )
        ).all()
    except Exception:  # noqa: BLE001 — fail-open 红线
        logger.warning("R3 ai_call 证据采集 fail-open")
        success_n, samples = [], []
    return {
        "scenario": scenario,
        "failed_count": payload.get("failed_count"),
        "window_minutes": AI_FAILURE_WINDOW_MIN,
        "success_count_in_window": len(success_n),
        "samples": [
            {"model": m, "latency_ms": lat, "error": (e or "")[:300]}
            for e, m, lat in samples
        ],
    }


async def _evidence_push(session: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """②推送失败：当日 outbox dropped 行 / dm_admin effect 连败样本（与扫描同口径）。"""
    from datetime import datetime
    from datetime import time as dtime
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from app.platform.superagent.models import AgentEffect, AgentOutboxMessage

    component = str(payload.get("component") or "")
    out: dict[str, Any] = {"component": component}
    day_start = datetime.combine(
        datetime.now(ZoneInfo("Asia/Shanghai")).date(), dtime.min,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    try:
        if component == "outbox":
            out["dropped_count"] = len((
                await session.execute(
                    select(AgentOutboxMessage.id).where(
                        AgentOutboxMessage.status == "dropped",
                        AgentOutboxMessage.created_at >= day_start,
                    )
                )
            ).scalars().all())
            dropped = (
                await session.execute(
                    select(AgentOutboxMessage)
                    .where(
                        AgentOutboxMessage.status == "dropped",
                        AgentOutboxMessage.created_at >= day_start,
                    )
                    .limit(5)
                )
            ).scalars().all()
            out["samples"] = [
                {"conversation": x.conversation[:120],
                 "dropped_reason": (x.dropped_reason or "")[:200],
                 "last_error": (x.last_error or "")[:200]}
                for x in dropped
            ]
        else:  # dm_admin
            rows = (
                await session.execute(
                    select(AgentEffect).where(
                        AgentEffect.kind == "dm_admin",
                        AgentEffect.status == "failed",
                        AgentEffect.created_at >= day_start,
                    ).limit(5)
                )
            ).scalars().all()
            out["failed_effect_count"] = len(rows)
            out["samples"] = [
                {"attempts": x.attempts, "last_error": (x.last_error or "")[:200]}
                for x in rows
            ]
    except Exception:  # noqa: BLE001 — fail-open 红线
        logger.warning("R3 push 证据采集 fail-open")
    return out


def _evidence_event(payload: dict[str, Any]) -> dict[str, Any]:
    """③飞书事件失败：payload 即证据（直投时已带 handler/error）。"""
    return {
        "event_type": str(payload.get("event_type") or "")[:120],
        "handler": str(payload.get("handler") or "")[:120],
        "error": str(payload.get("error") or "")[:400],
    }


async def _evidence_ragflow(session: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """④RAG 吞吐：当日 failed 文档清单 + run 级失败计数。"""
    from sqlalchemy import select

    from app.modules.safety.models.knowledge import RagplusDocMap

    samples: list[dict[str, Any]] = []
    doc_n = 0
    try:
        rows = (
            await session.execute(
                select(RagplusDocMap)
                .where(RagplusDocMap.status == "failed")
                .limit(5)
            )
        ).scalars().all()
        doc_n = len(rows)
        samples = [
            {"domain": x.domain, "title": (x.title or "")[:120],
             "last_error": (x.last_error or "")[:200]}
            for x in rows
        ]
    except Exception:  # noqa: BLE001 — fail-open 红线
        logger.warning("R3 ragflow 证据采集 fail-open")
    return {
        "failed_doc_count": payload.get("failed_doc_count"),
        "failed_run_count": payload.get("failed_run_count"),
        "current_failed_visible": doc_n,
        "samples": samples,
    }


# ═══════════════════════════════════════════════════════════════
# B. LLM 归因（单次调用；契约校验；降级不抛）
# ═══════════════════════════════════════════════════════════════


def _llm_messages(signal: str, evidence: dict[str, Any]) -> list[dict[str, str]]:
    import json

    return [
        {
            "role": "system",
            "content": (
                "你是安全生产系统的运维自愈诊断器。根据结构化证据判定故障根因并开处方。\n"
                "root_cause_class 只能取：upstream_outage(上游平台/外部依赖断连)、"
                "quota_exhausted(API余额/配额耗尽)、network(本机网络瞬断)、"
                "config_error(配置错误)、data_issue(数据问题)、code_bug(代码缺陷)、"
                "unknown(证据不足)。\n"
                f"prescriptions[].action 只能取：{','.join(PRESCRIPTION_ACTIONS)}。\n"
                "本地不可修的根因（upstream_outage/quota_exhausted）处方给 urgency=human"
                "且不要给 L1 动作；输出 JSON：{\"root_cause_class\":str,"
                "\"confidence\":0-1,\"reasoning\":\"≤120字\","
                "\"cross_signals\":[str],\"prescriptions\":[{\"action\":str,"
                "\"args\":{},\"urgency\":\"now|next_scan|human\"}]}"
            ),
        },
        {
            "role": "user",
            "content": f"信号类：{signal}\n证据：{json.dumps(evidence, ensure_ascii=False, default=str)[:6000]}",
        },
    ]


def validate_llm_output(data: dict[str, Any]) -> dict[str, Any] | None:
    """契约严格校验：任一键非法 → None（调用方降级 unknown）。"""
    rc = data.get("root_cause_class")
    if rc not in signals.ROOT_CAUSE_CLASSES:
        return None
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence"))))
    except (TypeError, ValueError):
        return None
    prescriptions: list[dict[str, Any]] = []
    for p in data.get("prescriptions") or []:
        if not isinstance(p, dict) or p.get("action") not in PRESCRIPTION_ACTIONS:
            continue
        prescriptions.append({
            "action": str(p["action"]),
            "args": dict(p.get("args") or {}) if isinstance(p.get("args"), dict) else {},
            "urgency": p.get("urgency") if p.get("urgency") in URGENCIES else "next_scan",
        })
    return {
        "root_cause_class": rc,
        "confidence": confidence,
        "reasoning": str(data.get("reasoning") or "")[:120],
        "cross_signals": [str(x)[:80] for x in (data.get("cross_signals") or [])][:5],
        "prescriptions": prescriptions,
        "source": "llm",
    }


def rule_based_diagnosis(signal: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """纯规则降级（零 LLM）：关键词启发 + 只出 L0 处方（设计 §4.3 降级路径）。"""
    texts: list[str] = []
    if evidence.get("detail"):
        texts.append(str(evidence["detail"]))
    texts += [str(e.get("error") or "") for e in (evidence.get("errors") or [])]
    # 二期扩面证据字段也进关键词 blob（samples/事件 error）
    texts += [str(e.get("error") or "") for e in (evidence.get("samples") or [])]
    texts += [str(e.get("last_error") or "") for e in (evidence.get("samples") or [])]
    if evidence.get("error"):
        texts.append(str(evidence["error"]))
    blob = " ".join(texts)

    endpoints = [str(e) for e in (evidence.get("dep_endpoints") or [])]
    if any(h in blob for h in _URGENCY_HINTS):
        rc, urgency = "quota_exhausted", "human"
    elif endpoints:
        rc, urgency = "upstream_outage", "human"
    elif any(h in blob for h in _CONNECT_HINTS):
        rc, urgency = "network", "human"
    else:
        rc, urgency = "unknown", "human"

    prescriptions: list[dict[str, Any]] = [{"action": "notify_enriched", "args": {}, "urgency": "now"}]
    if signal in (signals.SIGNAL_RAG_DEGRADED, signals.SIGNAL_JOB_FAILED):
        prescriptions.append({"action": "rag_recheck", "args": {}, "urgency": "next_scan"})
    return {
        "root_cause_class": rc,
        "confidence": 0.5,
        "reasoning": "纯规则降级（LLM 不可用/未启用/解析失败），证据直出",
        "cross_signals": [],
        "prescriptions": prescriptions,
        "urgency_hint": urgency,
        "source": "rules",
    }


async def llm_diagnose(signal: str, evidence: dict[str, Any]) -> dict[str, Any] | None:
    """单次 LLM 归因（审计留痕）；任何失败返回 None → 调用方走规则降级。"""
    if not config.diag_llm_enabled():
        return None
    try:
        from app.modules.safety.ai_audit.context import ai_audit_scope
        from app.modules.safety.service.config import create_ai_service

        with ai_audit_scope(scenario="r3_ops_diagnosis", channel="system"):
            service = create_ai_service("text")
            try:
                raw = await asyncio.wait_for(
                    service.chat_parsed(
                        _llm_messages(signal, evidence),
                        expected_keys=["root_cause_class", "confidence", "reasoning", "prescriptions"],
                        temperature=0.1,
                    ),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
            finally:
                await service.close()
        return validate_llm_output(raw)
    except Exception:  # noqa: BLE001 — 降级红线：LLM 任何异常不抛不重试
        logger.exception("R3 LLM 归因失败，降级纯规则（signal=%s）", signal)
        return None


async def diagnose(signal: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """归因入口：LLM 优先，失败/关闸降级规则表。"""
    return await llm_diagnose(signal, evidence) or rule_based_diagnosis(signal, evidence)
