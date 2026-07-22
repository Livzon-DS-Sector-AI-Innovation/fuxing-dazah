"""岗位需求接口"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.response import success_response

router = APIRouter(tags=["HR-岗位需求"])


@router.get("/job-requirements", summary="岗位需求列表")
async def list_job_reqs(session: AsyncSession = Depends(get_db)):
    r = await session.execute(text("SELECT id,position_name,department,headcount,hired_count,requirements,status FROM hr.job_requirements WHERE is_deleted=false ORDER BY created_at DESC"))
    return success_response(data=[{"id":str(row[0]),"position_name":row[1],"department":row[2],"headcount":row[3],"hired_count":row[4],"requirements":row[5],"status":row[6]} for row in r])


@router.post("/job-requirements", summary="创建岗位需求")
async def create_job_req(payload: dict, session: AsyncSession = Depends(get_db)):
    await session.execute(text("INSERT INTO hr.job_requirements (id,position_name,department,headcount,requirements,status,created_at,updated_at) VALUES (gen_random_uuid(),:pn,:dept,:hc,:req,'招聘中',now(),now())"), {"pn":payload.get("position_name",""),"dept":payload.get("department",""),"hc":int(payload.get("headcount",1)),"req":payload.get("requirements","")})
    await session.commit(); return success_response(message="创建成功", status_code=201)


@router.put("/job-requirements/{req_id}", summary="更新岗位需求")
async def update_job_req(req_id: UUID, payload: dict, session: AsyncSession = Depends(get_db)):
    await session.execute(text("UPDATE hr.job_requirements SET position_name=COALESCE(:pn,position_name),department=COALESCE(:dept,department),headcount=COALESCE(:hc,headcount),requirements=COALESCE(:req,requirements),status=COALESCE(:st,status) WHERE id=:id AND is_deleted=false"), {"pn":payload.get("position_name"),"dept":payload.get("department"),"hc":payload.get("headcount"),"req":payload.get("requirements"),"st":payload.get("status"),"id":req_id})
    await session.commit(); return success_response(message="已更新")


@router.delete("/job-requirements/{req_id}", summary="删除岗位需求")
async def delete_job_req(req_id: UUID, session: AsyncSession = Depends(get_db)):
    await session.execute(text("UPDATE hr.job_requirements SET is_deleted=true WHERE id=:id"), {"id":req_id})
    await session.commit(); return success_response(message="已删除")
