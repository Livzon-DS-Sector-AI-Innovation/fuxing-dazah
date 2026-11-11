"""员工档案同步定时任务：每天凌晨 02:00 全量对账（手动同步可随时触发）。

任务无条件注册，运行时读 DB 配置：未启用直接返回，无需 env 开关。
调度器的 last_run 不跨重启：启动时刻晚于 02:00 会立即触发一次，
由 _synced_today 守卫按 last_sync_at 去重——今天已同步过（含手动）
就跳过，服务停机错过 02:00 则在下次启动时补跑一次，始终每天至多一轮。
"""

import logging
from datetime import datetime

from app.core.database import async_session_factory
from app.modules.hr.employee_sync.config import EmployeeSyncConfig, load_config
from app.modules.hr.employee_sync.service import EmployeeSyncService
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

logger = logging.getLogger(__name__)

SYNC_TIME_OF_DAY = "02:00"


def _synced_today(cfg: EmployeeSyncConfig, now: datetime) -> bool:
    """今天 02:00 之后已同步过（含手动同步）→ 本轮跳过。"""
    if not cfg.last_sync_at:
        return False
    try:
        last = datetime.fromisoformat(cfg.last_sync_at)
    except ValueError:
        return False
    window_start = now.replace(hour=2, minute=0, second=0, microsecond=0)
    return last.date() == now.date() and last >= window_start


async def run_employee_sync() -> None:
    """全量对账（源表 → 本地 → 脱敏名单）。同步进行中时静默跳过本轮。"""
    async with async_session_factory() as db:
        cfg = await load_config(db)
        if not cfg.is_ready or _synced_today(cfg, datetime.now()):
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
    schedule=ScheduleConfig(strategy=ScheduleStrategy.FIXED_TIME, time_of_day=SYNC_TIME_OF_DAY),
    coro=run_employee_sync,
    timeout_seconds=280,
    module="hr",
)
