"""候选人管理接口"""

import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.schemas import (
    CandidateAnalysisReportOut,
    CandidateCreate,
    CandidateResponse,
    CandidateStatusTransition,
    CandidateUpdate,
    DecideReviewRequest,
    PushReviewRequest,
)
from app.modules.hr.service import CandidateAnalysisService, CandidateService
from app.shared.schemas import PageParams

router = APIRouter(tags=["HR-候选人"])


def get_service(session: AsyncSession = Depends(get_db)) -> CandidateService:
    return CandidateService(session)


def get_candidate_analysis_service(session: AsyncSession = Depends(get_db)) -> CandidateAnalysisService:
    return CandidateAnalysisService(session)


# ─── 简历解析 ───


@router.post("/candidates/parse-resume", summary="解析简历")
async def parse_cv(file: UploadFile = Form(..., alias="resume")):
    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(400, "仅支持PDF")
    from app.modules.hr.resume_parser import parse_resume_pdf
    os.makedirs("uploads/resumes", exist_ok=True)
    content = bytes(await file.read())
    # 文件名加 uuid 前缀，避免同名简历互相覆盖
    path = f"uploads/resumes/{uuid4().hex[:8]}_{file.filename}"
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


@router.post("/candidates/upload", summary="批量导入候选人")
async def upload_candidates(
    file: UploadFile,
    service: CandidateService = Depends(get_service),
):
    """上传 Excel 文件批量导入候选人，按姓名+手机/邮箱自动去重新增或更新。"""
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "仅支持 .xlsx / .xls 格式")
    try:
        content = await file.read()
        result = await service.upload_candidates(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(
        data=result,
        message=f"新增 {result['created']}，更新 {result['updated']}"
    )


@router.get("/candidates/template", summary="下载候选人导入模板")
async def download_candidate_template():
    """下载候选人批量导入 Excel 模板"""
    from io import BytesIO
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    headers = list(CandidateService._CANDIDATE_UPLOAD_COLUMN_MAP.keys())
    ws.append(headers)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=candidate_import_template.xlsx"},
    )


@router.post("/candidates", summary="创建候选人")
async def create_candidate(
    payload: CandidateCreate,
    service: CandidateService = Depends(get_service),
):
    r = await service.create(payload)
    return success_response(data=CandidateResponse.model_validate(r).model_dump(mode="json"), message="创建成功", status_code=201)


# ─── 推送审核（必须在 /candidates/{cid} 之前，避免路径冲突）───


