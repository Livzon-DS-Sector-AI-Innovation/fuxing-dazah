"""员工档案同步定时任务：5 分钟兜底对账（WS 事件丢失时的补偿）。

任务无条件注册，运行时读 DB 配置：未启用直接返回，无需 env 开关。
"""

import logging

from app.core.database import async_session_factory
from app.modules.hr.employee_sync.config import load_config
from app.modules.hr.employee_sync.service import EmployeeSyncService
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

logger = logging.getLogger(__name__)


async def run_employee_sync() -> None:
    """全量对账（源表 → 本地 → 脱敏表）。同步进行中时静默跳过本轮。"""
    async with async_session_factory() as db:
        cfg = await load_config(db)
        if not cfg.is_ready:
            return
        service = EmployeeSyncService(db)
        try:
            stats = await service.reconcile(cfg)
            if any(stats.get(k) for k in ("created", "updated", "deleted", "errors")):
                logger.info("员工档案对账完成: %s", stats)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("员工档案对账失败")


EMPLOYEE_SYNC_TASK = TaskDefinition(
    name="hr.employee_sync.reconcile",
    schedule=ScheduleConfig(strategy=ScheduleStrategy.INTERVAL, interval_seconds=300),
    coro=run_employee_sync,
    timeout_seconds=280,
    module="hr",
)
