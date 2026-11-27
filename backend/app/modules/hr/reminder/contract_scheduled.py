"""合同到期定时提醒：每天 09:10 扫描 N 天内合同到期（含已过期未续签）的在职人员，飞书提醒 HR。

数据源：员工档案第一次合同（Employee.contract_end_date）+ 入职台账四组
合同起止（OnboardingRecord.contract_end_date/_2/_3/_4），按工号合并去重、
每工号只报一个到期日——口径：取该工号所有合同结束日期里「今天及以后」
最早的一个（当前周期合同的下一个到期日）；若全部已过期则取最晚的过期
日期（已过期未续签，更需要提醒）。

配置存 hr.system_settings（系统设置页「人事提醒配置」卡片）：
- hr_reminder.contract_expiry.enabled    缺省 true
- hr_reminder.contract_expiry.open_ids   接收人（姓名或 open_id，逗号分隔）
- hr_reminder.contract_expiry.days_ahead 提前天数，缺省 30

未配置接收人仅记日志（与转正提醒一致）。去重：以「工号 + 到期日窗口」
为口径，同一天内由调度器 FIXED_TIME 保证至多一轮，续签后下一次扫描
自然出窗。
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.hr.models import Employee, OnboardingRecord
from app.modules.hr.reminder.config import load_reminder_config, resolve_receivers
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

logger = logging.getLogger(__name__)

REMIND_TIME_OF_DAY = "09:10"
DEFAULT_DAYS_AHEAD = 30
REMINDER_TYPE = "contract_expiry"


@dataclass(slots=True)
class _ContractDue:
    employee_number: str
    name: str
    department: str
    end_date: date


def _pick_due_date(dates: list[date], deadline: date, today: date) -> date | None:
    """从一人工号的多份合同结束日期里挑出要提醒的那一个。

    - 有今天及以后的日期：取最早一个（当前合同的到期日），仅在窗口内才提醒
    - 全部已过期：取最晚的过期日期（已过期未续签，始终提醒）
    """
    upcoming = sorted(d for d in dates if d >= today)
    if upcoming:
        return upcoming[0] if upcoming[0] <= deadline else None
    return max(dates) if dates else None


async def run_contract_reminder() -> None:
    async with async_session_factory() as db:
        config = await load_reminder_config(db, REMINDER_TYPE, default_days_ahead=DEFAULT_DAYS_AHEAD)
        if not config.enabled:
            logger.info("合同到期提醒已停用（system_settings: hr_reminder.%s.enabled=false）", REMINDER_TYPE)
            return
        days_ahead = config.days_ahead or DEFAULT_DAYS_AHEAD
        today = date.today()
        deadline = today + timedelta(days=days_ahead)

        # 工号 → 合同结束日期池 + 展示信息（员工档案优先，入职台账兜底姓名/部门）
        date_pool: dict[str, list[date]] = {}
        info: dict[str, tuple[str, str]] = {}
        left_numbers: set[str] = set()

        employees = (await db.execute(
            select(Employee).where(Employee.is_deleted.is_(False))
        )).scalars().all()
        for e in employees:
            if e.status == "离职":
                left_numbers.add(e.employee_number)
                continue
            if e.contract_end_date is not None:
                date_pool.setdefault(e.employee_number, []).append(e.contract_end_date)
                info[e.employee_number] = (e.name, e.department or "")

        onboarding = (await db.execute(
            select(OnboardingRecord).where(OnboardingRecord.is_deleted.is_(False))
        )).scalars().all()
        for rec in onboarding:
            if rec.employee_number in left_numbers:
                continue
            ends = [d for d in (
                rec.contract_end_date, rec.contract_end_2, rec.contract_end_3, rec.contract_end_4,
            ) if d is not None]
            if not ends:
                continue
            date_pool.setdefault(rec.employee_number, []).extend(ends)
            info.setdefault(rec.employee_number, (rec.name, rec.department or ""))

        due: list[_ContractDue] = []
        for number, dates in date_pool.items():
            picked = _pick_due_date(dates, deadline, today)
            if picked is None:
                continue
            name, department = info.get(number, (number, ""))
            due.append(_ContractDue(number, name, department, picked))
        if not due:
            return

        due.sort(key=lambda x: x.end_date)
        lines = [
            f"- {d.name}（{d.department} · 工号 {d.employee_number} · 到期 {d.end_date}，"
            f"{'已过期 ' + str((today - d.end_date).days) + ' 天' if d.end_date < today else '剩 ' + str((d.end_date - today).days) + ' 天'}）"
            for d in due
        ]
        logger.info("合同到期提醒：%d 人在 %d 天窗口内到期（或已过期）", len(due), days_ahead)

        receivers = await resolve_receivers(db, config.receivers)
        if not receivers:
            logger.info(
                "未配置提醒接收人（system_settings: hr_reminder.%s.open_ids），跳过推送（仅日志）",
                REMINDER_TYPE,
            )
            return

        from app.platform.integrations.feishu.notification import send_user_card

        card = {
            "schema": "2.0",
            "header": {"title": {"tag": "plain_text", "content": "合同到期提醒"}, "template": "blue"},
            "body": {"elements": [
                {"tag": "markdown", "content": (
                    f"以下 **{len(due)}** 名员工合同 {days_ahead} 天内到期（或已过期未续签），"
                    f"请及时安排续签：\n\n" + "\n".join(lines)
                )},
            ]},
        }
        for open_id in receivers:
            try:
                await send_user_card(open_id, card=card)
            except Exception as e:  # noqa: BLE001
                logger.warning("合同到期提醒发送失败 open_id=%s: %s", open_id, e)


CONTRACT_REMINDER_TASK = TaskDefinition(
    name="hr.contract.reminder",
    schedule=ScheduleConfig(strategy=ScheduleStrategy.FIXED_TIME, time_of_day=REMIND_TIME_OF_DAY),
    coro=run_contract_reminder,
    timeout_seconds=60,
    module="hr",
)
