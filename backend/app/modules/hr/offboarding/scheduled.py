"""离职管理定时任务：飞书审批结果轮询（每 15 分钟）+ 两类节点提醒（每天定点）。

节点提醒走人事提醒框架的 KV 配置（hr_reminder.<type>.enabled / open_ids / days_ahead），
扫描规则见 reminders.py。与其它人事提醒一致：未配置接收人时只在服务端记日志、不推送
——部门负责人是「在 HR 配置的接收人之外追加」的，不会因为没人配置就被单独打扰。
"""

import logging
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.hr.offboarding import approval, reminders
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding import settings as offboarding_settings
from app.modules.hr.offboarding.models import OffboardingCase
from app.modules.hr.reminder.config import load_reminder_config, resolve_receivers
from app.modules.hr.title_review.notify import _lookup_open_id
from app.platform.scheduler import (
    ScheduleConfig,
    SchedulerRegistry,
    ScheduleStrategy,
    TaskDefinition,
)

logger = logging.getLogger(__name__)

# 错开既有人事提醒（转正 09:00 / 合同公告期 09:05 / 合同到期 09:10）
LEAD_REMIND_TIME_OF_DAY = "09:20"
CLEARANCE_DUE_REMIND_TIME_OF_DAY = "09:30"


# ─── 审批编排：结果轮询 ───

async def run_approval_sync() -> None:
    """每 15 分钟：轮询回写离职审批/清退会签结果（幂等），办结自动推进；
    顺带把已到建议发起日（离职日前 2 天）仍挂起的清退交接发起出去。"""
    async with async_session_factory() as db:
        try:
            counts = await approval.sync_pending_results(db)
            launched = await approval.initiate_deferred_clearance(db, today=date.today())
        except Exception as exc:  # 整轮失败只跳过本轮，下一轮重试
            logger.warning("离职审批轮询失败（本轮跳过）: %s", exc)
            await db.rollback()
            return
        if any(counts.values()) or launched:
            await db.commit()
            logger.info("离职审批结果回写: %s，到期自动发起清退交接 %d 单", counts, launched)
        else:
            await db.rollback()


# ─── 节点提醒 ───

async def _send_to_all(open_ids: set[str], card: dict[str, Any], label: str) -> int:
    from app.platform.integrations.feishu.notification import send_user_card

    sent = 0
    for open_id in open_ids:
        try:
            if await send_user_card(open_id, card=card):
                sent += 1
        except Exception as exc:  # 单个接收人失败不影响其余
            logger.warning("%s发送失败 open_id=%s: %s", label, open_id, exc)
    return sent


async def _department_manager_open_ids(
    db: AsyncSession, departments: set[str],
) -> set[str]:
    """部门负责人 open_id：部门表负责人姓名 → identity 解析，解析不到的跳过。"""
    open_ids: set[str] = set()
    for name in await repo.list_department_manager_names(db, departments):
        open_id = await _lookup_open_id(name)
        if open_id:
            open_ids.add(open_id)
        else:
            logger.warning("离职提醒：部门负责人按姓名解析失败，跳过 %s", name)
    return open_ids


