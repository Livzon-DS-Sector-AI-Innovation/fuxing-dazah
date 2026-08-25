"""职称评审定时任务：5 分钟兜底对账（WS 事件丢失时的补偿）。"""

import logging

from app.core.database import async_session_factory
from app.modules.hr.title_review.service import TitleReviewService
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

logger = logging.getLogger(__name__)


async def run_reconcile_all() -> None:
    """对进行中（open/reviewing）的活动逐一执行双向对账。"""
    async with async_session_factory() as db:
        service = TitleReviewService(db)
        activities = await service.activity_repo.list_active()
        for activity in activities:
            try:
                stats = await service.reconcile_activity(activity.id)
                if any(stats.values()):
                    logger.info("活动对账完成: activity=%s stats=%s", activity.id, stats)
            except Exception:
                logger.exception("活动对账失败: activity_id=%s", activity.id)
                # 回滚本活动产生的脏状态，避免后续活动触发 PendingRollbackError
                await db.rollback()
        await db.commit()


TITLE_REVIEW_SYNC_TASK = TaskDefinition(
    name="hr.title_review.reconcile",
    schedule=ScheduleConfig(strategy=ScheduleStrategy.INTERVAL, interval_seconds=300),
    coro=run_reconcile_all,
    timeout_seconds=300,
    module="hr",
)
