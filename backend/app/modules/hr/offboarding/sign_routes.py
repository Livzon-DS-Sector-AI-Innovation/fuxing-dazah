"""离职证明签字公开路由（免登，token 即凭证）：查看证明 + 手写签字确认 + PDF 下载。

挂在全局 api_router（prefix=/hr，同 labor_contract sign_router 模式）——
不能挂 hr_router（require_hr_basic 门禁会把无系统账号的离职员工挡在门外）。
token 为一次性：确认成功后清空，链接自动作废，所以签字成功后的 PDF 下载
不能再走 token 鉴权，而是在确认接口的响应里直接带回文件内容。
"""

import base64
import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.file_storage import content_disposition
from app.core.response import success_response
from app.modules.hr.models import DepartureRecord
from app.modules.hr.offboarding import certificate as cert_gen
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding import service
from app.modules.hr.offboarding import settings as offboarding_settings
from app.modules.hr.offboarding.models import OffboardingCase
from app.modules.hr.offboarding.schemas import DepartureCertSignConfirm
from app.platform.audit.service import record_audit_log

logger = logging.getLogger(__name__)

sign_router = APIRouter(tags=["HR-离职管理"])


async def _load_context(db: AsyncSession, token: str) -> tuple[OffboardingCase | None, DepartureRecord]:
    """token → (办结单, 台账行)。台账行不挂流程（存量线下离职）时 case 为 None。"""
    record = await repo.find_record_by_sign_token(db, service.hash_token(token))
    if not record:
        raise AppException(message="签字链接无效或已失效", status_code=404)
    return await repo.latest_case_by_record(db, record.id), record


def _record_fields(record: DepartureRecord) -> dict[str, Any]:
    """无办结单的台账行：证明字段直接取台账（兜底展示）。"""
    reasons = record.offboarding_reason if isinstance(record.offboarding_reason, list) else []
    return {
        "name": record.name,
        "id_number": record.id_card or "",
        "department": record.department,
        "position": record.position or "-",
        "entry_date": record.livo_entry_date or record.factory_entry_date or "",
        "leave_date": record.offboarding_date or "",
        "leave_reason": (reasons[0] if reasons else None) or record.offboarding_type or "-",
    }


def _pdf_payload(case: OffboardingCase | None, record: DepartureRecord) -> dict[str, Any]:
    """签字成功页用的 PDF 内容：随确认响应带回（此时 token 已作废，不能再按 token 取）。"""
    stored = service.read_certificate_pdf(case) if case else None
    if not stored:
        return {"has_pdf": False, "pdf_base64": None, "pdf_filename": None}
    return {
        "has_pdf": True,
        "pdf_base64": base64.b64encode(stored[0]).decode(),
        "pdf_filename": f"解除劳动关系证明_{record.name}.pdf",
    }


@sign_router.get("/departure-cert-sign/{token}", summary="签字页信息（token 即凭证，免登）")
async def sign_page_info(token: str, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    case, record = await _load_context(db, token)
    if case:
        employee = await repo.get_employee(db, case.employee_id)
        fields = service.cert_fields(case, record, employee)
    else:
        fields = _record_fields(record)
    kv = await offboarding_settings.load_offboarding_settings(db)
    return success_response(data={
        "name": record.name,
        "department": fields["department"] or record.department,
        "position": fields["position"] or record.position or "-",
        "leave_date": str(fields["leave_date"] or ""),
        "has_pdf": bool(case and case.cert_storage_key),
        "contact": offboarding_settings.contact_info(kv),
        "certificate_html": cert_gen.generate_electronic_html(**fields),
    })


@sign_router.get("/departure-cert-sign/{token}/pdf", summary="下载证明 PDF（免登；签字前有效）")
async def download_certificate_pdf(token: str, db: AsyncSession = Depends(get_db)) -> Response:
    case, record = await _load_context(db, token)
    stored = service.read_certificate_pdf(case) if case else None
    if not stored:
        raise AppException(message="证明文件尚未生成", status_code=404)
    data, _content_type = stored
    return Response(
        content=data, media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(
            "attachment", f"解除劳动关系证明_{record.name}.pdf",
        )},
    )


@sign_router.post("/departure-cert-sign/{token}/confirm", summary="手写签字确认（一次性，确认后链接作废）")
async def confirm_sign(
    token: str,
    payload: DepartureCertSignConfirm,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    case, record = await service.confirm_sign_by_token(
        db, token, signature=payload.signature, confirm_name=payload.confirm_name,
    )
    pdf = _pdf_payload(case, record)
    if case:
        # 免登操作没有登录用户：按办结单留审计，署名取员工确认的签署人姓名
        await record_audit_log(
            db, action="hr.offboarding.cert_sign", user_id=None,
            resource_type="hr_offboarding_case", resource_id=case.id,
            new_value={"signed_name": record.cert_sign_name, "via": "h5_token"},
        )
        await db.commit()
    logger.info("离职证明签字页确认成功: %s 工号=%s", record.name, record.employee_number)
    return success_response(
        data={
            "signed_at": record.cert_signed_at.isoformat() if record.cert_signed_at else None,
            "case_status": case.status if case else None,
            **pdf,
        },
        message="签字确认成功",
    )
