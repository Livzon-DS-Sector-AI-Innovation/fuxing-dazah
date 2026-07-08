"""检定到期飞书提醒（每 60 秒检查一次，按数据库中设定的时间触发）。

防重复策略：
- 记录上次实际发送的日期时间（last_sent_at）
- 只有当"今天 + 当前设定的时间"已经推送过才跳过
- 用户修改提醒时间后，新时间点会正常触发推送
"""

import logging
from datetime import datetime

from app.core.config import get_settings
from app.core.database import async_session_factory

logger = logging.getLogger(__name__)


async def calibration_reminder_coro() -> None:
    """由 SchedulerEngine 调用的零参协程。

    每 60 秒触发一次，在函数内部比对数据库中的 notify_time 与当前时间，
    只有"今天 + 当前设定时间"组合未发送时才发送。
    """
    settings = get_settings()
    if not settings.METER_CALIBRATION_AUTO_NOTIFY_ENABLED:
        return

    try:
        async with async_session_factory() as db:
            from app.modules.meter import repository as repo

            meter_cfg = await repo.get_or_create_meter_settings(db)
            now = datetime.now()
            target = meter_cfg.notify_time  # datetime.time object

            # 检查是否到了设定的时间（精确到分钟）
            if now.hour != target.hour or now.minute != target.minute:
                await db.rollback()
                return

            # 检查"今天 + 当前设定时间"是否已发送过
            if meter_cfg.last_sent_at is not None:
                sent_at = meter_cfg.last_sent_at
                if (
                    sent_at.date() == now.date()
                    and sent_at.hour == target.hour
                    and sent_at.minute == target.minute
                ):
                    await db.rollback()
                    return

            # 发送通知
            from app.modules.meter.service import send_calibration_reminders

            result = await send_calibration_reminders(db)

            # 只有实际发送成功时才标记，避免空跑阻塞后续重试
            if result["sent"] > 0:
                meter_cfg.last_sent_at = now
                await db.commit()
            else:
                await db.rollback()

            logger.info(
                "检定到期提醒完成: sent=%d, skipped=%d, errors=%d",
                result["sent"], result["skipped"], result["errors"],
            )
    except Exception:
        logger.exception("检定到期提醒定时任务异常")
