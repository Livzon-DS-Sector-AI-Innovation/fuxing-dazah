"""离职证明公开签署接口（无需登录）。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response

router = APIRouter(tags=["离职证明签署"])


class SignRequest(BaseModel):
    name: str
    id_card_last4: str
    sign_image: str  # base64 签名图片


@router.get("/certificate-sign/{token}", summary="查看离职证明（签署前预览）")
async def view_certificate_for_sign(token: str, session: AsyncSession = Depends(get_db)):
    """员工点邮件链接后看到的页面数据，含证书预览和员工信息。"""
    from app.modules.hr.models import DepartureRecord

    record = (await session.execute(
        select(DepartureRecord).where(
            DepartureRecord.cert_sign_token == token,
            DepartureRecord.is_deleted == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not record:
        raise HTTPException(404, "签署链接无效或已过期")

    return success_response(data={
        "name": record.name,
        "department": record.department,
        "position": record.position,
        "offboarding_date": str(record.offboarding_date) if record.offboarding_date else "",
        "sign_status": record.cert_sign_status or "pending",
        "id_card_masked": record.id_card[-4:] if record.id_card and len(record.id_card) >= 4 else "",
    })


@router.post("/certificate-sign/{token}", summary="提交签署")
async def sign_certificate(
    token: str,
    payload: SignRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """员工提交签署：验证身份 + 保存签名。"""
    from datetime import datetime as dt, timezone

    from app.modules.hr.models import DepartureRecord
    from app.modules.hr.mail_service import send_email

    record = (await session.execute(
        select(DepartureRecord).where(
            DepartureRecord.cert_sign_token == token,
            DepartureRecord.is_deleted == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not record:
        raise HTTPException(404, "签署链接无效或已过期")
    if record.cert_sign_status == "signed":
        raise HTTPException(400, "已签署过，无需重复签署")

    # 身份验证：姓名 + 身份证后四位
    if record.name != payload.name:
        raise HTTPException(400, "姓名验证失败")
    if not record.id_card or record.id_card[-4:] != payload.id_card_last4:
        raise HTTPException(400, "身份证验证失败")

    # 保存签名
    record.cert_sign_status = "signed"
    record.cert_signed_at = dt.now(timezone.utc)
    record.cert_sign_image = payload.sign_image
    record.cert_sign_name = payload.name
    await session.flush()

    # 生成完整 PDF 并发送邮件
    from app.modules.hr.termination_certificate_generator import (
        generate_termination_certificate_pdf,
    )
    id_number = record.id_card or ""
    entry_date_val = record.livo_entry_date or record.factory_entry_date or ""

    pdf_buf = generate_termination_certificate_pdf(
        name=record.name or "",
        id_number=id_number,
        department=record.department or "",
        position=record.position or "",
        entry_date=entry_date_val or "",
        leave_date=record.offboarding_date or "",
        leave_reason=record.offboarding_type or "个人原因",
    )

    # 查找员工邮箱
    from app.modules.hr.models import Employee
    emp = (await session.execute(
        select(Employee.email).where(
            Employee.name == record.name,
            Employee.is_deleted == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    employee_email = emp or ""

    if employee_email:
        name = record.name or "员工"
        subj = f"离职证明 - {name}"
        body = f"{name}，您好：<br><br>您的离职证明已生成，请查收附件。<br><br>丽珠集团福州福兴医药有限公司"
        try:
            await send_email(
                to=employee_email,
                subject=subj,
                html_body=body,
                attachments=[("离职证明.pdf", pdf_buf.read())],
                session=session,
            )
        except Exception:
            pass

    await session.commit()
    return success_response(message="签署成功，离职证明已发送至您的邮箱")
