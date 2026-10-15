"""采集监控聚合（契约③ + 本仓收录留痕 → 三态信封）。

三态：not_connected=ragplus 爬虫模块 404/未部署；live=对接正常且无
down 源；degraded=不可达（errors 标注，绝不静默空结果）/存在 down 或
suspect_rebuild 源/ragplus 最近 run failed。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import RegulationIngestRun
from app.modules.safety.regulation_ingest.ragplus_crawler_client import (
    RagplusCrawlerError,
    RagplusCrawlerNotConnectedError,
    get_ragplus_crawler_client,
)

logger = logging.getLogger(__name__)

# 聚合窗口（stats 近7日 / funnel 近30日；待复核与原文待补为累计存量）
_STATS_WINDOW_DAYS = 7
_FUNNEL_WINDOW_DAYS = 30
_AGG_SCAN_ROWS = 200
_FEED_MAX = 20

_STATUS_NOT_CONNECTED = "not_connected"
_STATUS_LIVE = "live"
_STATUS_DEGRADED = "degraded"

# ragplus 契约③ runs 明细字段 v1 未逐项冻结——漏斗左半防御式取键
_RAG_FOUND_KEYS = ("found_count", "discovered", "found", "items_found")
_RAG_PARSED_KEYS = ("parsed_count", "parsed", "items_parsed")


def _first_key(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _serialize_run(row: RegulationIngestRun) -> dict[str, Any]:
    return {
        "run_log_id": str(row.id),
        "source_run_id": row.source_run_id,
        "source": row.source,
        "status": row.status,
        "received_count": row.received_count,
        "duplicate_count": row.duplicate_count,
        "pending_count": row.pending_count,
        "promoted_count": row.promoted_count,
        "rejected_count": row.rejected_count,
        "failed_count": row.failed_count,
        "ai_tokens_used": row.ai_tokens_used,
        "items_result": row.items_result or [],
        "receipts": row.receipts,
        "error_summary": row.error_summary,
        "created_at": _iso(row.created_at),
        "finished_at": _iso(row.finished_at),
    }


async def _load_recent_runs(
    session: AsyncSession, days: int, limit: int = _AGG_SCAN_ROWS,
) -> list[RegulationIngestRun]:
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(RegulationIngestRun)
        .where(
            RegulationIngestRun.is_deleted.is_(False),
            RegulationIngestRun.created_at >= since,
        )
        .order_by(RegulationIngestRun.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _load_all_active(session: AsyncSession) -> list[RegulationIngestRun]:
    stmt = (
        select(RegulationIngestRun)
        .where(RegulationIngestRun.is_deleted.is_(False))
        .order_by(RegulationIngestRun.created_at.desc())
        .limit(_AGG_SCAN_ROWS)
    )
    return list((await session.execute(stmt)).scalars().all())


async def build_monitor_envelope(
    session: AsyncSession, *, page: int = 1, page_size: int = 20,
) -> dict[str, Any]:
    """聚合契约③状态与本仓留痕，产出监控三态信封。"""
    errors: list[str] = []
    rag_status: dict[str, Any] | None = None
    overall = _STATUS_LIVE

    try:
        client = get_ragplus_crawler_client()
        rag_status = await client.get_crawler_status()
    except RagplusCrawlerNotConnectedError as exc:
        overall = _STATUS_NOT_CONNECTED
        errors.append(f"ragplus 爬虫模块未部署（{exc}）")
    except RagplusCrawlerError as exc:
        overall = _STATUS_DEGRADED
        errors.append(f"ragplus 状态查询失败: {exc}")
    except Exception as exc:  # noqa: BLE001 — 聚合端点任何 ragplus 侧异常都不得 5xx
        overall = _STATUS_DEGRADED
        errors.append(f"ragplus 状态查询异常: {exc}")

    sources: list[dict[str, Any]] = (
        rag_status.get("sources") or [] if rag_status else []
    )
    rag_runs: list[dict[str, Any]] = (
        rag_status.get("runs") or [] if rag_status else []
    )

    if overall == _STATUS_LIVE:
        bad_sources = [
            s for s in sources
            if str(s.get("status", "")).lower() in ("down", "suspect_rebuild")
        ]
        if bad_sources:
            overall = _STATUS_DEGRADED
            errors.append(
                "数据源异常: " + "、".join(
                    str(s.get("name", "?")) for s in bad_sources[:5]
                ),
            )
        if rag_runs and str(rag_runs[0].get("status", "")).lower() == "failed":
            overall = _STATUS_DEGRADED
            errors.append("ragplus 最近一次爬取运行 failed")

    # ── 本仓留痕聚合 ──
    stats_window = await _load_recent_runs(session, _STATS_WINDOW_DAYS)
    funnel_window = await _load_recent_runs(session, _FUNNEL_WINDOW_DAYS)
    all_active = await _load_all_active(session)

    items_7d = sum(r.promoted_count for r in stats_window)
    ai_relevant_7d = items_7d  # AI 判定相关=收录执行数（promote）
    pending_total = sum(r.pending_count for r in all_active)
    attachment_missing_total = sum(
        1
        for r in all_active
        for item in (r.items_result or [])
        if item.get("attachment_missing")
    )
    healthy = sum(
        1 for s in sources if str(s.get("status", "")).lower() == "ok"
    )
    last_run = all_active[0] if all_active else None
    rag_last = rag_runs[0] if rag_runs else None

    stats = {
        "sources_total": len(sources),
        "sources_healthy": healthy,
        "items_7d": items_7d,
        "ai_relevant_7d": ai_relevant_7d,
        "pending_review": pending_total,
        "attachment_missing": attachment_missing_total,
        "last_run_at": _iso(last_run.created_at) if last_run else None,
        "last_run_status": last_run.status if last_run else None,
        "last_run_source_id": last_run.source_run_id if last_run else None,
        "ragplus_last_run_at": (
            rag_last.get("started_at") or rag_last.get("finished_at")
            if rag_last else None
        ),
        "ragplus_last_run_status": str(rag_last.get("status")) if rag_last else None,
    }

    # feed：最新收录（promote 条目倒序）
    feed: list[dict[str, Any]] = []
    for row in all_active:
        for item in row.items_result or []:
            if item.get("action_taken") != "promote":
                continue
            feed.append({
                "candidate_id": item.get("candidate_id"),
                "title": item.get("title"),
                "url": item.get("url"),
                "reason": item.get("reason"),
                "is_revision": "修订替代" in (item.get("reason") or ""),
                "bitable_record_id": item.get("bitable_record_id"),
                "ingested_at": _iso(row.created_at),
            })
        if len(feed) >= _FEED_MAX:
            break
    feed = feed[:_FEED_MAX]

    # 漏斗：左半 ragplus 近30日 runs（防御取键），右半本仓留痕求和
    funnel = {
        "discovered": sum(
            v for v in (
                _first_key(r, _RAG_FOUND_KEYS) for r in rag_runs
            ) if v is not None
        ) or None,
        "parsed": sum(
            v for v in (
                _first_key(r, _RAG_PARSED_KEYS) for r in rag_runs
            ) if v is not None
        ) or None,
        "received": sum(r.received_count for r in funnel_window),
        "deduped": sum(r.duplicate_count for r in funnel_window),
        "ai_judged": sum(
            r.received_count - r.duplicate_count for r in funnel_window
        ),
        "promoted": sum(r.promoted_count for r in funnel_window),
        "rejected": sum(r.rejected_count for r in funnel_window),
        "window_days": _FUNNEL_WINDOW_DAYS,
    }

    # 运行历史分页（本仓留痕为主表）
    total_stmt = select(func.count()).select_from(RegulationIngestRun).where(
        RegulationIngestRun.is_deleted.is_(False),
    )
    total = (await session.execute(total_stmt)).scalar() or 0
    runs_stmt = (
        select(RegulationIngestRun)
        .where(RegulationIngestRun.is_deleted.is_(False))
        .order_by(RegulationIngestRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    runs_rows = list((await session.execute(runs_stmt)).scalars().all())

    return {
        "status": overall,
        "stats": stats,
        "sources": sources,
        "feed": feed,
        "funnel": funnel,
        "runs": {
            "data": [_serialize_run(r) for r in runs_rows],
            "meta": {"total": total, "page": page, "page_size": page_size},
        },
        "errors": errors,
    }


async def build_run_detail(
    session: AsyncSession, source_run_id: str,
) -> dict[str, Any] | None:
    """运行详情：本仓收录段（逐条管线）+ ragplus 采集段快照（两段拼接）。"""
    stmt = select(RegulationIngestRun).where(
        RegulationIngestRun.source_run_id == source_run_id,
        RegulationIngestRun.is_deleted.is_(False),
    ).order_by(RegulationIngestRun.created_at.desc())
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return None

    ragplus_run: dict[str, Any] | None = None
    detail_errors: list[str] = []
    try:
        client = get_ragplus_crawler_client()
        status = await client.get_crawler_status()
        for candidate in status.get("runs") or []:
            if str(candidate.get("run_id", "")) == source_run_id:
                ragplus_run = candidate
                break
    except Exception as exc:  # noqa: BLE001 — 采集段缺失不阻塞收录段展示
        detail_errors.append(f"ragplus 采集段快照拉取失败: {exc}")

    return {
        "ingest": _serialize_run(row),
        "ragplus_run": ragplus_run,
        "errors": detail_errors,
    }
