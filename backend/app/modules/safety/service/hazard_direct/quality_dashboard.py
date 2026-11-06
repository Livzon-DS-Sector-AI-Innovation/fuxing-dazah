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
