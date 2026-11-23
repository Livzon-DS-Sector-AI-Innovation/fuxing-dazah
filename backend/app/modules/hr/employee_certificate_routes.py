"""员工电子证件资料库接口：台账 / 员工视图 / 上传换证 / 原件调阅 / 应交配置 / 调阅记录。"""

from datetime import date
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.hr import employee_certificate_service as cert_service
from app.modules.hr.deps import HrAccessContext, get_hr_scope

router = APIRouter(tags=["HR-员工证件"])


async def _read_upload(file: UploadFile) -> tuple[bytes, str | None]:
    data = await file.read()
    if not data:
        raise HTTPException(422, "证件扫描件不能为空")
    return data, file.filename


# ── 台账 / 缺件清单 ──


@router.get("/certificates", summary="证件台账（当前版本；按部门/类别/姓名检索）")
async def list_certificates(
    department: str | None = Query(None),
    category: str | None = Query(None),
    keyword: str | None = Query(None, description="姓名/工号模糊匹配"),
    current_only: bool = Query(True, description="false 时含历史版本"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    items, total = await cert_service.list_certificates(
        session, hr_scope,
        department=department, category=category, keyword=keyword,
        current_only=current_only, page=page, page_size=page_size,
    )
    return paginated_response(items, page, page_size, total)


@router.get("/certificates/missing", summary="缺件清单（应交未交，HR 催收视图）")
async def list_missing_certificates(
    department: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    rows = await cert_service.list_missing(session, hr_scope, department=department)
    return success_response(data=rows)


# ── 应交证件配置 ──


@router.get("/certificates/requirements", summary="应交证件清单配置")
async def list_requirements(session: AsyncSession = Depends(get_db)):
    return success_response(data=await cert_service.list_requirements(session))


class RequirementPayload(BaseModel):
    category: str = Field(min_length=1, max_length=32)
    applies_to: str = Field(min_length=1, max_length=16, description="all=全员 / key_position=仅重点岗位")


@router.post("/certificates/requirements", summary="新增应交证件配置")
async def add_requirement(
    payload: RequirementPayload,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await cert_service.add_requirement(session, payload.category, payload.applies_to)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(data=row, message="已新增")


@router.delete("/certificates/requirements/{requirement_id}", summary="删除应交证件配置")
async def delete_requirement(
    requirement_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        await cert_service.delete_requirement(session, requirement_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(message="已删除")


# ── 员工证件视图 / 上传换证 ──


@router.get("/employees/{employee_id}/certificates", summary="员工证件视图（六类分组+待补交标注）")
async def get_employee_certificates(
    employee_id: UUID,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    try:
        return success_response(data=await cert_service.get_employee_certificates(
            session, hr_scope, employee_id,
        ))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/employees/{employee_id}/certificates", summary="上传/换证（同类别自动升版本，旧版保留）")
async def upload_certificate(
    employee_id: UUID,
    file: UploadFile = File(..., description="证件扫描件（图片/PDF，≤20MB）"),
    category: str = Form(..., description="证件类别"),
    certificate_name: str | None = Form(None, max_length=128),
    certificate_no: str | None = Form(None, max_length=64),
    issue_date: date | None = Form(None, description="发证日期"),
    expiry_date: date | None = Form(None, description="有效期至（长期有效不填）"),
    is_permanent: bool = Form(False, description="长期有效"),
    remark: str | None = Form(None, max_length=512),
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    data, filename = await _read_upload(file)
    try:
        row = await cert_service.upload_certificate(
            session, hr_scope, employee_id,
            file_bytes=data, filename=filename, category=category,
            certificate_name=certificate_name, certificate_no=certificate_no,
            issue_date=issue_date, expiry_date=expiry_date,
            is_permanent=is_permanent, remark=remark,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(data=row, message="已归档（版本 v{v}）".format(v=row["version_no"]))


# ── 原件 / 更正 / 删除 ──


@router.get("/certificates/{certificate_id}/file", summary="证件原件（预览/下载，记审计）")
async def get_certificate_file(
    certificate_id: UUID,
    download: bool = Query(False, description="true=下载附件模式"),
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    try:
        data, headers = await cert_service.get_certificate_file(
            session, hr_scope, certificate_id, download=download,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(content=data, headers=headers)


class CertificateUpdatePayload(BaseModel):
    certificate_name: str | None = Field(None, max_length=128)
    certificate_no: str | None = Field(None, max_length=64)
    issue_date: date | None = None
    expiry_date: date | None = None
    is_permanent: bool | None = None
    remark: str | None = Field(None, max_length=512)


@router.put("/certificates/{certificate_id}", summary="更正证件登记要素（发证日期/有效期等）")
async def update_certificate(
    certificate_id: UUID,
    payload: CertificateUpdatePayload,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    changes = payload.model_dump(exclude_unset=True)
    try:
        row = await cert_service.update_certificate(session, hr_scope, certificate_id, changes=changes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(data=row, message="已更正")


@router.delete("/certificates/{certificate_id}", summary="删除证件（软删；当前版本删除后最新历史版本自动顶替）")
async def delete_certificate(
    certificate_id: UUID,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    try:
        await cert_service.delete_certificate(session, hr_scope, certificate_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(message="已删除")


# ── 调阅记录 ──


@router.get("/certificates/access-logs", summary="证件调阅/操作记录（审计）")
async def list_access_logs(
    employee_id: UUID | None = Query(None, description="按员工过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    items, total = await cert_service.list_access_logs(
        session, hr_scope, employee_id=employee_id, page=page, page_size=page_size,
    )
    return paginated_response(items, page, page_size, total)
