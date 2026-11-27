"""试用期转正定时任务（每天 09:00，单任务三段扫描）。

1. 7 天到期提醒 HR（原有规则保留兜底）：接收人存 hr.system_settings 键
   probation_reminder.open_ids（逗号分隔 open_id，系统设置界面可直接改），
   未配置仅记日志——前端转正面板/员工列表倒计时始终可见，不依赖推送。
   去重：以「到期日窗口 + 无进行中评估」为口径，评估发起后自然不再提醒；
   同一员工同一天重复运行由调度器 FIXED_TIME 保证至多一轮。
2. 重点岗位满 60 天安全考试提醒：提醒员工本人 + 对接 HR 参加安全办考试；
   每员工仅提醒一次（hr.probation_remind_logs 防重复轰炸），考试合格或
   评估发起后不再触发。
3. 转正前 30 天提醒部门负责人：关注试用期表现（不胜任须提前一个月书面
   通知本人），卡片带「发起转正评估」按钮（用人部门发起入口）；每员工
   仅提醒一次，进行中评估不提醒。
"""

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.hr.models import (
    Employee,
    HrDepartment,
    ProbationRemindLog,
    ProbationReview,
    ProbationSafetyExam,
    SystemSetting,
)
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

logger = logging.getLogger(__name__)

REMIND_TIME_OF_DAY = "09:00"
REMIND_DAYS_AHEAD = 7
DAYS_AHEAD_FOR_LEADER = 30
SAFETY_EXAM_DAYS_AFTER_HIRE = 60

KEY_REMINDER_OPEN_IDS = "probation_reminder.open_ids"

_PROBATION_CATEGORIES = ("试用期", "实习转试用", "实习生")


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


def _probation_employees_query():
    return select(Employee).where(
        Employee.is_deleted.is_(False),
        Employee.status == "试用期",
        Employee.status_category.in_(_PROBATION_CATEGORIES),
    )


async def _active_review_employee_ids(db: AsyncSession) -> set:
    from app.modules.hr.probation_service import ACTIVE_STATUSES

    return set((await db.execute(
        select(ProbationReview.employee_id).where(
            ProbationReview.status.in_(ACTIVE_STATUSES),
            ProbationReview.is_deleted.is_(False),
        )
    )).scalars().all())


async def _reminded_employee_ids(db: AsyncSession, remind_type: str) -> set:
    return set((await db.execute(
        select(ProbationRemindLog.employee_id).where(
            ProbationRemindLog.remind_type == remind_type,
            ProbationRemindLog.is_deleted.is_(False),
        )
    )).scalars().all())


def _record_remind(db: AsyncSession, employee_id, remind_type: str) -> None:
    db.add(ProbationRemindLog(
        employee_id=employee_id, remind_type=remind_type,
        reminded_at=datetime.now(UTC),
    ))


async def _resolve_employee_open_id(db: AsyncSession, employee: Employee) -> str | None:
    """员工本人 open_id：档案直存值优先，否则姓名解析。"""
    from app.modules.hr.probation_service import _resolve_open_id_by_name

    if employee.feishu_open_id:
        return employee.feishu_open_id
    return await _resolve_open_id_by_name(employee.name)


async def _send_user_card(open_id: str, card: dict) -> bool:
    from app.platform.integrations.feishu.notification import send_user_card

    try:
        await send_user_card(open_id, card=card)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("飞书卡片发送失败 open_id=%s: %s", open_id, e)
        return False


# ───────────────────────── 1. 7 天到期提醒 HR ─────────────────────────


async def _remind_hr_due_soon(db: AsyncSession, receivers: list[str]) -> None:
    employees = (await db.execute(_probation_employees_query())).scalars().all()
    active_ids = await _active_review_employee_ids(db)

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
    logger.info("试用期到期提醒：%d 名员工 %d 天内到期", len(due), REMIND_DAYS_AHEAD)

    if not receivers:
        logger.info("未配置提醒接收人（system_settings: %s），跳过推送（仅日志）", KEY_REMINDER_OPEN_IDS)
        return

    card = {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": "试用期转正提醒"}, "template": "orange"},
        "body": {"elements": [
            {"tag": "markdown", "content": (
                f"以下 **{len(due)}** 名员工试用期 {REMIND_DAYS_AHEAD} 天内到期（或已过期），"
                f"请在员工档案页发起转正评估：\n\n" + "\n".join(lines)
            )},
        ]},
    }
    for open_id in receivers:
        await _send_user_card(open_id, card)


# ─────────────────── 2. 重点岗位满 60 天安全考试提醒 ───────────────────


