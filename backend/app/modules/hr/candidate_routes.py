"""候选人管理接口"""

import os
import shutil
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.schemas import (
    CandidateCreate,
    CandidateResponse,
    CandidateStatusTransition,
    CandidateUpdate,
)
from app.modules.hr.service import CandidateService
from app.shared.schemas import PageParams

router = APIRouter(tags=["HR-候选人"])


def get_service(session: AsyncSession = Depends(get_db)) -> CandidateService:
    return CandidateService(session)


# ─── 简历解析 ───


@router.post("/candidates/parse-resume", summary="解析简历")
async def parse_cv(file: UploadFile = Form(..., alias="resume")):
    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(400, "仅支持PDF")
    from app.modules.hr.resume_parser import parse_resume_pdf
    os.makedirs("uploads/resumes", exist_ok=True)
    content = bytes(await file.read())
    path = f"uploads/resumes/{file.filename}"
    open(path, "wb").write(content)
    r = parse_resume_pdf(content)
    r["resume_file_path"] = path
    return success_response(data=r)


# ─── 候选人 CRUD ───


@router.get("/candidates", summary="候选人列表")
async def list_candidates(
    job_requirement_id: UUID | None = Query(None, description="按岗位需求筛选"),
    status: str | None = Query(None, description="按状态筛选"),
    keyword: str | None = Query(None, description="按姓名/手机搜索"),
    candidate_type: str | None = Query(None, description="按类型筛选: 普工/职能"),
    page_params: PageParams = Depends(),
    service: CandidateService = Depends(get_service),
):
    rows, total = await service.list_all(
        job_requirement_id=job_requirement_id,
        status=status,
        keyword=keyword,
        candidate_type=candidate_type,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    return success_response(
        data=[CandidateResponse.model_validate(r).model_dump(mode="json") for r in rows],
        meta={"page": page_params.page, "page_size": page_params.page_size, "total": total},
    )


@router.post("/candidates", summary="创建候选人")
async def create_candidate(
    payload: CandidateCreate,
    service: CandidateService = Depends(get_service),
):
    r = await service.create(payload)
    return success_response(data=CandidateResponse.model_validate(r).model_dump(mode="json"), message="创建成功", status_code=201)


@router.get("/candidates/{cid}", summary="候选人详情")
async def get_candidate(cid: UUID, service: CandidateService = Depends(get_service)):
    r = await service.get(cid)
    return success_response(data=CandidateResponse.model_validate(r).model_dump(mode="json"))


@router.put("/candidates/{cid}", summary="更新候选人")
async def update_candidate(cid: UUID, payload: CandidateUpdate, service: CandidateService = Depends(get_service)):
    r = await service.update(cid, payload)
    return success_response(data=CandidateResponse.model_validate(r).model_dump(mode="json"), message="已更新")


@router.delete("/candidates/{cid}", summary="删除候选人")
async def delete_candidate(cid: UUID, service: CandidateService = Depends(get_service)):
    await service.delete(cid)
    return success_response(message="已删除")


@router.put("/candidates/{cid}/status", summary="候选人状态流转")
async def transition_status(cid: UUID, payload: CandidateStatusTransition, service: CandidateService = Depends(get_service)):
    try:
        r = await service.transition_status(cid, payload.status, payload.remark)
        return success_response(data=CandidateResponse.model_validate(r).model_dump(mode="json"), message=f"状态已变更为「{payload.status}」")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/candidates/{cid}/status-logs", summary="候选人状态流转日志")
async def get_status_logs(cid: UUID, service: CandidateService = Depends(get_service)):
    logs = await service.get_status_logs(cid)
    return success_response(data=[{
        "id": str(log.id),
        "from_status": log.from_status,
        "to_status": log.to_status,
        "operator": log.operator,
        "remark": log.remark,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    } for log in logs])


# ─── 简历预览 ───


@router.get("/candidates/{cid}/resume-preview", summary="简历预览")
async def resume_preview(cid: UUID, service: CandidateService = Depends(get_service)):
    r = await service.get(cid)
    if not r.resume_url or not os.path.exists(r.resume_url):
        raise HTTPException(404, "无简历文件")
    return FileResponse(r.resume_url, media_type="application/pdf")


# ─── Offer 发送与预览 ───


@router.post("/candidates/{cid}/send-offer", summary="发送Offer")
async def send_offer(
    cid: UUID,
    candidate_email: str = Form(...),
    candidate_name: str = Form(""),
    position: str = Form(""),
    department: str = Form(""),
    base_salary: str = Form(""),
    salary_range: str = Form(""),
    medical_date: str = Form(""),
    report_date: str = Form(""),
    offer_expire_date: str = Form(""),
    service: CandidateService = Depends(get_service),
    session: AsyncSession = Depends(get_db),
):
    from datetime import date as date_type

    from app.modules.hr.mail_service import send_email
    from app.modules.hr.models import EmailLog
    from app.modules.hr.offer_generator import generate_offer_pdf

    n = candidate_name or "候选人"
    pdf_buf = generate_offer_pdf(
        name=n, department=department, position=position,
        base_salary=base_salary, salary_range=salary_range,
        medical_date=medical_date, report_date=report_date,
        offer_expire_date=offer_expire_date,
    )
    filename = f"入职Offer_{n}.pdf"
    html = (
        f"<html><body style=\"font-family:sans-serif;padding:20px;\">"
        f"<h2>入职 Offer</h2><p>{n}，您好！</p>"
        f"<p>部门：{department} 岗位：{position}</p>"
        f"<p>请查看附件中的 Offer 通知书，并在3个工作日内<b>回复此邮件</b>确认是否接受。</p>"
        f"</body></html>"
    )
    subj = f"入职 Offer — {position}" if position else "入职 Offer"
    try:
        send_email(to=candidate_email, subject=subj, html_body=html, attachments=[(filename, pdf_buf.read())])
        st, err = "sent", None
    except Exception as e:
        st, err = "failed", str(e)
    session.add(EmailLog(email_type="offer", employee_name=n, recipient=candidate_email, subject=subj, status=st, error_message=err))
    if st == "sent":
        c = await service.get(cid)
        c.offer_status = "已发送"
        c.offer_sent_at = date_type.today()
        await service.update(cid, CandidateUpdate(offer_status="已发送"))
    await session.commit()
    if st == "failed":
        raise HTTPException(500, f"发送失败: {err}")
    return success_response(message="Offer已发送")


@router.post("/candidates/{cid}/preview-offer", summary="预览Offer")
async def preview_offer(
    cid: UUID,
    candidate_name: str = Form(""),
    position: str = Form(""),
    department: str = Form(""),
    base_salary: str = Form(""),
    salary_range: str = Form(""),
    medical_date: str = Form(""),
    report_date: str = Form(""),
    offer_expire_date: str = Form(""),
):
    from app.modules.hr.offer_generator import generate_offer_html
    html = generate_offer_html(
        name=candidate_name or "候选人", department=department, position=position,
        base_salary=base_salary, salary_range=salary_range,
        medical_date=medical_date, report_date=report_date,
        offer_expire_date=offer_expire_date,
    )
    return HTMLResponse(content=html)
