"""离职证明：核对开具、送达补发、签收（电子版 H5 手写签字 / 纸质两联版当面签收）。

两种模板对应两种签收方式（需求「开具解除劳动关系证明」）：
- electronic 电子单张版：证明 PDF 邮件送达 + 一次性签署链接，员工在 H5 手写签名；
- paper 纸质两联版：含签收栏，打印后交员工当面签字，HR 登记签收时间与签收人。
签字结果落 DepartureRecord.cert_sign_*（employee_sync 同步不触碰这些列）。
"""

import logging
import re
import secrets
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.file_storage import read_object, store_object
from app.modules.hr.models import DepartureRecord, Employee
from app.modules.hr.offboarding import certificate as cert_gen
from app.modules.hr.offboarding import delivery, notify
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding.models import OffboardingCase
from app.modules.hr.offboarding.service.common import (
    hash_token,
    linked_record,
    notify_context,
    now,
    refetch,
    upsert_departure_record,
)

logger = logging.getLogger(__name__)

# 手写签名：PNG/JPEG 的 base64 dataURL（台账列是 Text，超限直接拒绝而不是截断出坏图）
_SIGNATURE_PATTERN = re.compile(r"^data:image/(?:png|jpeg);base64,[A-Za-z0-9+/]+={0,2}$")
_SIGNATURE_MAX_LEN = 500_000


def cert_fields(
    case: OffboardingCase, record: DepartureRecord | None, employee: Employee | None,
) -> dict[str, Any]:
    """证明字段：档案带出（姓名/身份证号/入职日期/部门岗位/离职日期/离职原因）。"""
    id_number = (record.id_card if record else None) or (employee.id_card if employee else None) or ""
    entry_date = (
        (record.livo_entry_date or record.factory_entry_date) if record else None
    ) or (employee.hire_date if employee else None) or ""
    return {
        "name": case.name,
        "id_number": id_number,
        "department": case.department,
        "position": case.position or "-",
        "entry_date": entry_date,
        "leave_date": case.offboarding_date,
        "leave_reason": case.reason or case.offboarding_type,
    }


def read_certificate_pdf(case: OffboardingCase) -> tuple[bytes, str] | None:
    if not case.cert_storage_key:
        return None
    return read_object("hr", case.cert_storage_key)


def is_electronic(case: OffboardingCase) -> bool:
    return case.cert_template != OffboardingCase.CERT_PAPER


async def issue_sign_token(db: AsyncSession, case: OffboardingCase, record: DepartureRecord) -> str:
    """签发一次性签字 token：台账存 sha256（64 字符恰合列宽），确认后清空作废。"""
    token = secrets.token_urlsafe(32)
    record.cert_sign_token = hash_token(token)
    record.cert_sign_status = "pending"
    await db.flush()
    return token


async def _refresh_sign_link(
    db: AsyncSession, case: OffboardingCase, record: DepartureRecord,
) -> tuple[str, list[str]]:
    """（重新）签发签字 token 并拼签署链接；旧链接随 token 替换作废。

    纸质两联版走当面签收，不签发链接。返回 (sign_url, 提示)；链接同时交回 HR，
    短信通道未接入时由 HR 人工转发给员工。
    """
    if not is_electronic(case):
        return "", []
    sign_url = await delivery.build_sign_url(db, await issue_sign_token(db, case, record))
    if not sign_url:
        return "", ["未配置签字页基地址（系统配置 → 离职管理），无法生成签署链接"]
    return sign_url, []


async def _load_pdf(case: OffboardingCase) -> bytes:
    stored = read_certificate_pdf(case)
    if not stored:
        raise AppException(message="证明文件缺失，请重新开具证明")
    return stored[0]


# ─── 开具 ───

