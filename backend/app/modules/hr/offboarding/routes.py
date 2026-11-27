"""离职管理 HTTP 路由：办结单 CRUD、审批推进、清退明细、证明开具/送达/办结。

本 router 挂在 hr 模块路由下（require_hr 门禁 + _HR_PATH_PERMISSIONS 映射，
权限复用 hr:departure:read/manage）；公开签字路由 sign_routes.sign_router
挂在全局 api_router（免登，token 即凭证）；台账增强见 ledger_routes.py。
"""

import logging
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException, ForbiddenException
from app.core.file_storage import content_disposition
from app.core.response import paginated_response, success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access
from app.modules.hr.offboarding import certificate as cert_gen
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding import service
from app.modules.hr.offboarding import settings as offboarding_settings
from app.modules.hr.offboarding.models import OffboardingCase, OffboardingClearanceItem
from app.modules.hr.offboarding.schemas import (
    ClearanceBulkReplace,
    CloseCaseRequest,
    IssueCertificateRequest,
    ManualStageDone,
    OffboardingCaseCreate,
    OffboardingCaseUpdate,
    PaperSignRequest,
    SendDeliveryRequest,
)
from app.platform.audit.service import record_audit_log

logger = logging.getLogger(__name__)

router = APIRouter(tags=["HR-离职管理"])

RESOURCE_TYPE = "hr_offboarding_case"


# ─── 序列化 ───

