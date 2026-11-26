"""离职办理节点提醒（方案 §3.9）：发起时限提醒 + 清退催办。

- offboarding_lead：档案已定离职日（Employee.departure_date）但没有任何进行中办结单的
  员工。按制度须提前发起（试用期 3 天 / 转正 1 个月，天数取 hr_offboarding.*），
  距「应发起日」不足 N 天（hr_reminder.offboarding_lead.days_ahead，缺省 7）开始提醒，
  已超过时限的持续提醒，直到发起办理。
- offboarding_clearance_due：办结单停在「离职审批中 / 清退会签中」且距离职日 ≤ 2 天
  （清退交接应于离职日前 2 天发起）——催办，直到走出清退阶段。

解决的是需求「现状说明」第一条：节点先后关系靠员工自行把握、缺系统提示。
扫描逻辑是不碰数据库的纯函数（pick_*），定时任务与测试共用；取数与发送在 scheduled.py。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.modules.hr.models import Employee
from app.modules.hr.offboarding.models import OffboardingCase

# 人事提醒框架里的提醒类型（KV 键前缀 hr_reminder.<type>.）
REMINDER_LEAD = "offboarding_lead"
REMINDER_CLEARANCE_DUE = "offboarding_clearance_due"

CLEARANCE_DUE_DAYS = 2  # 清退交接应于离职日前 2 天发起（需求「流程节点」第 3 条）
DEFAULT_LEAD_BUFFER_DAYS = 7  # 距「应发起日」不足 N 天开始提醒


@dataclass(slots=True)
class LeadOverdue:
    """已定离职日、尚无进行中办理、且临近/已超过应发起时限的员工。"""

    employee_number: str
    name: str
    department: str
    departure_date: date
    days_left: int  # 距离职日的天数（已过为负）
    lead_days: int  # 制度要求提前的天数
    probation: bool

    @property
    def overdue_days(self) -> int:
        """已超过应发起时限的天数；未超期为 0。"""
        return max(self.lead_days - self.days_left, 0)

    @property
    def deadline(self) -> date:
        """应发起的最晚日期。"""
        return self.departure_date - timedelta(days=self.lead_days)


@dataclass(slots=True)
class ClearanceOverdue:
    """距离职日 ≤ 2 天（或已过）仍停在审批/清退阶段的办结单。"""

    case_no: str
    name: str
    employee_number: str
    department: str
    status_label: str
    offboarding_date: date
    days_left: int


def pick_lead_overdue(
    employees: Sequence[Employee],
    active_employee_numbers: set[str],
    *,
    today: date,
    lead_probation: int,
    lead_resigned: int,
    buffer_days: int,
) -> list[LeadOverdue]:
    """筛出需要提醒发起离职办理的员工，按离职日升序（最紧急的在前）。

    employees 为 Employee 行；已离职、未定离职日、已有进行中办结单的不在内。
    """
    due: list[LeadOverdue] = []
    for employee in employees:
        if employee.departure_date is None or employee.status == "离职":
            continue
        if employee.employee_number in active_employee_numbers:
            continue
        probation = employee.status == "试用期"
        lead_days = lead_probation if probation else lead_resigned
        days_left = (employee.departure_date - today).days
        if days_left < lead_days + max(buffer_days, 0):
            due.append(LeadOverdue(
                employee_number=employee.employee_number,
                name=employee.name,
                department=employee.department or "-",
                departure_date=employee.departure_date,
                days_left=days_left,
                lead_days=lead_days,
                probation=probation,
            ))
    due.sort(key=lambda item: (item.departure_date, item.employee_number))
    return due


def pick_clearance_overdue(cases: Sequence[OffboardingCase], *, today: date, due_days: int = CLEARANCE_DUE_DAYS) -> list[ClearanceOverdue]:
    """筛出距离职日不足、仍停在审批/清退阶段的办结单，按离职日升序。"""
    due = [
        ClearanceOverdue(
            case_no=case.case_no,
            name=case.name,
            employee_number=case.employee_number,
            department=case.department,
            status_label=case.status_label,
            offboarding_date=case.offboarding_date,
            days_left=(case.offboarding_date - today).days,
        )
        for case in cases
        if (case.offboarding_date - today).days <= due_days
    ]
    due.sort(key=lambda item: (item.offboarding_date, item.case_no))
    return due


def _days_phrase(days_left: int) -> str:
    if days_left < 0:
        return f"已过离职日 {-days_left} 天"
    if days_left == 0:
        return "今天就是离职日"
    return f"还剩 {days_left} 天"


def lead_card(
    items: list[LeadOverdue], *, lead_probation: int, lead_resigned: int,
) -> dict[str, Any]:
    """发起时限提醒卡片；两个提前天数取自实际配置，文案与规则保持一致。"""
    lines = []
    for item in items:
        state = (
            f"**已超期 {item.overdue_days} 天**（应于 {item.deadline} 前发起）"
            if item.overdue_days
            else f"距时限仅 {item.days_left - item.lead_days} 天（应于 {item.deadline} 前发起）"
        )
        lines.append(
            f"- {item.name}（{item.department} · 工号 {item.employee_number} · "
            f"{'试用期' if item.probation else '转正'}）离职日 {item.departure_date}，{state}"
        )
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "离职发起时限提醒"},
            "template": "orange",
        },
        "body": {"elements": [{"tag": "markdown", "content": (
            f"以下 **{len(items)}** 名员工已定离职日期，但尚未发起离职办理。"
            f"按制度须提前发起（试用期 {lead_probation} 天 / 转正 {lead_resigned} 天）：\n\n"
            + "\n".join(lines)
            + "\n\n请尽快在人事系统「离职管理 → 离职办理」发起办理。"
        )}]},
    }


def clearance_card(items: list[ClearanceOverdue]) -> dict[str, Any]:
    lines = [
        f"- {item.name}（{item.department} · 工号 {item.employee_number} · {item.case_no}）"
        f"离职日 {item.offboarding_date}（{_days_phrase(item.days_left)}），当前「{item.status_label}」"
        for item in items
    ]
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "离职手续催办"},
            "template": "red",
        },
        "body": {"elements": [{"tag": "markdown", "content": (
            f"以下 **{len(items)}** 名员工距离职日已不足 {CLEARANCE_DUE_DAYS} 天（或已到/超过离职日），"
            f"离职审批 / 清退会签仍未办结。清退交接应于离职日前 {CLEARANCE_DUE_DAYS} 天发起：\n\n"
            + "\n".join(lines)
            + "\n\n请各部门尽快处理；办结后请在人事系统「离职管理 → 离职办理」登记推进。"
        )}]},
    }