async def issue_certificate(
    db: AsyncSession,
    case: OffboardingCase,
    *,
    cert_template: str = OffboardingCase.CERT_ELECTRONIC,
    mail_recipient: str | None = None,
    issued_by: str | None = None,
    user_id: UUID | None = None,
) -> tuple[OffboardingCase, str, str | None]:
    """HR 核对开具：生成 PDF 存档 → 台账回写 cert_issued_at → 自动发邮件 → 送达阶段。

    返回 (case, 提示, sign_url)；sign_url 供 HR 人工转发签署链接。
    """
    if case.status != OffboardingCase.STATUS_CERT_ISSUING:
        raise AppException(message="仅「待开具证明」状态可开具证明")
    if cert_template not in (OffboardingCase.CERT_ELECTRONIC, OffboardingCase.CERT_PAPER):
        raise AppException(message="模板只能是 electronic / paper")

    employee = await repo.get_employee(db, case.employee_id)
    record = await upsert_departure_record(db, case, employee)
    fields = cert_fields(case, record, employee)
    generate = (
        cert_gen.generate_electronic_pdf
        if cert_template == OffboardingCase.CERT_ELECTRONIC
        else cert_gen.generate_paper_pdf
    )
    pdf_bytes = generate(**fields).getvalue()
    storage_key = f"offboarding/{case.id}/termination_certificate_{cert_template}.pdf"
    store_object("hr", storage_key, pdf_bytes, "application/pdf")

    case.cert_template = cert_template
    case.cert_issued_at = now()
    case.cert_issued_by = issued_by
    case.cert_storage_key = storage_key
    case.status = OffboardingCase.STATUS_DELIVERING
    case.updated_by = user_id
    record.cert_issued_at = case.cert_issued_at
    await db.flush()

    sign_url, notes = await _refresh_sign_link(db, case, record)
    if mail_recipient:
        result = await delivery.send_certificate_mail(
            db, to=mail_recipient, employee_name=case.name,
            pdf_bytes=pdf_bytes, sign_url=sign_url,
        )
        case.mail_recipient = mail_recipient
        case.mail_sent_at = now() if result.ok else None
        case.mail_status = result.status
        if not result.ok:
            notes.append(f"邮件发送失败：{result.error or '未知原因'}；可复制签署链接人工发送")
    else:
        notes.append("未填写送达邮箱，证明未自动发送")
    await db.commit()

    ctx = await notify_context(db)
    employee_notice = (
        "您的解除劳动关系证明已开具，请点击下方按钮查看并手写签名确认。"
        if is_electronic(case) else
        "您的解除劳动关系证明（纸质两联）已开具，请到人力资源部当面签收。"
    )
    await notify.notify_stage_advanced(
        db, case, ctx, sign_url=sign_url or None, employee_notice=employee_notice,
    )
    logger.info(
        "开具离职证明: %s(%s) 模板=%s 邮件=%s", case.name, case.case_no, cert_template, case.mail_status,
    )
    return await refetch(db, case.id), "；".join(notes), sign_url or None


# ─── 送达 ───

async def resend_delivery(
    db: AsyncSession, case: OffboardingCase, *,
    mail_recipient: str | None = None, sms_phone: str | None = None,
    user_id: UUID | None = None,
) -> tuple[OffboardingCase, str, str | None]:
    """送达阶段补发/重发/取签署链接。

    - 只取链接（不传邮箱/手机）：重新签发并返回签署链接，旧链接作废；
    - 传邮箱：重发邮件（电子版附新签署链接）；
    - 传手机号：短信通道未接入时只登记号码，链接仍交回 HR 人工发送。
    """
    if case.status != OffboardingCase.STATUS_DELIVERING:
        raise AppException(message="仅「证明送达中」可补发")
    pdf_bytes = await _load_pdf(case)
    record = await linked_record(db, case) or await upsert_departure_record(db, case, None)
    ctx = await notify_context(db)

    sign_url, notes = await _refresh_sign_link(db, case, record)
    if mail_recipient:
        result = await delivery.send_certificate_mail(
            db, to=mail_recipient, employee_name=case.name,
            pdf_bytes=pdf_bytes, sign_url=sign_url,
        )
        case.mail_recipient = mail_recipient
        case.mail_sent_at = now() if result.ok else None
        case.mail_status = result.status
        if not result.ok:
            notes.append(f"邮件发送失败：{result.error or '未知原因'}")
    if sms_phone:
        sms = await delivery.send_certificate_sms(
            db, to=sms_phone, employee_name=case.name,
            sign_url=sign_url or "（链接见邮件）", contact=ctx.contact,
        )
        case.sms_phone = sms_phone
        case.sms_status = sms.status
        if sms.status == "not_configured":
            notes.append("短信通道未接入，号码已登记；请复制签署链接通过其他方式发给员工")
        elif not sms.ok:
            notes.append(f"短信发送失败：{sms.error or '未知原因'}")
    case.updated_by = user_id
    await db.commit()
    return await refetch(db, case.id), "；".join(notes), sign_url or None


