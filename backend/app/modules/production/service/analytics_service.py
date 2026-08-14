"""生产分析服务。"""

import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now
from app.modules.production import repository as repo
from app.modules.production.schemas.analytics import StepCycleResponse, StepCycleStat

_MIN_SAMPLE_FOR_CONFIDENCE = 30


async def get_step_cycle_analytics(
    db: AsyncSession,
    *,
    route_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    days: int = 30,
) -> StepCycleResponse:
    """获取路线/产品的工序周期统计。"""
    since = now() - timedelta(days=days) if days > 0 else None

    rows = await repo.get_step_cycle_stats(
        db, route_id=route_id, product_id=product_id, since=since,
    )
    total_batches = await repo.count_active_batches(
        db, route_id=route_id, product_id=product_id, since=since,
    )

    steps = [
        StepCycleStat(
            node_id=r["node_id"],
            node_name=r["node_name"],
            stage_name=r["stage_name"],
            sort_order=r["sort_order"],
            n=r["n"],
            avg_hours=r["avg_hours"],
            min_hours=r["min_hours"],
            max_hours=r["max_hours"],
        )
        for r in rows
    ]

    min_n = min((s.n for s in steps), default=0)
    sample_note = None
    if min_n == 0:
        sample_note = "暂无数据"
    elif min_n < _MIN_SAMPLE_FOR_CONFIDENCE:
        sample_note = f"数据较少（最少工序仅 {min_n} 条记录），仅供参考"

    return StepCycleResponse(steps=steps, total_batches=total_batches, sample_note=sample_note)
