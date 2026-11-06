"""检定到期飞书提醒（每 60 秒检查一次，按数据库中设定的时间触发）。

防重复策略：
- 记录上次实际发送的日期时间（last_sent_at，timestamptz）
- 「今天 + 当前设定时间」的时刻已到且尚未发送过才发送
- 与整分钟精确匹配不同，即使某轮扫描因上一轮执行超时跳过了设定分钟，
  下一轮仍会补发，不会静默丢掉当天的提醒
- 用户把提醒时间改到当天更早的时刻：当天已发过则不再发；改到未来
  时刻则在新时刻到达后正常触发
"""

import logging
from datetime import datetime, timedelta

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.time import APP_TZ
from app.core.time import now as time_now
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

logger = logging.getLogger(__name__)


async def calibration_reminder_coro() -> None:
    """由 SchedulerEngine 调用的零参协程。

    每 60 秒触发一次，在函数内部比对数据库中的 notify_time 与当前时间，
    只有「今天 + 当前设定时间」时刻已到且未发送过才发送。
    """
    settings = get_settings()
    if not settings.METER_CALIBRATION_AUTO_NOTIFY_ENABLED:
        return

    try:
        async with async_session_factory() as db:
            from app.modules.meter import repository as repo

            meter_cfg = await repo.get_or_create_meter_settings(db)
            now = time_now()
            # 今天 + 当前设定时间（Asia/Shanghai 语义的 aware 时刻）
            target = datetime.combine(now.date(), meter_cfg.notify_time, tzinfo=APP_TZ)

            if now < target:
                await db.rollback()
                return

            # 今天该时刻已发送过（比较绝对时刻，与存储时区表示无关）
            if meter_cfg.last_sent_at is not None and meter_cfg.last_sent_at >= target:
                await db.rollback()
                return

            # 发送通知；异常也走同一套「30 分钟内重试 / 超窗放弃」判定，
            # 否则 now >= target 的补发门会让异常每分钟重试到当天结束
            from app.modules.meter.service import send_calibration_reminders

            rolled_back = False
            try:
                result = await send_calibration_reminders(db)
            except Exception:
                logger.exception("检定到期提醒发送异常")
                # 回滚失败事务：否则后面落标记的 commit 会一直失败、无限重试
                await db.rollback()
                rolled_back = True
                result = {"sent": 0, "skipped": 0, "errors": 1, "delivered": 0}

            # 标记「今天已处理」的条件：已送达任意一张卡片、扫描本身无错误
            # （无到期记录等正常空跑立即落标记）、或超过 30 分钟重试窗口。
            # 用 delivered 而不是 sent：部门内部分负责人失败时，已收到的人
            # 不能因重试每分钟再收一遍（sent 只统计整个部门全成功）
            handled = (
                result["delivered"] > 0
                or result["errors"] == 0
                or now >= target + timedelta(minutes=30)
            )
            if handled:
                meter_cfg.last_sent_at = now
                await db.commit()
            elif not rolled_back:
                await db.rollback()

            logger.info(
                "检定到期提醒完成: sent=%d, skipped=%d, errors=%d",
                result["sent"], result["skipped"], result["errors"],
            )
    except Exception:
        logger.exception("检定到期提醒定时任务异常")


CALIBRATION_REMINDER_TASK = TaskDefinition(
    name="meter.calibration_reminder",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=60,
    ),
    coro=calibration_reminder_coro,
    module="meter",
)