async def _remind_safety_exam_60d(db: AsyncSession, hr_receivers: list[str]) -> None:
    threshold = date.today() - timedelta(days=SAFETY_EXAM_DAYS_AFTER_HIRE)
    employees = (await db.execute(
        _probation_employees_query().where(Employee.is_key_position.is_(True))
    )).scalars().all()
    reminded = await _reminded_employee_ids(db, ProbationRemindLog.TYPE_SAFETY_EXAM_60D)
    passed_ids = set((await db.execute(
        select(ProbationSafetyExam.employee_id).where(
            ProbationSafetyExam.passed.is_(True),
            ProbationSafetyExam.is_deleted.is_(False),
        )
    )).scalars().all())

    due = [e for e in employees
           if e.id not in reminded and e.id not in passed_ids and e.hire_date <= threshold]
    if not due:
        return
    logger.info("60 天安全考试提醒：%d 名重点岗位员工待考试", len(due))

    sent_any = False
    for e in due:
        card = {
            "schema": "2.0",
            "header": {"title": {"tag": "plain_text", "content": "安全考试提醒（入职满60天）"}, "template": "orange"},
            "body": {"elements": [{"tag": "markdown", "content": (
                f"你（{e.name}）为重点岗位员工，入职已满 {SAFETY_EXAM_DAYS_AFTER_HIRE} 天，"
                f"请尽快参加安全办组织的安全考试。\n\n"
                f"考试合格后方可发起转正审批；结果由安全办录入系统。"
            )}]},
        }
        open_id = await _resolve_employee_open_id(db, e)
        if open_id and await _send_user_card(open_id, card):
            _record_remind(db, e.id, ProbationRemindLog.TYPE_SAFETY_EXAM_60D)
            sent_any = True
        else:
            logger.warning("60 天提醒发送失败，跳过记录（员工 %s 无 open_id）", e.name)
    if sent_any:
        await db.commit()

    if hr_receivers:
        lines = [f"- {e.name}（{e.department} · {e.position}，入职 {e.hire_date}）" for e in due]
        hr_card = {
            "schema": "2.0",
            "header": {"title": {"tag": "plain_text", "content": "重点岗位安全考试对接提醒"}, "template": "orange"},
            "body": {"elements": [{"tag": "markdown", "content": (
                f"以下 **{len(due)}** 名重点岗位员工入职满 {SAFETY_EXAM_DAYS_AFTER_HIRE} 天，"
                f"请对接安全办安排安全考试（已同步提醒员工本人）：\n\n" + "\n".join(lines)
            )}]},
        }
        for open_id in hr_receivers:
            await _send_user_card(open_id, hr_card)


# ─────────────── 3. 转正前 30 天提醒部门负责人（带发起按钮） ───────────────


async def _remind_leader_30d(db: AsyncSession) -> None:
    from app.modules.hr.probation_service import CARD_ACTION_START

    employees = (await db.execute(_probation_employees_query())).scalars().all()
    active_ids = await _active_review_employee_ids(db)
    reminded = await _reminded_employee_ids(db, ProbationRemindLog.TYPE_PROBATION_30D)

    deadline = date.today() + timedelta(days=DAYS_AHEAD_FOR_LEADER)
    due = [
        e for e in employees
        if e.id not in active_ids and e.id not in reminded
        and e.computed_probation_end is not None
        and e.computed_probation_end <= deadline
    ]
    if not due:
        return

    # 部门名 → 部门负责人姓名（hr.departments 配置）
    dept_rows = (await db.execute(
        select(HrDepartment.name, HrDepartment.department_manager_name).where(
            HrDepartment.is_deleted.is_(False),
            HrDepartment.department_manager_name.is_not(None),
        )
    )).all()
    manager_by_dept = {name: manager for name, manager in dept_rows}

    from app.modules.hr.probation_service import _resolve_open_id_by_name

    # 按部门负责人分组发卡（同一负责人的多名员工聚一张卡，每员工一个发起按钮）
    by_manager: dict[str, list[Employee]] = {}
    for e in due:
        manager = manager_by_dept.get(e.department)
        if not manager:
            logger.warning("30 天提醒跳过 %s（部门 %s 未配置负责人）", e.name, e.department)
            continue
        by_manager.setdefault(manager, []).append(e)

    for manager, members in by_manager.items():
        open_id = await _resolve_open_id_by_name(manager)
        if not open_id:
            logger.warning("30 天提醒跳过负责人 %s（无 open_id）", manager)
            continue
        lines = []
        for e in members:
            days = e.computed_probation_days_left
            days_text = (
                f"已过期 {abs(days)} 天" if days is not None and days < 0 else f"剩 {days} 天"
            )
            lines.append(
                f"- **{e.name}**（{e.position} · 转正到期 {e.computed_probation_end}，{days_text}）"
            )
        elements = [
            {"tag": "markdown", "content": (
                f"以下 **{len(members)}** 名员工试用期 30 天内到期，请关注其试用期表现；"
                f"经考核不胜任的，须提前一个月书面通知本人：\n\n" + "\n".join(lines)
            )},
        ]
        for e in members:
            elements.append({
                "tag": "action", "actions": [{
                    "tag": "button", "type": "primary",
                    "text": {"tag": "lark_md", "content": f"为 **{e.name}** 发起转正评估"},
                    "value": {"action": CARD_ACTION_START, "employee_id": str(e.id)},
                }],
            })
        card = {
            "schema": "2.0",
            "header": {"title": {"tag": "plain_text", "content": "试用期转正前提醒"}, "template": "orange"},
            "body": {"elements": elements},
        }
        if await _send_user_card(open_id, card):
            for e in members:
                _record_remind(db, e.id, ProbationRemindLog.TYPE_PROBATION_30D)
        else:
            logger.warning("30 天提醒发送失败 manager=%s", manager)
    # 仅在有记录时提交
    if db.new:
        await db.commit()


async def run_probation_reminder() -> None:
    async with async_session_factory() as db:
        from app.modules.hr.probation_config import reload_probation_config

        await reload_probation_config(db)
        receivers = await _load_reminder_open_ids(db)
        await _remind_hr_due_soon(db, receivers)
        await _remind_safety_exam_60d(db, receivers)
        await _remind_leader_30d(db)


PROBATION_REMINDER_TASK = TaskDefinition(
    name="hr.probation.reminder",
    schedule=ScheduleConfig(strategy=ScheduleStrategy.FIXED_TIME, time_of_day=REMIND_TIME_OF_DAY),
    coro=run_probation_reminder,
    timeout_seconds=120,
    module="hr",
)
