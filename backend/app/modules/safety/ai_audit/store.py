"""AI 调用审计的写入与查询（repository + service 职责，供 executor / API / Agent 工具共用）。

写入走独立 session（``insert_audit``）；查询接收调用方的请求级 session。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Integer, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ, now
from app.modules.safety.ai_audit.models import AICallAudit

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 写入（独立 session，永不抛出）
# ═══════════════════════════════════════════════════════════════


async def insert_audit(**fields: Any) -> None:
    """独立 session 写入一条审计记录。任何异常只告警，不向上抛。

    供不经过 AuditedAIService 的调用路径使用（如业务 Agent 的 executor，
    其模型调用走 pydantic-ai 而非平台 AIService）。
    """
    try:
        from app.core.database import async_session_factory

        row = AICallAudit(**fields)
        async with async_session_factory() as session:
            session.add(row)
            await session.commit()

        # ── 失败飞书通知（fire-and-forget，不阻塞审计写入） ──
        if fields.get("status") == "failed":
            from app.modules.safety.ai_audit.failure_notifier import fire_notify

            fire_notify(
                scenario=fields.get("scenario", "unknown"),
                error=fields.get("error"),
                trace_id=fields.get("trace_id"),
                channel=fields.get("channel"),
                model=fields.get("model"),
            )
    except Exception:
        logger.exception("AI 调用审计写入失败（不影响业务）")


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════


async def list_audits(
    session: AsyncSession,
    *,
    scenario: str | None = None,
    status: str | None = None,
    channel: str | None = None,
    resource_id: uuid.UUID | None = None,
    user_name: str | None = None,
    keyword: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[AICallAudit], int]:
    """分页查询审计记录，返回 (rows, total)。"""
    conditions = []
    if scenario:
        conditions.append(AICallAudit.scenario == scenario)
    if status:
        conditions.append(AICallAudit.status == status)
    if channel:
        conditions.append(AICallAudit.channel == channel)
    if resource_id:
        conditions.append(AICallAudit.resource_id == resource_id)
    if user_name:
        conditions.append(AICallAudit.user_name.ilike(f"%{user_name}%"))
    if keyword:
        kw = f"%{keyword}%"
        conditions.append(
            AICallAudit.input_text.ilike(kw) | AICallAudit.output_text.ilike(kw)
        )
    if date_from:
        conditions.append(AICallAudit.created_at >= date_from)
    if date_to:
        conditions.append(AICallAudit.created_at <= date_to)

    count_stmt = select(func.count()).select_from(AICallAudit)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await session.execute(count_stmt)).scalar_one()

    stmt = select(AICallAudit)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = (
        stmt.order_by(AICallAudit.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return rows, total


async def get_audit(
    session: AsyncSession, audit_id: uuid.UUID
) -> AICallAudit | None:
    """按 ID 取单条审计记录（详情，含全文）。"""
    return await session.get(AICallAudit, audit_id)


async def get_stats(
    session: AsyncSession,
    days: int = 7,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    """时间窗内按场景聚合 + 按天序列 + 上一等长周期环比。

    默认近 ``days`` 天；显式传 ``date_from``/``date_to`` 时以其为准。
    返回 ``by_scenario``（场景聚合）、``daily``（趋势图数据）、
    ``prev_totals``（上一周期总量，供前端算环比）。
    """
    until = date_to or now()
    since = date_from or (until - timedelta(days=days))

    _failed_sum = func.coalesce(
        func.sum(case((AICallAudit.status == "failed", 1), else_=0).cast(Integer)), 0
    )

    # ── 场景聚合 ──
    stmt = (
        select(
            AICallAudit.scenario,
            func.count().label("calls"),
            func.coalesce(func.sum(AICallAudit.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AICallAudit.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(AICallAudit.cache_hit_tokens), 0).label("cache_hit_tokens"),
            func.coalesce(func.sum(AICallAudit.cache_miss_tokens), 0).label("cache_miss_tokens"),
            func.coalesce(func.avg(AICallAudit.latency_ms), 0).label("avg_latency_ms"),
            _failed_sum.label("failed"),
        )
        .where(AICallAudit.created_at >= since, AICallAudit.created_at < until)
        .group_by(AICallAudit.scenario)
    )
    result = await session.execute(stmt)

    by_scenario = []
    totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_hit_tokens": 0, "cache_miss_tokens": 0, "failed": 0}
    for row in result:
        item = {
            "scenario": row.scenario,
            "calls": int(row.calls),
            "input_tokens": int(row.input_tokens),
            "output_tokens": int(row.output_tokens),
            "cache_hit_tokens": int(row.cache_hit_tokens),
            "cache_miss_tokens": int(row.cache_miss_tokens),
            "avg_latency_ms": int(row.avg_latency_ms),
            "failed": int(row.failed),
        }
        by_scenario.append(item)
        totals["calls"] += item["calls"]
        totals["input_tokens"] += item["input_tokens"]
        totals["output_tokens"] += item["output_tokens"]
        totals["cache_hit_tokens"] += item["cache_hit_tokens"]
        totals["cache_miss_tokens"] += item["cache_miss_tokens"]
        totals["failed"] += item["failed"]

    # ── 按天 × 场景序列（趋势图） ──
    # 将 UTC 时间戳转为 Asia/Shanghai 后再截断，确保按中国日期分组
    day_col = func.date_trunc("day", func.timezone(str(APP_TZ), AICallAudit.created_at)).label("day")
    daily_stmt = (
        select(
            day_col,
            AICallAudit.scenario,
            func.count().label("calls"),
            func.coalesce(func.sum(AICallAudit.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AICallAudit.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(AICallAudit.cache_hit_tokens), 0).label("cache_hit_tokens"),
            func.coalesce(func.sum(AICallAudit.cache_miss_tokens), 0).label("cache_miss_tokens"),
            _failed_sum.label("failed"),
        )
        .where(AICallAudit.created_at >= since, AICallAudit.created_at < until)
        .group_by(day_col, AICallAudit.scenario)
        .order_by(day_col)
    )
    daily = [
        {
            "date": row.day.date().isoformat(),
            "scenario": row.scenario,
            "calls": int(row.calls),
            "input_tokens": int(row.input_tokens),
            "output_tokens": int(row.output_tokens),
            "cache_hit_tokens": int(row.cache_hit_tokens),
            "cache_miss_tokens": int(row.cache_miss_tokens),
            "failed": int(row.failed),
        }
        for row in await session.execute(daily_stmt)
    ]

    # ── 上一等长周期总量（环比基数） ──
    prev_since = since - (until - since)
    prev_stmt = select(
        func.count().label("calls"),
        func.coalesce(func.sum(AICallAudit.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(AICallAudit.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(AICallAudit.cache_hit_tokens), 0).label("cache_hit_tokens"),
        func.coalesce(func.sum(AICallAudit.cache_miss_tokens), 0).label("cache_miss_tokens"),
        _failed_sum.label("failed"),
    ).where(AICallAudit.created_at >= prev_since, AICallAudit.created_at < since)
    prev = (await session.execute(prev_stmt)).one()
    prev_totals = {
        "calls": int(prev.calls),
        "input_tokens": int(prev.input_tokens),
        "output_tokens": int(prev.output_tokens),
        "cache_hit_tokens": int(prev.cache_hit_tokens),
        "cache_miss_tokens": int(prev.cache_miss_tokens),
        "failed": int(prev.failed),
    }

    return {
        "days": days,
        "date_from": since.isoformat(),
        "date_to": until.isoformat(),
        "totals": totals,
        "prev_totals": prev_totals,
        "by_scenario": by_scenario,
        "daily": daily,
    }
