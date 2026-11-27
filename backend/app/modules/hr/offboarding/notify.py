"""离职管理飞书通知卡片：阶段推进通知（解决「节点先后靠员工自己把握」痛点）。

HR 侧收件人走系统配置 hr_offboarding.hr_copy_open_ids（resolve_receivers 支持姓名 /
open_id 两种填法，为空则不发）；员工侧通知收件人取 Employee.feishu_open_id，
缺失时记日志跳过。卡片通知一律尽力而为：失败只记日志，不回滚已落库的状态。
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding.models import OffboardingCase
from app.modules.hr.reminder.config import resolve_receivers
from app.platform.integrations.feishu.notification import send_user_card

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NotifyContext:
    """发通知所需的配置快照：HR 接收人条目 + 落款联系人（service.common.notify_context 构造）。"""

    hr_copy: list[str] = field(default_factory=list)
    contact: str = "人力资源部"


# 各阶段 HR 的下一步动作（节点先后由系统编排，卡片直接告诉 HR 该做什么）
NEXT_STEP: dict[str, str] = {
    OffboardingCase.STATUS_DRAFT: "确认信息与离岗体检登记后，发起离职审批",
    OffboardingCase.STATUS_APPROVING: "待部门负责人审批；未接飞书审批的，审批通过后在平台登记办结",
    OffboardingCase.STATUS_CLEARING: "跟进各部门清退会签并登记清退明细，完成后登记会签办结",
    OffboardingCase.STATUS_CERT_ISSUING: "核对员工信息，开具解除劳动关系证明",
    OffboardingCase.STATUS_DELIVERING: "把证明交给员工（邮件 / 当面），员工签字后登记签收",
    OffboardingCase.STATUS_SIGNED: "确认飞书账号已注销后办结",
    OffboardingCase.STATUS_CLOSED: "无需操作，档案与台账已同步",
    OffboardingCase.STATUS_CANCELED: "无需操作；如仍需办理请重新发起",
}


async def _send(open_id: str, title: str, markdown: str) -> bool:
    try:
        ok = await send_user_card(open_id, title=title, content=markdown)
    except Exception as exc:  # 单个接收人失败不影响其余
        logger.warning("离职管理卡片发送异常: open_id=%s → %s", open_id, exc)
        return False
    if not ok:
        logger.warning("离职管理卡片发送失败: open_id=%s title=%s", open_id, title)
    return ok


async def notify_hr_receivers(
    db: AsyncSession, copy_entries: list[str], title: str, markdown: str,
) -> int:
    """HR 侧通知：配置为空时静默跳过（未配置接收人不视为错误）。"""
    if not copy_entries:
        return 0
    sent = 0
    for open_id in await resolve_receivers(db, copy_entries):
        if await _send(open_id, title, markdown):
            sent += 1
    return sent


async def notify_stage_advanced(
    db: AsyncSession, case: OffboardingCase, ctx: NotifyContext, *,
    note: str | None = None, employee_notice: str | None = None,
) -> None:
    """阶段推进通知：HR 摘要 + （可选）员工侧卡片。

    note：本次推进的补充说明（如「飞书审批定义未配置，走站内登记办结」）；
    employee_notice：传文案时才给员工发卡。系统只在公司内网可达，员工在手机上点不开
    任何指向本系统的链接，所以卡片只带文字，不带跳转按钮。
    """
    try:
        lines = [
            f"**{case.department} {case.name}**（{case.employee_number}）离职办理已推进：",
            f"- 当前阶段：**{case.status_label}**",
        ]
        if note:
            lines.append(f"- 说明：{note}")
        lines.append(f"- 离职日期：{case.offboarding_date}（{case.offboarding_type}）")
        next_step = NEXT_STEP.get(case.status)
        if next_step:
            lines.append(f"- 下一步：{next_step}")
        lines.append(f"- 申请编号：{case.case_no}")
        lines.append("\n如需操作请进入人事系统「离职管理 → 离职办理」。")
        await notify_hr_receivers(db, ctx.hr_copy, f"离职办理推进 · {case.name}", "\n".join(lines))

        if employee_notice:
            await _notify_employee(db, case, employee_notice)
    except Exception as exc:  # 通知失败不影响状态机
        logger.warning("离职阶段推进通知失败: case=%s → %s", case.id, exc)


async def notify_initiate_failed(
    db: AsyncSession, case: OffboardingCase, ctx: NotifyContext, *,
    stage: str, error: str,
) -> None:
    """飞书审批发起失败（已配置但不可用）：提醒 HR 检查配置，或站内登记推进。"""
    try:
        await notify_hr_receivers(
            db, ctx.hr_copy, f"离职审批发起失败 · {case.name}",
            f"**{case.name}**（{case.case_no}）的「{stage}」飞书审批发起失败：\n"
            f"- 原因：{error}\n"
            f"- 已降级为**站内登记办结**，可在办理抽屉手动推进；\n"
            f"- 若需走飞书审批，请检查系统配置「离职管理」里的审批定义编码。",
        )
    except Exception as exc:
        logger.warning("离职审批发起失败通知发送失败: case=%s → %s", case.id, exc)


async def _notify_employee(db: AsyncSession, case: OffboardingCase, notice: str) -> None:
    """员工侧卡片（纯文字）：无飞书账号（或已注销）时跳过——邮件 / 短信才是离职员工的主通道。"""
    employee = await repo.get_employee(db, case.employee_id)
    open_id = getattr(employee, "feishu_open_id", None) if employee else None
    if not open_id:
        logger.info("员工无飞书 open_id，跳过离职办理员工通知: case=%s", case.id)
        return
    await _send(open_id, "离职办理通知", f"{case.name}您好，{notice}")