def _item_dict(item: OffboardingClearanceItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "category": item.category,
        "category_label": OffboardingClearanceItem.CATEGORY_LABELS.get(item.category, item.category),
        "item_name": item.item_name,
        "status": item.status,
        "status_label": OffboardingClearanceItem.STATUS_LABELS.get(item.status, item.status),
        "deduction_amount": float(item.deduction_amount) if item.deduction_amount is not None else None,
        "supplement_amount": float(item.supplement_amount) if item.supplement_amount is not None else None,
        "remark": item.remark,
        "confirmed_by": item.confirmed_by,
        "confirmed_at": item.confirmed_at.isoformat() if item.confirmed_at else None,
        "source": item.source,
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _case_dict(case: OffboardingCase, *, items: list[OffboardingClearanceItem] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(case.id),
        "case_no": case.case_no,
        "employee_id": str(case.employee_id),
        "departure_record_id": str(case.departure_record_id) if case.departure_record_id else None,
        "employee_number": case.employee_number,
        "name": case.name,
        "department": case.department,
        "position": case.position,
        "level": case.level,
        "initiator_name": case.initiator_name,
        "offboarding_date": case.offboarding_date.isoformat(),
        "offboarding_type": case.offboarding_type,
        "reason": case.reason,
        "employee_category": case.employee_category,
        "application_submitted": case.application_submitted,
        "status": case.status,
        "status_label": case.status_label,
        "approval_track": case.approval_track,
        "resignation_instance_code": case.resignation_instance_code,
        "resignation_finished_at": _iso(case.resignation_finished_at),
        "clearance_instance_code": case.clearance_instance_code,
        "clearance_finished_at": _iso(case.clearance_finished_at),
        "health_check_required": case.health_check_required,
        "health_check_done": case.health_check_done,
        "health_check_date": _iso(case.health_check_date),
        "health_check_file_name": case.health_check_file_name,
        "has_health_check_file": bool(case.health_check_file_key),
        "cert_template": case.cert_template,
        "cert_issued_at": _iso(case.cert_issued_at),
        "cert_issued_by": case.cert_issued_by,
        "has_cert_file": bool(case.cert_storage_key),
        "mail_recipient": case.mail_recipient,
        "mail_sent_at": _iso(case.mail_sent_at),
        "mail_status": case.mail_status,
        "sms_phone": case.sms_phone,
        "sms_status": case.sms_status,
        "delivery_channel": case.delivery_channel,
        "paper_signed_at": _iso(case.paper_signed_at),
        "paper_signed_by": case.paper_signed_by,
        "account_deactivated": case.account_deactivated,
        "closed_at": _iso(case.closed_at),
        "remark": case.remark,
        "created_at": _iso(case.created_at),
    }
    if items is not None:
        data["clearance_items"] = [_item_dict(i) for i in items]
    return data


# ─── 数据范围 ───

async def _ensure_in_scope(ctx: HrAccessContext, case: OffboardingCase) -> None:
    if ctx.is_unrestricted:
        return
    ctx.ensure_can_access_department(case.department)


def _scope_departments(ctx: HrAccessContext) -> frozenset[str] | None:
    """None = 不限；空集 = 无可见部门（self_only）。"""
    if ctx.is_unrestricted:
        return None
    if ctx.data_scope == "self_only":
        return frozenset()
    return ctx.scoped_departments or (
        frozenset({ctx.department}) if ctx.department else frozenset()
    )


# ─── 办结单 CRUD ───

@router.get("/offboarding-cases", summary="离职办理列表（分页）")
async def list_cases(
    status: str | None = Query(None, description="状态过滤"),
    department: str | None = Query(None, max_length=64),
    keyword: str | None = Query(None, max_length=64, description="姓名/工号/部门/岗位模糊"),
    date_from: date | None = Query(None, description="离职日期起"),
    date_to: date | None = Query(None, description="离职日期止"),
    overdue: bool = Query(False, description="仅看临期 / 超期单（审批或清退中且距离职日 ≤ 2 天）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> JSONResponse:
    departments = _scope_departments(ctx)
    if department:
        if departments is not None and department not in departments:
            raise ForbiddenException("数据范围限制：仅可查看授权部门")
        departments = frozenset({department})
    rows, total = await repo.list_cases(
        db, status=status, departments=departments, overdue=overdue,
        keyword=keyword, offboarding_date_from=date_from, offboarding_date_to=date_to,
        page=page, page_size=page_size,
    )
    return paginated_response(
        data=[_case_dict(c) for c in rows], total=total, page=page, page_size=page_size
    )


@router.get("/offboarding-cases/stats", summary="离职办理统计（各状态单数 + 临期单数）")
async def case_stats(
    department: str | None = Query(None, max_length=64),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> JSONResponse:
    """看板页头用。静态段必须排在 /offboarding-cases/{case_id} 之前，否则会被当成 UUID 解析。"""
    departments = _scope_departments(ctx)
    if department:
        if departments is not None and department not in departments:
            raise ForbiddenException("数据范围限制：仅可查看授权部门")
        departments = frozenset({department})
    counts = await repo.count_cases_by_status(db, departments=departments)
    overdue = await repo.count_overdue_cases(db, departments=departments)
    return success_response(data={
        "counts": counts,
        "overdue": overdue,
        "total": sum(counts.values()),
        "active": sum(count for status, count in counts.items() if status in OffboardingCase.FLOW_ORDER[:-1]),
    })


@router.post("/offboarding-cases", summary="发起离职办理（按档案快照建单）")
async def create_case(
    payload: OffboardingCaseCreate,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> JSONResponse:
    case = await service.create_case(
        db,
        employee_id=payload.employee_id,
        offboarding_date=payload.offboarding_date,
        offboarding_type=payload.offboarding_type,
        reason=payload.reason,
        application_submitted=payload.application_submitted,
        health_check_required=payload.health_check_required,
        remark=payload.remark,
        user_id=ctx.user.id,
        initiator_name=ctx.user.name,
    )
    await record_audit_log(
        db, action="hr.offboarding.create", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=case.id,
        new_value={"case_no": case.case_no, "employee_number": case.employee_number,
                   "offboarding_date": case.offboarding_date.isoformat()},
    )
    return success_response(data=_case_dict(case), message="离职办理已创建")


@router.get("/offboarding-cases/{case_id}", summary="离职办理详情（含清退明细与签字状态）")
async def get_case(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> JSONResponse:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    items = await repo.list_clearance_items(db, case.id)
    kv = await offboarding_settings.load_offboarding_settings(db)
    stage_kwargs = {"track": case.approval_track, "level": case.level}
    data: dict[str, Any] = {
        **_case_dict(case, items=items),
        # 两个审批环节是否接了飞书：未接则走站内登记，前端据此提示与显隐
        "resignation_feishu": offboarding_settings.stage_configured(
            kv, stage="resignation", **stage_kwargs,
        ),
        "clearance_feishu": offboarding_settings.stage_configured(
            kv, stage="clearance", **stage_kwargs,
        ),
    }
    record = await service.linked_record(db, case)
    data["sign_state"] = None if record is None else {
        "cert_sign_status": record.cert_sign_status,
        "cert_signed_at": _iso(record.cert_signed_at),
        "cert_sign_name": record.cert_sign_name,
        "has_sign_image": bool(record.cert_sign_image),
        "cert_issued_at": _iso(record.cert_issued_at),
    }
    return success_response(data=data)


@router.put("/offboarding-cases/{case_id}", summary="编辑离职办理基本信息")
async def update_case(
    case_id: UUID,
    payload: OffboardingCaseUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> JSONResponse:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    case = await service.update_case(
        db, case,
        offboarding_date=payload.offboarding_date,
        offboarding_type=payload.offboarding_type,
        reason=payload.reason,
        application_submitted=payload.application_submitted,
        health_check_required=payload.health_check_required,
        remark=payload.remark,
        user_id=ctx.user.id,
    )
    await record_audit_log(
        db, action="hr.offboarding.update", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=case.id,
        new_value=payload.model_dump(exclude_unset=True),
    )
    return success_response(data=_case_dict(case), message="已保存")


@router.post("/offboarding-cases/{case_id}/cancel", summary="取消离职办理")
async def cancel_case(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> JSONResponse:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    previous = case.status
    case = await service.cancel_case(db, case, user_id=ctx.user.id)
    await record_audit_log(
        db, action="hr.offboarding.cancel", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=case.id,
        old_value={"status": previous}, new_value={"status": case.status},
    )
    return success_response(data=_case_dict(case), message="已取消")


# ─── 流程推进 ───

@router.post("/offboarding-cases/{case_id}/submit-approval", summary="发起离职审批（体检门禁+飞书编排，未配置降级站内）")
async def submit_approval(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> JSONResponse:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    case, warning = await service.submit_approval(
        db, case, user_id=ctx.user.id, operator_open_id=ctx.user.feishu_open_id,
    )
    await record_audit_log(
        db, action="hr.offboarding.submit_approval", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=case.id,
        new_value={"status": case.status, "instance_code": case.resignation_instance_code},
    )
    feishu = bool(case.resignation_instance_code)
    message = "已发起飞书离职审批" if feishu else "已提交，飞书审批未配置——部门负责人审批通过后请站内登记办结"
    return success_response(data=_case_dict(case), message=message + (f"；{warning}" if warning else ""))


@router.post("/offboarding-cases/{case_id}/manual-stage-done", summary="站内登记办结（审批定义未配置时的降级推进）")
async def manual_stage_done(
    case_id: UUID,
    payload: ManualStageDone,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> JSONResponse:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    case = await service.manual_stage_done(
        db, case, stage=payload.stage, note=payload.note, user_id=ctx.user.id,
        operator_open_id=ctx.user.feishu_open_id,
    )
    await record_audit_log(
        db, action="hr.offboarding.manual_stage_done", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=case.id,
        new_value={"stage": payload.stage, "note": payload.note},
    )
    return success_response(data=_case_dict(case), message="已登记办结并推进")


@router.put("/offboarding-cases/{case_id}/clearance-items", summary="保存清退明细（全量替换）")
async def replace_clearance_items(
    case_id: UUID,
    payload: ClearanceBulkReplace,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> JSONResponse:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    items = await service.replace_clearance_items(
        db, case, [i.model_dump() for i in payload.items], user_id=ctx.user.id,
    )
    await record_audit_log(
        db, action="hr.offboarding.save_clearance", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=case.id,
        new_value={"count": len(items)},
    )
    return success_response(data=[_item_dict(i) for i in items], message="清退明细已保存")


@router.post("/offboarding-cases/{case_id}/health-check", summary="离岗体检登记（重点岗位门禁，可传报告附件）")
async def register_health_check(
    case_id: UUID,
    health_check_done: bool = Form(...),
    health_check_date: date | None = Form(None),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> JSONResponse:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    file_bytes = await file.read() if file else None
    case = await service.register_health_check(
        db, case,
        done=health_check_done,
        check_date=health_check_date,
        file_name=file.filename if file else None,
        file_bytes=file_bytes,
        user_id=ctx.user.id,
    )
    await record_audit_log(
        db, action="hr.offboarding.health_check", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=case.id,
        new_value={"done": case.health_check_done, "date": _iso(case.health_check_date)},
    )
    return success_response(data=_case_dict(case), message="体检登记已保存")


@router.get("/offboarding-cases/{case_id}/health-check-file", summary="下载体检报告附件")
async def download_health_check_file(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> Response:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    stored = service.read_health_check_file(case)
    if not stored:
        raise AppException(message="体检报告附件不存在", status_code=404)
    data, content_type = stored
    filename = case.health_check_file_name or "离岗体检报告"
    return Response(
        content=data, media_type=content_type,
        headers={"Content-Disposition": content_disposition("attachment", filename)},
    )


# ─── 证明开具 / 送达 / 签收 / 办结 ───

@router.get("/offboarding-cases/{case_id}/certificate-preview", summary="证明预览（核对页，template=electronic/paper）")
async def preview_certificate(
    case_id: UUID,
    template: str = Query("electronic", pattern="^(electronic|paper)$"),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> HTMLResponse:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    employee = await repo.get_employee(db, case.employee_id)
    record = await service.linked_record(db, case)
    fields = service.cert_fields(case, record, employee)
    generate = cert_gen.generate_paper_html if template == "paper" else cert_gen.generate_electronic_html
    return HTMLResponse(content=generate(**fields))


@router.post("/offboarding-cases/{case_id}/issue-certificate", summary="开具证明（生成 PDF 存档+台账回写+自动发邮件）")
async def issue_certificate(
    case_id: UUID,
    payload: IssueCertificateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> JSONResponse:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    case, warning, sign_url = await service.issue_certificate(
        db, case, cert_template=payload.cert_template,
        mail_recipient=payload.mail_recipient, issued_by=ctx.user.name, user_id=ctx.user.id,
    )
    await record_audit_log(
        db, action="hr.offboarding.issue_certificate", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=case.id,
        new_value={"template": payload.cert_template, "mail": payload.mail_recipient},
    )
    return success_response(
        data={**_case_dict(case), "sign_url": sign_url},
        message="证明已开具" + (f"；{warning}" if warning else ""),
    )


@router.post("/offboarding-cases/{case_id}/resend-delivery", summary="补发/重发送达（邮件重发；短信登记；不传参则只取签署链接）")
async def resend_delivery(
    case_id: UUID,
    payload: SendDeliveryRequest,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> JSONResponse:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    case, note, sign_url = await service.resend_delivery(
        db, case, mail_recipient=payload.mail_recipient,
        sms_phone=payload.sms_phone, user_id=ctx.user.id,
    )
    return success_response(
        data={**_case_dict(case), "sign_url": sign_url},
        message="送达处理完成" + (f"；{note}" if note else ""),
    )


@router.post("/offboarding-cases/{case_id}/paper-sign", summary="纸质两联版签收登记（当面签字，时间与方式留存）")
async def paper_sign(
    case_id: UUID,
    payload: PaperSignRequest,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> JSONResponse:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    case = await service.register_paper_sign(
        db, case, signed_by=payload.signed_by, user_id=ctx.user.id,
    )
    await record_audit_log(
        db, action="hr.offboarding.paper_sign", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=case.id,
        new_value={"signed_by": payload.signed_by},
    )
    return success_response(data=_case_dict(case), message="纸质签收已登记")


@router.post("/offboarding-cases/{case_id}/close", summary="办结（档案/证件/花名册/入职台账/离职台账联动）")
async def close_case(
    case_id: UUID,
    payload: CloseCaseRequest,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> JSONResponse:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    case = await service.close_case(
        db, case, account_deactivated=payload.account_deactivated, user_id=ctx.user.id,
    )
    await record_audit_log(
        db, action="hr.offboarding.close", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=case.id,
        new_value={"account_deactivated": payload.account_deactivated},
    )
    return success_response(data=_case_dict(case), message="已办结，档案与各台账已同步")


@router.get("/offboarding-cases/{case_id}/certificate-file", summary="下载证明 PDF")
async def download_certificate(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> Response:
    case = await service.get_or_404(db, case_id)
    await _ensure_in_scope(ctx, case)
    stored = service.read_certificate_pdf(case)
    if not stored:
        raise AppException(message="证明文件尚未生成", status_code=404)
    data, _content_type = stored
    return Response(
        content=data, media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(
            "attachment", f"解除劳动关系证明_{case.name}.pdf",
        )},
    )
