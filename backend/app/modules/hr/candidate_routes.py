"""候选人管理接口"""

import os, shutil
from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access
from app.shared.schemas import PageParams

router = APIRouter(tags=["HR-候选人"])


@router.post("/candidates/parse-resume", summary="解析简历")
async def parse_cv(file: UploadFile = Form(..., alias="resume")):
    if not file.filename or not file.filename.endswith(".pdf"): raise HTTPException(400, "仅支持PDF")
    from app.modules.hr.resume_parser import parse_resume_pdf
    os.makedirs("uploads/resumes", exist_ok=True)
    content = bytes(await file.read())
    path = f"uploads/resumes/{file.filename}"
    open(path, "wb").write(content)
    r = parse_resume_pdf(content); r["resume_file_path"] = path
    return success_response(data=r)


@router.get("/candidates", summary="候选人列表")
async def list_candidates(page_params: PageParams = Depends(), session: AsyncSession = Depends(get_db)):
    r = await session.execute(text("SELECT id,name,phone,email,position,department,gender,school,education,major,status,recommendation_level,job_requirement_id FROM hr.candidates WHERE is_deleted=false ORDER BY created_at DESC LIMIT :lim OFFSET :off"), {"lim": page_params.page_size, "off": (page_params.page-1)*page_params.page_size})
    return success_response(data=[{"id":str(row[0]),"name":row[1],"phone":row[2],"email":row[3],"position":row[4],"department":row[5],"gender":row[6],"school":row[7],"education":row[8],"major":row[9],"status":row[10],"recommendation_level":row[11],"job_requirement_id":str(row[12]) if row[12] else None} for row in r])


@router.post("/candidates", summary="创建候选人")
async def create_candidate(payload: dict, session: AsyncSession = Depends(get_db)):
    rp = None
    if payload.get("resume_file_path") and os.path.exists(payload["resume_file_path"]):
        os.makedirs("uploads/resumes", exist_ok=True)
        rp = f"uploads/resumes/{payload.get('name','candidate')}_{os.path.basename(payload['resume_file_path'])}"
        shutil.copy(payload["resume_file_path"], rp)
    await session.execute(text("INSERT INTO hr.candidates (id,name,phone,email,position,department,gender,school,education,major,status,recommendation_level,job_requirement_id,resume_url,created_at,updated_at) VALUES (gen_random_uuid(),:n,:ph,:em,:pos,:dept,:g,:sch,:edu,:maj,:st,:rl,:jid,:rp,now(),now())"), {"n":payload.get("name",""),"ph":payload.get("phone",""),"em":payload.get("email",""),"pos":payload.get("position",""),"dept":payload.get("department",""),"g":payload.get("gender",""),"sch":payload.get("school",""),"edu":payload.get("education",""),"maj":payload.get("major",""),"st":payload.get("status","待筛选"),"rl":payload.get("recommendation_level",""),"jid":payload.get("job_requirement_id"),"rp":rp})
    await session.commit(); return success_response(message="创建成功", status_code=201)


@router.get("/candidates/{cid}", summary="候选人详情")
async def get_candidate(cid: UUID, session: AsyncSession = Depends(get_db)):
    r = await session.execute(text("SELECT id,name,phone,email,position,department,gender,school,education,major,status,recommendation_level,job_requirement_id FROM hr.candidates WHERE id=:id AND is_deleted=false"), {"id": cid})
    row = r.first()
    if not row: raise HTTPException(404, "不存在")
    return success_response(data={"id":str(row[0]),"name":row[1],"phone":row[2],"email":row[3],"position":row[4],"department":row[5],"gender":row[6],"school":row[7],"education":row[8],"major":row[9],"status":row[10],"recommendation_level":row[11],"job_requirement_id":str(row[12]) if row[12] else None})


