"""定时任务运行日志读写（Agent 任务运行中心，3.0 四期 1-D）。

- record_task_run：写一行运行记录（session 由调用方给，测试走回滚 session）；
- record_task_run_fail_open：调度器挂钩用，自开短命 session，失败仅记日志
  （留痕绝不影响任务本体）；
- load_run_overview：监督页端点数据（每任务最近一次 + 全局最近历史）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import SchedulerTaskRunLog

logger = logging.getLogger(__name__)

_ERROR_MAX_CHARS = 500


def _truncate(text: str) -> str:
    """截断到上限，超长尾注省略号（单一截断点，防双重截断削掉省略号）。"""
    return text if len(text) <= _ERROR_MAX_CHARS else text[:_ERROR_MAX_CHARS] + "…"


def error_summary(exc: BaseException | None = None, text: str | None = None) -> str | None:
    """异常 → 「类型: 消息」摘要（截断，尾注省略号）。"""
    raw = f"{type(exc).__name__}: {exc}".strip() if exc is not None else (text or "")
    if not raw:
        return None
    return _truncate(raw)


def _row_out(row: SchedulerTaskRunLog) -> dict[str, Any]:
    return {
        "job_name": row.job_name,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "status": row.status,
        "duration_ms": row.duration_ms,
        "error": row.error,
    }


async def record_task_run(
    db: AsyncSession,
    *,
    job_name: str,
    started_at: datetime,
    status: str,
    error: str | None = None,
) -> SchedulerTaskRunLog:
    """写入一次运行记录（flush 不 commit，事务边界归调用方）。"""
    finished_at = datetime.now(UTC)
    log = SchedulerTaskRunLog(
        job_name=job_name,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        duration_ms=int((finished_at - started_at).total_seconds() * 1000),
        error=_truncate(error) if error else None,
    )
    db.add(log)
    await db.flush()
    return log


async def record_task_run_fail_open(
    *,
    job_name: str,
    started_at: datetime,
    status: str,
    error: str | None = None,
) -> None:
    """调度挂钩专用：独立短命 session 落一行运行日志，失败仅告警不抛。"""
    try:
        from app.core.database import async_session_factory

        async with async_session_factory() as session:
            await record_task_run(
                session,
                job_name=job_name,
                started_at=started_at,
                status=status,
                error=error,
            )
            await session.commit()
    except Exception:
        logger.warning(
            "任务运行日志写入失败（忽略，不影响任务本体）: %s", job_name, exc_info=True
        )


async def load_run_overview(
    db: AsyncSession, *, recent_limit: int = 100
) -> dict[str, Any]:
    """监督页任务运行中心数据：每任务最近一次（DISTINCT ON）+ 全局最近 N 条。"""
    latest_rows = (
        await db.execute(
            select(SchedulerTaskRunLog)
            .distinct(SchedulerTaskRunLog.job_name)
            .where(SchedulerTaskRunLog.is_deleted.is_(False))
            .order_by(SchedulerTaskRunLog.job_name, SchedulerTaskRunLog.started_at.desc())
        )
    ).scalars().all()
    recent_rows = (
        await db.execute(
            select(SchedulerTaskRunLog)
            .where(SchedulerTaskRunLog.is_deleted.is_(False))
            .order_by(SchedulerTaskRunLog.started_at.desc())
            .limit(recent_limit)
        )
    ).scalars().all()
    return {
        "latest_by_job": {r.job_name: _row_out(r) for r in latest_rows},
        "recent": [_row_out(r) for r in recent_rows],
    }
