"""劳动合同定时任务：归档缺失周提醒（每周一 09:00）+ 批量挂接暂存清理。

汇总未归档合同扫描件（在职 + 离职，含已续签取代/已终止的原合同），按部门分组发
HR 卡片，提示到电子档案库导出补扫清单。配置走 hr_contract.*（labor_contract/settings.py）：
开关缺省开；接收人未配置时沿用 HR 抄送，两者都为空则不发。同轮清掉批量挂接预检后
超期未提交的暂存文件。任务挂载见 labor_contract/scheduled.py 的 register_labor_contract_tasks。
"""

import logging
from collections import Counter

from app.core.database import async_session_factory
from app.modules.hr.labor_contract import archive_batch_import as batch_import
from app.modules.hr.labor_contract import archive_service, notify
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract import settings as contract_settings
from app.modules.hr.reminder.config import resolve_receivers
from app.platform.scheduler import (
    ScheduleConfig,
    ScheduleStrategy,
    TaskDefinition,
)

logger = logging.getLogger(__name__)


async def run_archive_reminder() -> None:
    """每周一：未归档合同按部门汇总，发 HR 卡片；顺带清理批量挂接的超期暂存文件。"""
    try:
        removed = batch_import.cleanup_stale_staging()
        if removed:
            logger.info("合同批量挂接超期暂存清理: %d 个文件", removed)
    except Exception:  # noqa: BLE001 — 清理失败不应影响提醒本身
        logger.exception("合同批量挂接暂存清理失败")

    async with async_session_factory() as db:
        kv = await contract_settings.load_contract_settings(db)
        if not contract_settings.archive_reminder_enabled(kv):
            logger.info("合同归档缺失提醒已停用（hr_contract.archive_reminder_enabled=false）")
            return
        unarchived = await repo.list_unarchived(db)
        if not unarchived:
            await db.rollback()
            return
        departed = await archive_service.resolve_departed(db, unarchived)
        receivers = await resolve_receivers(
            db, contract_settings.archive_reminder_receivers(kv)
        )
        # 计数必须在 rollback 之前算完：回滚会让 ORM 实例过期，异步下再读属性会抛 MissingGreenlet
        total = len(unarchived)
        departed_count = sum(c.employee_number in departed for c in unarchived)
        department_counts = Counter(c.department for c in unarchived)
        await db.rollback()  # 只读汇总，不落任何变更

        sent = await notify.send_archive_summary(
            in_service_count=total - departed_count,
            departed_count=departed_count,
            department_counts=department_counts.most_common(),
            receivers=receivers,
        )
        logger.info(
            "合同归档缺失提醒: 未归档 %d（在职 %d / 离职 %d），送达 %d",
            total, total - departed_count, departed_count, sent,
        )


ARCHIVE_REMINDER_TASK = TaskDefinition(
    name="hr.contract.archive_reminder",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.CRON, expression="0 9 * * 1", timezone="Asia/Shanghai",
    ),
    coro=run_archive_reminder,
    settings_toggle_key="",
    module="hr",
)
