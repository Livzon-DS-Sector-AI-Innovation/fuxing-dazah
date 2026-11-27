"""离职证明：核对开具、送达补发、签收（到人事办公室当面手写签名 / 纸质签收登记）。

两种模板签收方式相同，差别只在版式（需求「开具解除劳动关系证明」）：
- electronic 电子单张版：单张，可邮件发送 PDF；员工到人事办公室时在公司电脑上手写签名；
- paper 纸质两联版：含签收栏，打印后交员工当面签字，HR 登记签收时间与签收人。
系统只部署在公司内网，员工在手机 / 外网打不开指向本系统的任何链接，所以没有「线上签字」：
手写签名一律在人事办公室的公司电脑上完成，签名图随离职台账留存。
签字结果落 DepartureRecord.cert_sign_*（employee_sync 同步不触碰这些列）。
"""

import logging
import re
from datetime import date, datetime
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

# 签收方式（OffboardingCase.delivery_channel）；存量数据里的 mail 是早期线上签字留下的
CHANNEL_HANDWRITING = "handwriting"  # 员工在公司电脑上当面手写签名
CHANNEL_PAPER = "paper"  # 纸质件上签字后由 HR 登记签收


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
) -> tuple[OffboardingCase, str]:
    """HR 核对开具：生成 PDF 存档 → 台账回写 cert_issued_at → 自动发邮件 → 送达阶段。

    返回 (case, 没办成的事)；如「邮件发送失败：…」「未填写送达邮箱，证明未自动发送」。
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
    pdf_bytes = generate(**fields, issued_on=date.today()).getvalue()
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

    notes: list[str] = []
    if mail_recipient:
        result = await delivery.send_certificate_mail(
            db, to=mail_recipient, employee_name=case.name, pdf_bytes=pdf_bytes,
        )
        case.mail_recipient = mail_recipient
        case.mail_sent_at = now() if result.ok else None
        case.mail_status = result.status
        if not result.ok:
            notes.append(f"邮件发送失败：{result.error or '未知原因'}")
    else:
        notes.append("未填写送达邮箱，证明未自动发送")
    await db.commit()

    await notify.notify_stage_advanced(
        db, case, await notify_context(db),
        employee_notice="您的解除劳动关系证明已开具，请到人力资源部签收并签字确认。",
    )
    logger.info(
        "开具离职证明: %s(%s) 模板=%s 邮件=%s", case.name, case.case_no, cert_template, case.mail_status,
    )
    return await refetch(db, case.id), "；".join(notes)


# ─── 送达 ───

async def resend_delivery(
    db: AsyncSession, case: OffboardingCase, *,
    mail_recipient: str | None = None, sms_phone: str | None = None,
    user_id: UUID | None = None,
) -> tuple[OffboardingCase, str]:
    """送达阶段补发：传邮箱重发邮件（附证明 PDF）；传手机号登记短信已人工发送。

    返回 (case, 没办成的事)。
    """
    if case.status != OffboardingCase.STATUS_DELIVERING:
        raise AppException(message="仅「证明送达中」可补发")
    notes: list[str] = []
    if mail_recipient:
        result = await delivery.send_certificate_mail(
            db, to=mail_recipient, employee_name=case.name, pdf_bytes=await _load_pdf(case),
        )
        case.mail_recipient = mail_recipient
        case.mail_sent_at = now() if result.ok else None
        case.mail_status = result.status
        if not result.ok:
            notes.append(f"邮件发送失败：{result.error or '未知原因'}")
    if sms_phone:
        _mark_sms_sent(case, phone=sms_phone)
    case.updated_by = user_id
    await db.commit()
    return await refetch(db, case.id), "；".join(notes)


def _mark_sms_sent(case: OffboardingCase, *, phone: str) -> None:
    """短信发送留痕：接收号码 + 发送时间（通道未接服务商，由 HR 人工发出后登记）。"""
    case.sms_phone = phone.strip()[:32]
    case.sms_status = "manual"
    case.sms_sent_at = now()


async def register_sms_sent(
    db: AsyncSession, case: OffboardingCase, *, phone: str, user_id: UUID | None = None,
) -> OffboardingCase:
    """登记「离职证明短信已发给员工」：留存接收号码与发送时间。"""
    phone = (phone or "").strip()
    if not phone:
        raise AppException(message="请填写接收短信的手机号")
    if case.status != OffboardingCase.STATUS_DELIVERING:
        raise AppException(message="仅「证明送达中」可登记短信发送")
    _mark_sms_sent(case, phone=phone)
    case.updated_by = user_id
    await db.commit()
    return await refetch(db, case.id)


# ─── 签收 ───

def _mark_signed(
    record: DepartureRecord, *, signed_at: datetime, signed_name: str, signature: str | None,
) -> None:
    record.cert_sign_status = "signed"
    record.cert_signed_at = signed_at
    record.cert_sign_name = signed_name
    record.cert_sign_image = signature


async def _advance_to_signed(db: AsyncSession, case: OffboardingCase, *, note: str) -> OffboardingCase:
    case.status = OffboardingCase.STATUS_SIGNED
    await db.commit()
    # 员工刚签完，这里只通知 HR 进入办结环节
    await notify.notify_stage_advanced(db, case, await notify_context(db), note=note)
    return await refetch(db, case.id)


async def register_paper_sign(
    db: AsyncSession, case: OffboardingCase, *, signed_by: str,
    user_id: UUID | None = None,
) -> OffboardingCase:
    """纸质签收登记：员工在纸质证明上当面签字，HR 登记签收时间与签收人。"""
    if case.status != OffboardingCase.STATUS_DELIVERING:
        raise AppException(message="仅「证明送达中」可登记签收")
    signed_by = signed_by.strip()
    if not signed_by:
        raise AppException(message="签收人不能为空")
    stamp = now()
    case.paper_signed_at = stamp
    case.paper_signed_by = signed_by
    case.delivery_channel = CHANNEL_PAPER
    case.updated_by = user_id
    record = await linked_record(db, case)
    if record:
        _mark_signed(record, signed_at=stamp, signed_name=signed_by, signature=None)
    return await _advance_to_signed(db, case, note="员工已在纸质证明上当面签收")


def validate_signature(signature: str) -> None:
    if len(signature) > _SIGNATURE_MAX_LEN or not _SIGNATURE_PATTERN.match(signature):
        raise AppException(message="签名数据格式不正确")


async def register_signature(
    db: AsyncSession, case: OffboardingCase, *, signature: str, signed_name: str | None = None,
    user_id: UUID | None = None,
) -> OffboardingCase:
    """员工到人事办公室当面手写签名：在 HR 登录的公司电脑上签，签名图随离职台账留存。

    signed_name 是员工确认的签署人姓名，留空取员工姓名。
    """
    if case.status != OffboardingCase.STATUS_DELIVERING:
        raise AppException(message="仅「证明送达中」可登记手写签名")
    validate_signature(signature)
    stamp = now()
    signed_name = (signed_name or "").strip() or case.name
    case.delivery_channel = CHANNEL_HANDWRITING
    case.updated_by = user_id
    record = await linked_record(db, case) or await upsert_departure_record(db, case, None)
    _mark_signed(record, signed_at=stamp, signed_name=signed_name, signature=signature)
    logger.info("离职证明当面手写签名: %s(%s)", case.name, case.case_no)
    return await _advance_to_signed(db, case, note="员工已在人事办公室手写签名确认")
