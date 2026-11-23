"""员工档案同步定时任务：每小时整点全量对账（手动同步可随时触发）。

原为每天 02:00 一轮；转正审批/证件缺件/试用期节点都依赖源表数据的
及时性，改为每小时整点全量对账。任务无条件注册，运行时读 DB 配置：
未启用直接返回，无需 env 开关。

调度器的 last_run 不跨重启：启动晚于整点会立即触发一次，
由 _synced_recently 守卫按 last_sync_at 去重——距上次同步（含手动）
不足最小间隔就跳过，服务停机错过整点则下次启动补跑一轮，
始终每小时至多一轮。对账本身幂等（按 feishu_record_id upsert），
且带同步锁防并发，重复触发无害。
"""

import logging
from datetime import datetime

from app.core.database import async_session_factory
from app.modules.hr.employee_sync.config import EmployeeSyncConfig, load_config
from app.modules.hr.employee_sync.service import EmployeeSyncService
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

logger = logging.getLogger(__name__)

# 每小时整点；守卫间隔略小于 60 分钟，避免整点抖动导致某轮被跳过
CRON_EXPRESSION = "0 * * * *"
MIN_SYNC_INTERVAL_MINUTES = 55


def _synced_recently(cfg: EmployeeSyncConfig, now: datetime) -> bool:
    """距上次同步（含手动）不足最小间隔 → 本轮跳过。"""
    if not cfg.last_sync_at:
        return False
    try:
        last = datetime.fromisoformat(cfg.last_sync_at)
    except ValueError:
        return False
    return (now - last).total_seconds() < MIN_SYNC_INTERVAL_MINUTES * 60


async def run_employee_sync() -> None:
    """全量对账（源表 → 本地 → 脱敏名单）。同步进行中时静默跳过本轮。"""
    async with async_session_factory() as db:
        cfg = await load_config(db)
        if not cfg.is_ready or _synced_recently(cfg, datetime.now()):
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
    schedule=ScheduleConfig(strategy=ScheduleStrategy.CRON, expression=CRON_EXPRESSION),
    coro=run_employee_sync,
    timeout_seconds=280,
    module="hr",
)
