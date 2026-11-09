"""P1-4 D2 —— 隐患 AI 识别质量看板（只读实时聚合服务层）。

与离线 replay（``scripts/hazard_ai_quality_replay.py``）**同口径**：
    审计行窗口查询语义同构（scenario + output_text 非空 + created_at 窗口
    + LIMIT 5000，与 replay SQL 一致；差异仅窗口边界取 ``>=`` 应用时钟 vs
    replay 的 DB 时钟，当前量级无影响），指标全部由 ``quality_metrics``
    纯函数计算（唯一事实源，不重写）。

只读边界：单条 SELECT（命中 idx_ai_audits_scenario_created）+ Redis 死信
HGETALL；无写路径、无网络副作用。死信水位复用 ``failure_ledger``
（hgetall 异常 fail-open→[]；ledger 自身抛错时 count=None 表示水位未知）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_audit.models import AICallAudit
from app.modules.safety.service.hazard_direct.failure_ledger import (
    RedisLike,
    list_dead_letters,
)
from app.modules.safety.service.hazard_direct.quality_metrics import (
    SCENARIO,
    analyze_rows,
    baseline_comparison,
)

logger = logging.getLogger(__name__)

# 看板允许的窗口（天）；与 P0-C 基线对照口径一致的是 30d
ALLOWED_WINDOWS = (7, 30)
# 窗口行数上限（与 replay SQL 的 LIMIT 同值，防异常放量拖垮聚合）
_WINDOW_ROW_LIMIT = 5000


async def build_quality_dashboard(
    db: AsyncSession, *, days: int = 30, redis: RedisLike | None = None
) -> dict[str, Any]:
    """质量看板数据（实时聚合）。

    Args:
        db: 只读会话（窗口查询 ai_call_audits）。
        days: 时间窗（天），调用方（API 层）负责校验 ∈ ALLOWED_WINDOWS。
        redis: 死信账本客户端；None 时由 failure_ledger 解析默认客户端。

    返回结构见 spec §4.2（window/totals/citation/retrieval/gate_categories/
    repair_stages/by_day/rerun_records/baseline/dead_letters）。
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    stmt = (
        select(
            AICallAudit.created_at,
            AICallAudit.degradation_level,
            AICallAudit.input_text,
            AICallAudit.output_text,
            AICallAudit.extra,
        )
        .where(
            AICallAudit.scenario == SCENARIO,
            AICallAudit.output_text.is_not(None),
            AICallAudit.created_at >= cutoff,
        )
        .order_by(AICallAudit.created_at.asc())
        .limit(_WINDOW_ROW_LIMIT)
    )
    result = await db.execute(stmt)
    rows = [dict(row) for row in result.mappings().all()]

    stats = analyze_rows(rows)
    return {
        "window": {
            "days": days,
            "from": cutoff.isoformat(),
            "to": now.isoformat(),
        },
        "totals": stats["totals"],
        "citation": stats["citation"],
        "retrieval": stats["retrieval"],
        "gate_categories": stats["gate_categories"],
        "repair_stages": stats["repair_stages"],
        "by_day": stats["by_day"],
        "rerun_records": stats["rerun_records"],
        "baseline": baseline_comparison(stats),
        "dead_letters": await _dead_letter_watermark(redis),
    }


async def _dead_letter_watermark(redis: RedisLike | None) -> dict[str, Any]:
    """死信水位（数量+清单）；ledger 自身异常时 count=None（水位未知）。"""
    try:
        items = await list_dead_letters(redis=redis)
    except Exception:
        logger.warning("质量看板死信水位读取失败，降级为未知", exc_info=True)
        return {"count": None, "items": []}
    return {"count": len(items), "items": items}


