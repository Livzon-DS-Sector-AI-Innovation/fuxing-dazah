"""劳动合同飞书通知卡片：续签通知 / 领取通知 / 签字提醒 / HR 公告期摘要。

员工侧通知收件人取 Employee.feishu_open_id（档案同步字段），缺失时记日志跳过
（一线工人未入飞书的场景宁可不发也不报错中断流程）。
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.labor_contract.models import LaborContract
from app.modules.hr.models import Employee
from app.platform.integrations.feishu.notification import send_user_card

logger = logging.getLogger(__name__)


async def _employee_open_id(employee: Employee) -> str | None:
    open_id = getattr(employee, "feishu_open_id", None)
    if not open_id:
        logger.warning(
            "员工 %s(%s) 缺少飞书 open_id，跳过员工侧通知",
            getattr(employee, "name", "?"),
            getattr(employee, "employee_number", "?"),
        )
    return open_id


async def _send(
    open_id: str, title: str, markdown: str,
    elements: list[dict[str, Any]] | None = None,
) -> bool:
    ok = await send_user_card(open_id, title=title, content=markdown, elements=elements)
    if not ok:
        logger.warning("劳动合同卡片发送失败: open_id=%s title=%s", open_id, title)
    return ok


async def send_renewal_notice(
    db: AsyncSession, contract: LaborContract, employee: Employee, contact: str
) -> bool:
    """审批通过后的续签通知：提示员工到 HR 办理续签手续。"""
    open_id = await _employee_open_id(employee)
    if not open_id:
        return False
    end_text = contract.end_date.isoformat() if contract.end_date else "无固定期限"
    markdown = (
        f"{contract.name}您好，您的劳动合同（第 {contract.seq_no} 份，"
        f"期限 {contract.term_label}，至 {end_text}）已通过部门审批。\n\n"
        f"请尽快到 **{contact}** 办理续签手续。"
    )
    return await _send(open_id, "劳动合同续签通知", markdown)


async def send_stamp_notice(
    db: AsyncSession, contract: LaborContract, employee: Employee, contact: str
) -> bool:
    """盖章完成后的领取通知：提示员工领取合同原件。"""
    open_id = await _employee_open_id(employee)
    if not open_id:
        return False
    markdown = (
        f"{contract.name}您好，您的劳动合同（第 {contract.seq_no} 份）已完成签订盖章。\n\n"
        f"请到 **{contact}** 领取劳动合同原件。"
    )
    return await _send(open_id, "领取劳动合同原件通知", markdown)


async def send_sign_reminder(
    db: AsyncSession, contract: LaborContract, employee: Employee,
    contact: str, sign_url: str,
) -> bool:
    """领取后的签字提醒：附一次性线上签字入口。"""
    open_id = await _employee_open_id(employee)
    if not open_id:
        return False
    markdown = (
        f"{contract.name}您好，您已领取劳动合同（第 {contract.seq_no} 份）原件。\n\n"
        f"请点击下方「点击签字」完成线上签字确认，作为已领取的凭证。\n\n"
        f"如有疑问请联系 **{contact}**。"
    )
    elements = [{
        "tag": "action",
        "actions": [{
            "tag": "button",
            "text": {"tag": "plain_text", "content": "点击签字"},
            "type": "primary",
            "url": sign_url,
        }],
    }]
    return await _send(open_id, "劳动合同签字提醒", markdown, elements)


async def send_announcement_summary(
    db: AsyncSession,
    *,
    announced_rows: list[tuple[LaborContract, str]],
    manual_rows: list[LaborContract],
    failed_rows: list[tuple[LaborContract, str]],
    expired_rows: list[LaborContract],
    receivers: list[str],
    days_ahead: int,
) -> int:
    """公告期扫描后的 HR 摘要卡片。返回成功发送数。"""
    if not receivers:
        return 0
    lines: list[str] = []
    if announced_rows:
        lines.append(f"**进入公告期（提前 {days_ahead} 天，{len(announced_rows)} 人，已发起飞书审批）**")
        for contract, approver in announced_rows:
            lines.append(f"- {contract.department} {contract.name}（{contract.employee_number}）"
                         f" 到期 {contract.end_date}，第 {contract.seq_no + 1} 次续签审批 → {approver}")
    if manual_rows:
        lines.append(f"**站内待审批（{len(manual_rows)} 人，未配置审批定义或负责人缺失，走台账勾选）**")
        for contract in manual_rows:
            lines.append(f"- {contract.department} {contract.name}（{contract.employee_number}）"
                         f" 到期 {contract.end_date}")
    if failed_rows:
        lines.append(f"**发起失败（{len(failed_rows)} 人，请检查审批定义配置）**")
        for contract, error in failed_rows:
            lines.append(f"- {contract.department} {contract.name}：{error}")
    if expired_rows:
        lines.append(f"**到期未续签（{len(expired_rows)} 人，已在台账标注）**")
        for contract in expired_rows:
            lines.append(f"- {contract.department} {contract.name}（{contract.employee_number}）"
                         f" 已于 {contract.end_date} 到期")
    if not lines:
        return 0
    markdown = "\n".join(lines)
    sent = 0
    for open_id in receivers:
        if await _send(open_id, "劳动合同公告期提醒", markdown):
            sent += 1
    return sent


# 卡片正文有长度上限：部门明细最多列这么多，其余合并成一行
_ARCHIVE_MAX_DEPARTMENTS = 20


async def send_archive_summary(
    *,
    in_service_count: int,
    departed_count: int,
    department_counts: list[tuple[str, int]],
    receivers: list[str],
) -> int:
    """归档缺失周提醒（每周一）：未归档合同扫描件按部门汇总。返回成功发送数。"""
    total = in_service_count + departed_count
    if not receivers or total == 0:
        return 0
    lines = [
        f"未归档合同扫描件共 **{total}** 份（在职 {in_service_count} / 离职 {departed_count}）。",
        "",
        "**按部门**",
    ]
    for department, count in department_counts[:_ARCHIVE_MAX_DEPARTMENTS]:
        lines.append(f"- {department or '未分类'}：{count} 份")
    rest = department_counts[_ARCHIVE_MAX_DEPARTMENTS:]
    if rest:
        lines.append(f"- 其余 {len(rest)} 个部门共 {sum(c for _, c in rest)} 份")
    lines += [
        "",
        "请到「劳动合同 → 电子档案库」导出补扫清单，安排扫描归档；离职人员合同在离职台账归档。",
    ]
    markdown = "\n".join(lines)
    sent = 0
    for open_id in receivers:
        if await _send(open_id, "合同归档缺失提醒", markdown):
            sent += 1
    return sent