@router.get("/candidates/pending-review", summary="待我审核的候选人列表")
async def list_pending_review(
    reviewer: str | None = Query(None, description="审核人姓名"),
    service: CandidateService = Depends(get_service),
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    from app.modules.hr.schemas import CandidateReviewResponse
    from app.modules.hr.service import CandidateReviewService
    rv_service = CandidateReviewService(session)
    # 缺省按当前用户过滤（“待我审核”语义），显式传 reviewer 时按指定人查询
    rows = await rv_service.list_pending(
        reviewer=reviewer or hr_scope.user.name or None
    )
    return success_response(data=[{
        "review": CandidateReviewResponse.model_validate(row["review"]).model_dump(mode="json"),
        "candidate": CandidateResponse.model_validate(row["candidate"]).model_dump(mode="json"),
        "job_requirement": {"id": str(row["job_requirement"].id), "position_name": row["job_requirement"].position_name, "department": row["job_requirement"].department} if row["job_requirement"] else None,
    } for row in rows])


# ─── 候选人详情（动态路径放后面）───


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


@router.post("/candidates/{cid}/push-review", summary="推送候选人给用人部门审核")
async def push_review(
    cid: UUID,
    payload: PushReviewRequest,
    service: CandidateService = Depends(get_service),
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.service import CandidateReviewService
    rv_service = CandidateReviewService(session)
    try:
        r = await rv_service.push(cid, payload.pushed_by or "HR", payload.push_note, payload.reviewer)
        return success_response(data={"id": str(r.id), "status": r.status}, message="已推送至用人部门审核")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/recruitment/stats", summary="招聘统计概览")
async def recruitment_stats(session: AsyncSession = Depends(get_db)):
    from app.modules.hr.models import Candidate
    from app.modules.hr.repository import CandidateRepository, JobRequirementRepository

    candidate_repo = CandidateRepository(session)
    jd_repo = JobRequirementRepository(session)

    total_candidates = await candidate_repo.count_total()
    active_jobs = await jd_repo.count_active()

    # 一次 GROUP BY 查询代替 8 次顺序 count_by_status
    status_counts = await candidate_repo.count_group_by_status()
    statuses = ["待筛选", "已筛选", "待部门审核", "面试中", "已面试", "录用中", "已录用", "待入职审批", "已入职", "已拒绝"]
    funnel = [{"status": s, "count": status_counts.get(s, 0)} for s in statuses]

    # 转化率：相邻阶段之间
    rates = []
    for i in range(len(statuses) - 1):
        this_count = status_counts.get(statuses[i], 0)
        next_count = status_counts.get(statuses[i + 1], 0)
        rate = round(next_count / this_count * 100, 1) if this_count > 0 else 0
        rates.append({"from": statuses[i], "to": statuses[i + 1], "rate": rate})

    # 平均招聘周期（从创建到入职的天数，仅统计已入职）
    cycle_days = None
    from sqlalchemy import func as sa_func
    cycle_result = (await session.execute(
        select(sa_func.avg(
            sa_func.extract('epoch', Candidate.updated_at - Candidate.created_at) / 86400
        )).where(Candidate.status == "已入职", Candidate.is_deleted == False)  # noqa: E712
    )).scalar()
    if cycle_result:
        cycle_days = round(float(cycle_result), 1)

    # 各岗位招聘进度
    jd_list = await jd_repo.list_all(status=None)
    job_progress = [{
        "id": str(j.id),
        "position_name": j.position_name,
        "department": j.department,
        "headcount": j.headcount,
        "hired_count": j.hired_count or 0,
    } for j in jd_list]

    # 月度入职趋势（近12个月）
    monthly_hires_raw = await candidate_repo.count_monthly_hires(months=12)
    monthly_hires = [
        {"month": f"{h['year']}-{h['month']:02d}", "count": h['count']}
        for h in monthly_hires_raw
    ]

    # 来源渠道分析
    source_stats = await candidate_repo.count_by_source()

    return success_response(data={
        "total_candidates": total_candidates,
        "active_jobs": active_jobs,
        "funnel": funnel,
        "conversion_rates": rates,
        "avg_cycle_days": cycle_days,
        "job_progress": job_progress,
        "monthly_hires": monthly_hires,
        "source_stats": source_stats,
    })


@router.post("/candidates/{cid}/onboard", summary="一键入职")
async def onboard_candidate(
    cid: UUID,
    service: CandidateService = Depends(get_service),
):
    from app.modules.hr.service import NotFoundException
    try:
        _, onboarding, emp_no = await service.onboard(cid)
        await service.repo.session.commit()
        return success_response(data={"id": str(onboarding.id), "employee_number": emp_no}, message="入职成功")
    except NotFoundException as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/candidates/{cid}/decide-review", summary="审核候选人")
async def decide_review(
    cid: UUID,
    payload: DecideReviewRequest,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    from app.modules.hr.schemas import CandidateReviewResponse
    from app.modules.hr.service import CandidateReviewService
    from app.platform.permission.deps import get_user_permissions

    rv_service = CandidateReviewService(session)
    try:
        # 支持通过 review_id 或自动按 candidate_id 查找待审核记录
        if payload.review_id:
            review_id = UUID(payload.review_id)
        else:
            review_id = await rv_service.find_pending_review_id(cid)
        # 仅审核人（或管理权限）可做审核决策
        rv = await rv_service.repo.get_by_id(review_id)
        perms = await get_user_permissions(str(hr_scope.user.id), session)
        is_manager = "hr:recruitment:manage" in perms
        if not is_manager and rv and rv.reviewer and rv.reviewer != hr_scope.user.name:
            raise HTTPException(403, f"该审核由 {rv.reviewer} 负责，您无权操作")
        r = await rv_service.decide(review_id, payload.decision, payload.review_comment)
        return success_response(data=CandidateReviewResponse.model_validate(r).model_dump(mode="json"), message="审核完成")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/candidates/{cid}/push-onboarding-review", summary="发起入职审批")
async def push_onboarding_review(
    cid: UUID,
    payload: PushReviewRequest,
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.schemas import CandidateReviewResponse
    from app.modules.hr.service import CandidateReviewService
    rv_service = CandidateReviewService(session)
    try:
        r = await rv_service.push_onboarding(cid, payload.pushed_by or "HR", payload.push_note)
        return success_response(data=CandidateReviewResponse.model_validate(r).model_dump(mode="json"), message="入职审批已发起")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/candidates/{cid}/onboarding-tasks", summary="获取入职子任务列表")
async def get_onboarding_tasks(
    cid: UUID,
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.schemas import OnboardingTaskResponse
    from app.modules.hr.service import OnboardingTaskService
    tasks = await OnboardingTaskService(session).list_by_candidate(cid)
    return success_response(data=[OnboardingTaskResponse.model_validate(t).model_dump(mode="json") for t in tasks])


@router.put("/candidates/{cid}/onboarding-tasks/{task_id}", summary="更新入职子任务")
async def update_onboarding_task(
    cid: UUID,
    task_id: UUID,
    payload: dict,
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.schemas import OnboardingTaskResponse
    from app.modules.hr.service import OnboardingTaskService
    task = await OnboardingTaskService(session).update(task_id, payload)
    return success_response(data=OnboardingTaskResponse.model_validate(task).model_dump(mode="json"), message="任务已更新")


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
    additional_terms: str = Form(""),
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
        additional_terms=additional_terms,
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
        await send_email(to=candidate_email, subject=subj, html_body=html, attachments=[(filename, pdf_buf.read())], session=session)
        st, err = "sent", None
    except Exception as e:
        st, err = "failed", str(e)
    session.add(EmailLog(email_type="offer", employee_name=n, recipient=candidate_email, subject=subj, status=st, error_message=err))
    if st == "sent":
        await service.update(cid, CandidateUpdate(offer_status="已发送", offer_sent_at=date_type.today()))
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
    additional_terms: str = Form(""),
):
    from app.modules.hr.offer_generator import generate_offer_html
    html = generate_offer_html(
        name=candidate_name or "候选人", department=department, position=position,
        base_salary=base_salary, salary_range=salary_range,
        medical_date=medical_date, report_date=report_date,
        offer_expire_date=offer_expire_date,
        additional_terms=additional_terms,
    )
    return HTMLResponse(content=html)


# ─── 候选人胜任度多维分析报告 ───


@router.get("/candidates/{candidate_id}/analysis-reports", summary="候选人胜任度分析报告列表")
async def list_analysis_reports(
    candidate_id: UUID,
    service: CandidateAnalysisService = Depends(get_candidate_analysis_service),
):
    reports = await service.list_by_candidate(candidate_id)
    return success_response(data=[
        CandidateAnalysisReportOut.model_validate(r).model_dump(mode="json") for r in reports
    ])


@router.post("/candidates/{candidate_id}/analysis-reports", summary="生成胜任度分析报告")
async def generate_analysis_report(
    candidate_id: UUID,
    payload: dict,
    service: CandidateAnalysisService = Depends(get_candidate_analysis_service),
):
    """基于面试记录自动生成多维度胜任度报告（面试建议自动联动写入面试备注）。"""
    interview_id = payload.get("interview_id")
    if not interview_id:
        raise HTTPException(400, "请提供面试记录ID")
    try:
        report = await service.generate(candidate_id, UUID(str(interview_id)))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(
        data=CandidateAnalysisReportOut.model_validate(report).model_dump(mode="json"),
        message="报告已生成",
    )