async def build_exception_review_dashboard(
    db: AsyncSession, *, days: int = 30, redis: RedisLike | None = None
) -> dict[str, Any]:
    """例外复核 Tab（P1-3 E5，只读；不影响 P1-4 既有 dashboard 端点）。

    数据源：``ai_call_audits`` 窗口计数（已分析条数，口径=①场景非空输出行）
    + ``exception_reviewer`` Redis 报告 hash（窗口内复核报告）。

    口径说明（observe）：
    - ``exception_rate`` = 窗口内复核报告数 / 已分析条数（例外条数以「被
      复核的例外」计——失败账本不保留窗口化历史，这是当前可观测的诚实口径）；
    - ``rescued_rate`` = rescued 报告数 / 窗口内复核报告数（程序判定口径）；
    - ``dead_letters`` 复用既有水位函数（当前值，非窗口聚合）。
    """
    from sqlalchemy import func

    from app.modules.safety.service.hazard_direct.exception_reviewer import (
        REVIEWS_KEY,
        ExceptionReviewReport,
        summarize_exception_metrics,
    )

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    count_stmt = (
        select(func.count())
        .select_from(AICallAudit)
        .where(
            AICallAudit.scenario == SCENARIO,
            AICallAudit.output_text.is_not(None),
            AICallAudit.created_at >= cutoff,
        )
    )
    result = await db.execute(count_stmt)
    analyzed = int(result.scalar_one_or_none() or 0)

    reviews_available = True
    reports: list[ExceptionReviewReport] = []
    try:
        client = redis if redis is not None else _default_review_redis()
        raw = await client.hgetall(REVIEWS_KEY)
        for record_id, payload in (raw or {}).items():
            try:
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8", errors="replace")
                report = ExceptionReviewReport.model_validate_json(payload)
            except Exception:  # noqa: BLE001 — 单条脏数据跳过
                logger.warning("例外复核报告解析失败: field=%s", record_id)
                continue
            if report.observed_at >= cutoff:
                reports.append(report)
    except Exception:
        logger.warning("例外复核报告 Redis 读取失败，降级为空", exc_info=True)
        reviews_available = False

    reports.sort(key=lambda r: r.observed_at, reverse=True)
    metrics = summarize_exception_metrics(
        exception_count=len(reports),
        analyzed_count=analyzed,
        reviewed_count=len(reports),
        rescued_count=sum(1 for r in reports if r.rescued),
    )
    # ── P2-1 auto 维度（observe 批全为 0；既有键语义不变，向后兼容加键）──
    writeback_success = sum(1 for r in reports if r.writeback == "success")
    writeback_failed = sum(1 for r in reports if r.writeback == "failed")
    pending_confirm = sum(1 for r in reports if r.writeback == "pending_confirm")
    cas_conflict = sum(1 for r in reports if r.writeback == "cas_conflict")
    # 人工复核率（Q9A）：分子=需人工介入（确认等待+CAS 冲突+写失败），分母=已复核
    manual_needed = pending_confirm + cas_conflict + writeback_failed
    metrics.update(
        {
            "writeback_success": writeback_success,
            "writeback_failed": writeback_failed,
            "pending_confirm": pending_confirm,
            "cas_conflict": cas_conflict,
            "human_override_count": sum(1 for r in reports if r.human_feedback),
            "manual_review_rate": (
                round(manual_needed / len(reports), 4) if reports else 0.0
            ),
            "effective_rescued_rate": (
                round(
                    sum(1 for r in reports if r.effective_rescued) / len(reports), 4
                )
                if reports
                else 0.0
            ),
        }
    )
    # auto 升格达标提示（Q1C：近 14 天 effective_rescued 率≥60% 且样本≥10；
    # 只提示不强制——auto 开关永远人工开）
    hint_cutoff = now - timedelta(days=14)
    recent = [r for r in reports if r.observed_at >= hint_cutoff]
    rescued_rate_14d = (
        round(sum(1 for r in recent if r.effective_rescued) / len(recent), 4)
        if recent
        else 0.0
    )
    auto_hint = {
        "eligible": len(recent) >= 10 and rescued_rate_14d >= 0.6,
        "rescued_rate_14d": rescued_rate_14d,
        "samples_14d": len(recent),
    }
    return {
        "window": {"days": days, "from": cutoff.isoformat(), "to": now.isoformat()},
        "reviews_available": reviews_available,
        "metrics": metrics,
        "auto_hint": auto_hint,
        "dead_letters": await _dead_letter_watermark(redis),
        "items": [r.summary() for r in reports[:50]],
    }


def _default_review_redis() -> RedisLike:
    """默认 Redis 客户端（复用 exception_reviewer 的解析口；测试注入 fake）。"""
    from app.modules.safety.service.hazard_direct.exception_reviewer import (
        review_redis_client,
    )

    return review_redis_client()