# ─── 签收 ───

async def register_paper_sign(
    db: AsyncSession, case: OffboardingCase, *, signed_by: str,
    user_id: UUID | None = None,
) -> OffboardingCase:
    """纸质两联版签收登记：员工当面签字，签收时间与方式留存。"""
    if case.status != OffboardingCase.STATUS_DELIVERING:
        raise AppException(message="仅「证明送达中」可登记纸质签收")
    signed_by = signed_by.strip()
    if not signed_by:
        raise AppException(message="签收人不能为空")
    stamp = now()
    case.paper_signed_at = stamp
    case.paper_signed_by = signed_by
    case.delivery_channel = "paper"
    case.status = OffboardingCase.STATUS_SIGNED
    case.updated_by = user_id
    record = await linked_record(db, case)
    if record:
        _mark_signed(record, signed_at=stamp, signed_name=signed_by, signature=None)
    await db.commit()
    # 员工刚当面签完字，这里只通知 HR 进入办结环节
    await notify.notify_stage_advanced(
        db, case, await notify_context(db), note="员工已当面签收纸质证明",
    )
    return await refetch(db, case.id)


def _mark_signed(
    record: DepartureRecord, *,
    signed_at: datetime, signed_name: str, signature: str | None,
) -> None:
    record.cert_sign_status = "signed"
    record.cert_signed_at = signed_at
    record.cert_sign_name = signed_name
    record.cert_sign_image = signature
    record.cert_sign_token = None  # 一次性：确认即作废


async def confirm_sign_by_token(
    db: AsyncSession, token: str, *, signature: str, confirm_name: str | None = None,
) -> tuple[OffboardingCase | None, DepartureRecord]:
    """员工 H5 手写签名确认（免登，token 即凭证）：签名图随台账留存。

    返回 (case, 台账行)；台账行不挂流程（存量线下离职）时 case 为 None。
    """
    if len(signature) > _SIGNATURE_MAX_LEN or not _SIGNATURE_PATTERN.match(signature):
        raise AppException(message="签名数据格式不正确")
    record = await repo.find_record_by_sign_token(db, hash_token(token))
    if not record:
        raise AppException(message="签字链接无效或已失效", status_code=404)

    stamp = now()
    signed_name = (confirm_name or "").strip() or record.name
    _mark_signed(record, signed_at=stamp, signed_name=signed_name, signature=signature)
    await db.flush()

    case = await repo.latest_case_by_record(
        db, record.id, statuses=(OffboardingCase.STATUS_DELIVERING,),
    )
    if case:
        case.delivery_channel = case.delivery_channel or "mail"
        case.status = OffboardingCase.STATUS_SIGNED
        await db.flush()
    await db.commit()
    logger.info("离职证明线上签字确认: %s 工号=%s", record.name, record.employee_number)

    if case:
        # 员工刚在 H5 签完字，这里只通知 HR 进入办结环节
        await notify.notify_stage_advanced(
            db, case, await notify_context(db), note="员工已在线手写签字确认",
        )
    return case, record
