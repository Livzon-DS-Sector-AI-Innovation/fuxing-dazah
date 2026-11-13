"""试用期转正定时任务：每天 09:00 扫描 7 天内到期且无进行中评估的员工，飞书提醒 HR。

提醒接收人存 hr.system_settings 键 probation_reminder.open_ids（逗号分隔
open_id，系统设置界面可直接改，参照 employee_sync 的 KV 模式），未配置仅记
日志——前端转正面板/员工列表倒计时始终可见，不依赖推送。
去重：以「到期日窗口 + 无进行中评估」为口径，评估发起后自然不再提醒；
同一员工同一天重复运行由调度器 FIXED_TIME 保证至多一轮（重启补跑场景
最多多发一次提醒卡，可接受）。
"""

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.hr.models import Employee, ProbationReview, SystemSetting
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

logger = logging.getLogger(__name__)

REMIND_TIME_OF_DAY = "09:00"
REMIND_DAYS_AHEAD = 7

KEY_REMINDER_OPEN_IDS = "probation_reminder.open_ids"


async def _load_reminder_open_ids(db: AsyncSession) -> list[str]:
    """读取提醒接收人 KV（缺省=空，仅日志不推送）。"""
    row = (await db.execute(
        select(SystemSetting).where(
            SystemSetting.key == KEY_REMINDER_OPEN_IDS,
            SystemSetting.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    raw = (row.value if row else None) or ""
    return [x.strip() for x in raw.split(",") if x.strip()]


async def run_probation_reminder() -> None:
    async with async_session_factory() as db:
        receivers = await _load_reminder_open_ids(db)
        # 试用期（含各类试用性质）且未软删的在职员工
        employees = (await db.execute(
            select(Employee).where(
                Employee.is_deleted.is_(False),
                Employee.status == "试用期",
                Employee.status_category.in_(("试用期", "实习转试用", "实习生")),
            )
        )).scalars().all()
        active_ids = set((await db.execute(
            select(ProbationReview.employee_id).where(
                ProbationReview.status.in_(("pending_reviewer", "pending_hr")),
                ProbationReview.is_deleted.is_(False),
            )
        )).scalars().all())

        deadline = date.today() + timedelta(days=REMIND_DAYS_AHEAD)
        due = [
            e for e in employees
            if e.id not in active_ids
            and e.computed_probation_end is not None
            and e.computed_probation_end <= deadline
        ]
        if not due:
            return

        lines = [
            f"- {e.name}（{e.department} · 到期 {e.computed_probation_end}，"
            f"{'已过期 ' + str(abs(e.computed_probation_days_left)) + ' 天' if (e.computed_probation_days_left or 0) < 0 else '剩 ' + str(e.computed_probation_days_left) + ' 天'}）"
            for e in due
        ]
        logger.info("试用期到期提醒：%d 名员工 7 天内到期", len(due))

        if not receivers:
            logger.info("未配置提醒接收人（system_settings: %s），跳过推送（仅日志）", KEY_REMINDER_OPEN_IDS)
            return

        from app.platform.integrations.feishu.notification import send_user_card

        card = {
            "schema": "2.0",
            "header": {"title": {"tag": "plain_text", "content": "试用期转正提醒"}, "template": "orange"},
            "body": {"elements": [
                {"tag": "markdown", "content": (
                    f"以下 **{len(due)}** 名员工试用期 7 天内到期（或已过期），"
                    f"请在员工档案页发起转正评估：\n\n" + "\n".join(lines)
                )},
            ]},
        }
        for open_id in receivers:
            try:
                await send_user_card(open_id, card=card)
            except Exception as e:  # noqa: BLE001
                logger.warning("转正提醒发送失败 open_id=%s: %s", open_id, e)


PROBATION_REMINDER_TASK = TaskDefinition(
    name="hr.probation.reminder",
    schedule=ScheduleConfig(strategy=ScheduleStrategy.FIXED_TIME, time_of_day=REMIND_TIME_OF_DAY),
    coro=run_probation_reminder,
    timeout_seconds=60,
    module="hr",
)
