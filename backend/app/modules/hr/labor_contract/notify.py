"""劳动合同飞书通知卡片：续签通知 / 领取通知 / HR 公告期摘要。

员工侧通知收件人取 Employee.feishu_open_id（档案同步字段），缺失时不发送
（一线工人未入飞书的场景宁可不发也不报错中断流程）。员工两张卡每次尝试发送都写一行
通知留痕（hr.contract_notice_logs）：成功 / 失败 / 因无飞书账号而跳过，供详情页展示
与「通知续签」进度步骤判断。文案里的联系人与携带材料取 hr_contract.* 配置（settings.py）。
系统只部署在公司内网，员工在手机上点不开指向本系统的链接，所以发给员工的卡片一律纯文字、不带按钮。
给部门负责人的续签审批提醒见 dept_notice.py（发送在 scheduled.py，留痕复用 log_notice；
负责人是内部员工、在公司电脑上处理，卡片上的「去合同台账审批」按钮指向内网页面）。
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.labor_contract import settings as contract_settings
from app.modules.hr.labor_contract.models import ContractNoticeLog, LaborContract
from app.modules.hr.models import Employee
from app.platform.integrations.feishu.notification import send_user_card

logger = logging.getLogger(__name__)

# ─── 留痕 ───

NO_OPEN_ID_MESSAGE = "员工无飞书账号"
SEND_FAILED_MESSAGE = "飞书卡片发送失败"


@dataclass(frozen=True)
class NoticeResult:
    """一次通知尝试的结果（与留痕行同口径）；as_dict 供接口直接返回。"""

    status: str
    recipient_name: str | None = None
    recipient_open_id: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "error": self.error, "recipient_name": self.recipient_name,
        }


async def log_notice(
    db: AsyncSession, *, contract: LaborContract, kind: str, status: str,
    recipient_name: str | None = None, recipient_open_id: str | None = None,
    error_message: str | None = None, created_by: UUID | None = None,
    created_by_name: str | None = None,
) -> NoticeResult:
    """写一行通知留痕并返回同口径的结果（不 commit，随调用方事务落库）。"""
    name = (recipient_name or "").strip() or None
    open_id = (recipient_open_id or "").strip() or None
    error = ((error_message or "").strip() or None)
    if error is not None:
        error = error[:255]
    db.add(ContractNoticeLog(
        contract_id=contract.id,
        kind=kind,
        status=status,
        recipient_name=name,
        recipient_open_id=open_id,
        error_message=error,
        created_by=created_by,
        created_by_name=(created_by_name or "").strip() or None,
        # 显式取墙钟时间：server 端 now() 是事务开始时间，同一事务内多次发送会并列、排序不稳
        created_at=datetime.now(UTC),
    ))
    await db.flush()
    return NoticeResult(
        status=status, recipient_name=name, recipient_open_id=open_id, error=error,
    )


# ─── 联系人配置 ───


@dataclass(frozen=True)
class Contact:
    """通知文案里的联系人：info 是联系部门（hr_contract.contact_info），name 是联系人姓名
    （hr_contract.contact_name，空则文案沿用原写法），materials 是续签需携带材料（空则不提）。"""

    info: str
    name: str = ""
    materials: str = ""


async def load_contact(db: AsyncSession) -> Contact:
    kv = await contract_settings.load_contract_settings(db)
    return Contact(
        info=contract_settings.contact_info(kv),
        name=contract_settings.contact_name(kv),
        materials=contract_settings.required_materials(kv),
    )


# ─── 文案（纯函数；飞书卡片 markdown 不支持列表语法，只用段落与加粗）───


def renew_notice_markdown(contract: LaborContract, contact: Contact) -> str:
    """续签通知：配了联系人姓名按新文案（找谁办 + 携带材料 + 联系方式），否则沿用原写法。"""
    end_text = contract.end_date.isoformat() if contract.end_date else "无固定期限"
    opening = (
        f"{contract.name}您好，您的劳动合同（第 {contract.seq_no} 份，"
        f"期限 {contract.term_label}，至 {end_text}）已通过部门审批。\n\n"
    )
    ask = (
        f"您的劳动合同即将到期，部门已同意续签，请尽快到 **{contact.info}** "
        f"找 **{contact.name}** 办理续签手续。"
        if contact.name else f"请尽快到 **{contact.info}** 办理续签手续。"
    )
    materials = f"需携带材料：{contact.materials}。" if contact.materials else ""
    closing = f"如有疑问请联系 **{contact.info}** {contact.name}。" if contact.name else ""
    return opening + ask + materials + closing


def stamp_notice_markdown(contract: LaborContract, contact: Contact) -> str:
    """领取通知：盖章完成后提示员工到联系部门领取合同原件（配了姓名则写明找谁领）。"""
    who = f" 找 **{contact.name}**" if contact.name else ""
    return (
        f"{contract.name}您好，您的劳动合同（第 {contract.seq_no} 份）已完成签订盖章。\n\n"
        f"请到 **{contact.info}**{who} 领取劳动合同原件。"
    )


# ─── 发送 ───


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
    """发一张卡。elements 是卡片按钮，只给内部员工（部门负责人）的卡用；发给员工的卡不带。"""
    ok = await send_user_card(open_id, title=title, content=markdown, elements=elements)
    if not ok:
        logger.warning("劳动合同卡片发送失败: open_id=%s title=%s", open_id, title)
    return ok


async def _dispatch(
    db: AsyncSession, *, contract: LaborContract, employee: Employee, kind: str,
    title: str, markdown: str,
    created_by: UUID | None = None, created_by_name: str | None = None,
) -> NoticeResult:
    """给员工发一张卡并留痕：没有飞书 open_id 不发送（留痕为跳过），其余按发送结果留痕。"""
    open_id = await _employee_open_id(employee)
    if not open_id:
        return await log_notice(
            db, contract=contract, kind=kind, status=ContractNoticeLog.STATUS_SKIPPED,
            recipient_name=employee.name, error_message=NO_OPEN_ID_MESSAGE,
            created_by=created_by, created_by_name=created_by_name,
        )
    ok = await _send(open_id, title, markdown)
    return await log_notice(
        db, contract=contract, kind=kind,
        status=ContractNoticeLog.STATUS_SENT if ok else ContractNoticeLog.STATUS_FAILED,
        recipient_name=employee.name, recipient_open_id=open_id,
        error_message=None if ok else SEND_FAILED_MESSAGE,
        created_by=created_by, created_by_name=created_by_name,
    )


async def send_renewal_notice(
    db: AsyncSession, contract: LaborContract, employee: Employee, *,
    created_by: UUID | None = None, created_by_name: str | None = None,
) -> NoticeResult:
    """审批通过后的续签通知：提示员工到人力资源部办理续签手续（联系人、携带材料见配置）。"""
    return await _dispatch(
        db, contract=contract, employee=employee, kind=ContractNoticeLog.KIND_RENEW,
        title="劳动合同续签通知",
        markdown=renew_notice_markdown(contract, await load_contact(db)),
        created_by=created_by, created_by_name=created_by_name,
    )


async def send_stamp_notice(
    db: AsyncSession, contract: LaborContract, employee: Employee, *,
    created_by: UUID | None = None, created_by_name: str | None = None,
) -> NoticeResult:
    """盖章完成后的领取通知：提示员工领取合同原件。"""
    return await _dispatch(
        db, contract=contract, employee=employee, kind=ContractNoticeLog.KIND_COLLECT,
        title="领取劳动合同原件通知",
        markdown=stamp_notice_markdown(contract, await load_contact(db)),
        created_by=created_by, created_by_name=created_by_name,
    )


async def send_announcement_summary(
    db: AsyncSession,
    *,
    announced_rows: list[tuple[LaborContract, str]],
    notified_rows: list[tuple[LaborContract, str]],
    unreached_rows: list[tuple[LaborContract, str]],
    failed_rows: list[tuple[LaborContract, str]],
    expired_rows: list[LaborContract],
    receivers: list[str],
    days_ahead: int,
) -> int:
    """公告期扫描后的 HR 摘要卡片。返回成功发送数。

    notified_rows / unreached_rows 为站内待审批的合同，元素是
    (合同, 部门负责人姓名) / (合同, 没通知到的原因)：负责人提醒卡片发出去了哪些、
    哪些要 HR 自己跟进（匹配不到负责人 / 推送失败 / 提醒已关闭）。
    """
    if not receivers:
        return 0
    lines: list[str] = []
    if announced_rows:
        lines.append(f"**进入公告期（提前 {days_ahead} 天，{len(announced_rows)} 人，已发起飞书审批）**")
        for contract, approver in announced_rows:
            lines.append(f"- {contract.department} {contract.name}（{contract.employee_number}）"
                         f" 到期 {contract.end_date}，第 {contract.seq_no + 1} 次续签审批 → {approver}")
    if notified_rows:
        lines.append(f"**站内待审批 · 已通知部门负责人（{len(notified_rows)} 人）**")
        for contract, manager in notified_rows:
            lines.append(f"- {contract.department} {contract.name}（{contract.employee_number}）"
                         f" 到期 {contract.end_date} → 负责人 {manager}")
    if unreached_rows:
        lines.append(f"**站内待审批 · 负责人未通知到（{len(unreached_rows)} 人，请 HR 跟进）**")
        for contract, reason in unreached_rows:
            lines.append(f"- {contract.department} {contract.name}（{contract.employee_number}）"
                         f" 到期 {contract.end_date}：{reason}")
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