@router.put("/candidates/{cid}", summary="更新候选人")
async def update_candidate(cid: UUID, payload: dict, session: AsyncSession = Depends(get_db)):
    await session.execute(text("UPDATE hr.candidates SET name=COALESCE(:n,name),phone=COALESCE(:ph,phone),email=COALESCE(:em,email),position=COALESCE(:pos,position),department=COALESCE(:dept,department),gender=COALESCE(:g,gender),school=COALESCE(:sch,school),education=COALESCE(:edu,education),major=COALESCE(:maj,major),status=COALESCE(:st,status),recommendation_level=COALESCE(:rl,recommendation_level) WHERE id=:id AND is_deleted=false"), {"n":payload.get("name"),"ph":payload.get("phone"),"em":payload.get("email"),"pos":payload.get("position"),"dept":payload.get("department"),"g":payload.get("gender"),"sch":payload.get("school"),"edu":payload.get("education"),"maj":payload.get("major"),"st":payload.get("status"),"rl":payload.get("recommendation_level"),"id": cid})
    await session.commit(); return success_response(message="已更新")


@router.delete("/candidates/{cid}", summary="删除候选人")
async def delete_candidate(cid: UUID, session: AsyncSession = Depends(get_db)):
    await session.execute(text("UPDATE hr.candidates SET is_deleted=true WHERE id=:id"), {"id": cid})
    await session.commit(); return success_response(message="已删除")


@router.get("/candidates/{cid}/resume-preview", summary="简历预览")
async def resume_preview(cid: UUID, session: AsyncSession = Depends(get_db)):
    r = await session.execute(text("SELECT resume_url FROM hr.candidates WHERE id=:id"), {"id": cid})
    row = r.first()
    if not row or not row[0]: raise HTTPException(404, "无简历文件")
    if not os.path.exists(row[0]): raise HTTPException(404, "简历文件不存在")
    from fastapi.responses import FileResponse
    return FileResponse(row[0], media_type="application/pdf")


@router.post("/candidates/{cid}/send-offer", summary="发送Offer")
async def send_offer(
    cid: UUID, candidate_email: str = Form(...), candidate_name: str = Form(""),
    position: str = Form(""), department: str = Form(""),
    base_salary: str = Form(""), salary_range: str = Form(""),
    medical_date: str = Form(""), report_date: str = Form(""),
    offer_expire_date: str = Form(""),
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import EmailLog
    from app.modules.hr.offer_generator import generate_offer_docx
    from app.platform.mail_service import send_email
    n = candidate_name or "候选人"
    docx_buf = generate_offer_docx(
        name=n, department=department, position=position,
        base_salary=base_salary, salary_range=salary_range,
        medical_date=medical_date, report_date=report_date,
        offer_expire_date=offer_expire_date,
    )
    filename = f"入职Offer_{n}.docx"
    html = f"<html><body style=\"font-family:sans-serif;padding:20px;\"><h2>入职 Offer</h2><p>{n}，您好！</p><p>部门：{department} 岗位：{position}</p><p>请查看附件中的 Offer 通知书，并在3个工作日内<b>回复此邮件</b>确认是否接受。</p></body></html>"
    subj = f"入职 Offer — {position}" if position else "入职 Offer"
    try:
        send_email(to=candidate_email, subject=subj, html_body=html, attachments=[(filename, docx_buf.read())]); st, err = "sent", None
    except Exception as e:
        st, err = "failed", str(e)
    session.add(EmailLog(email_type="offer", employee_name=n, recipient=candidate_email, subject=subj, status=st, error_message=err))
    await session.commit()
    if st == "failed": raise HTTPException(500, f"发送失败: {err}")
    return success_response(message="Offer已发送")


@router.post("/candidates/{cid}/preview-offer", summary="预览Offer")
async def preview_offer(
    cid: UUID, candidate_name: str = Form(""), position: str = Form(""),
    department: str = Form(""), base_salary: str = Form(""),
    salary_range: str = Form(""), medical_date: str = Form(""),
    report_date: str = Form(""), offer_expire_date: str = Form(""),
):
    from fastapi.responses import HTMLResponse
    from app.modules.hr.offer_generator import generate_offer_html
    html = generate_offer_html(
        name=candidate_name or "候选人", department=department, position=position,
        base_salary=base_salary, salary_range=salary_range,
        medical_date=medical_date, report_date=report_date,
        offer_expire_date=offer_expire_date,
    )
    return HTMLResponse(content=html)