async def run_lead_reminder() -> None:
    """每天：已定离职日但未发起办理、临近/超过应发起时限的员工 → 提醒 HR 与部门负责人。"""
    async with async_session_factory() as db:
        config = await load_reminder_config(
            db, reminders.REMINDER_LEAD, default_days_ahead=reminders.DEFAULT_LEAD_BUFFER_DAYS,
        )
        if not config.enabled:
            logger.info("离职发起时限提醒已停用（hr_reminder.%s.enabled=false）", reminders.REMINDER_LEAD)
            return
        kv = await offboarding_settings.load_offboarding_settings(db)
        lead_probation = offboarding_settings.lead_days(kv, probation=True)
        lead_resigned = offboarding_settings.lead_days(kv, probation=False)
        due = reminders.pick_lead_overdue(
            await repo.list_employees_with_departure_date(db),
            await repo.active_case_employee_numbers(db),
            today=date.today(),
            lead_probation=lead_probation,
            lead_resigned=lead_resigned,
            buffer_days=config.days_ahead or reminders.DEFAULT_LEAD_BUFFER_DAYS,
        )
        if not due:
            return
        logger.info("离职发起时限提醒：%d 人临近/超过应发起时限", len(due))
        receivers = await resolve_receivers(db, config.receivers)
        if not receivers:
            logger.info(
                "未配置提醒接收人（system_settings: hr_reminder.%s.open_ids），跳过推送（仅日志）",
                reminders.REMINDER_LEAD,
            )
            return
        managers = await _department_manager_open_ids(db, {item.department for item in due})
        sent = await _send_to_all(
            set(receivers) | managers,
            reminders.lead_card(due, lead_probation=lead_probation, lead_resigned=lead_resigned),
            "离职发起时限提醒",
        )
        logger.info("离职发起时限提醒已发送 %d 人（HR %d + 部门负责人 %d）",
                    sent, len(receivers), len(managers))


async def run_clearance_due_reminder() -> None:
    """每天：距离职日 ≤ 2 天仍停在审批/清退阶段的办结单 → 催办 HR 与部门负责人。"""
    async with async_session_factory() as db:
        config = await load_reminder_config(db, reminders.REMINDER_CLEARANCE_DUE)
        if not config.enabled:
            logger.info("离职手续催办已停用（hr_reminder.%s.enabled=false）", reminders.REMINDER_CLEARANCE_DUE)
            return
        due = reminders.pick_clearance_overdue(
            await repo.list_cases_in_statuses(
                db, (OffboardingCase.STATUS_APPROVING, OffboardingCase.STATUS_CLEARING),
            ),
            today=date.today(),
        )
        if not due:
            return
        logger.info("离职手续催办：%d 人距离职日不足仍未办结", len(due))
        receivers = await resolve_receivers(db, config.receivers)
        if not receivers:
            logger.info(
                "未配置提醒接收人（system_settings: hr_reminder.%s.open_ids），跳过推送（仅日志）",
                reminders.REMINDER_CLEARANCE_DUE,
            )
            return
        managers = await _department_manager_open_ids(db, {item.department for item in due})
        sent = await _send_to_all(
            set(receivers) | managers, reminders.clearance_card(due), "离职手续催办",
        )
        logger.info("离职手续催办已发送 %d 人（HR %d + 部门负责人 %d）", sent, len(receivers), len(managers))


# ─── 任务定义 ───

APPROVAL_SYNC_TASK = TaskDefinition(
    name="hr.offboarding.approval_sync",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=900
    ),
    coro=run_approval_sync,
    settings_toggle_key="",
    module="hr",
)

LEAD_REMINDER_TASK = TaskDefinition(
    name="hr.offboarding.lead_reminder",
    schedule=ScheduleConfig(strategy=ScheduleStrategy.FIXED_TIME, time_of_day=LEAD_REMIND_TIME_OF_DAY),
    coro=run_lead_reminder,
    timeout_seconds=60,
    module="hr",
)

CLEARANCE_DUE_REMINDER_TASK = TaskDefinition(
    name="hr.offboarding.clearance_due_reminder",
    schedule=ScheduleConfig(strategy=ScheduleStrategy.FIXED_TIME, time_of_day=CLEARANCE_DUE_REMIND_TIME_OF_DAY),
    coro=run_clearance_due_reminder,
    timeout_seconds=60,
    module="hr",
)


def register_offboarding_tasks(registry: SchedulerRegistry) -> None:
    """注册离职管理定时任务（hr/lifecycle.py 挂载，只在此处注册一次）。"""
    registry.register_task(APPROVAL_SYNC_TASK)
    registry.register_task(LEAD_REMINDER_TASK)
    registry.register_task(CLEARANCE_DUE_REMINDER_TASK)
