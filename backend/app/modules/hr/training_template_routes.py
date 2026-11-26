"""培训导出模板管理路由（用户自维护 docx 模板）。

权限：全部走 hr:training:template（deps._HR_PATH_PERMISSIONS 同步登记）；
上传/激活/恢复默认额外要求全量数据范围（模板影响全公司导出格式）。
审计：上传/激活/恢复默认写平台审计（hr.training_template.*）。
"""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException, ForbiddenException
from app.core.file_storage import content_disposition
from app.core.response import success_response
from app.modules.hr import training_template_store as store
from app.modules.hr.deps import HrAccessContext, require_hr_access
from app.platform.audit.service import record_audit_log

router = APIRouter(tags=["HR-培训导出模板"])

RESOURCE_TYPE = "hr_training_export_template"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _ensure_can_manage(ctx: HrAccessContext) -> None:
    """模板变更影响全公司导出格式：仅限 HR 全量数据范围。"""
    if not ctx.is_unrestricted:
        raise ForbiddenException("数据范围限制：培训导出模板维护仅限 HR（全量数据范围）")


async def _template_list(db: AsyncSession) -> list[dict]:
    """注册表全量 + 各模板当前自定义版概要。"""
    from sqlalchemy import func, select

    from app.modules.hr.models import TrainingExportTemplateVersion
    from app.modules.hr.training_template_registry import TEMPLATES

    rows = (
        await db.execute(
            select(TrainingExportTemplateVersion).where(
                TrainingExportTemplateVersion.is_deleted.is_(False),
            ).order_by(TrainingExportTemplateVersion.template_key, TrainingExportTemplateVersion.version_no.desc())
        )
    ).scalars().all()
    counts: dict[str, int] = {
        key: count for key, count in (
            await db.execute(
                select(TrainingExportTemplateVersion.template_key, func.count())
                .where(TrainingExportTemplateVersion.is_deleted.is_(False))
                .group_by(TrainingExportTemplateVersion.template_key)
            )
        ).all()
    }
    currents = {row.template_key: row for row in rows if row.is_current}
    names = await store.resolve_uploader_names(db, list(currents.values()))

    result = []
    for tdef in TEMPLATES:
        current = currents.get(tdef.key)
        uploader = None
        if current is not None:
            uploader = names.get(current.created_by) or (str(current.created_by) if current.created_by else None)
        result.append(store.template_def_dict(tdef, current, counts.get(tdef.key, 0), uploader))
    return result


@router.get("/training-export-templates", summary="培训导出模板清单（注册表+当前自定义版）")
async def list_training_templates(
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:training:template")),
) -> Response:
    return success_response(data=await _template_list(db))


@router.post("/training-export-templates/inspect", summary="自动识别上传模板中的占位符（上传向导预检）")
async def inspect_training_template(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:training:template")),
) -> Response:
    """扫描上传的 docx 全文，返回其中实际出现的 {占位符} 清单（去重、按出现顺序）。

    只做识别，不做校验——最终上传仍按目标导出的必填清单严格把关。
    """
    data = await file.read()
    if not data:
        raise AppException(status_code=422, message="模板文件不能为空")
    store.validate_template_document(file.filename, data)  # 仅校验可解析，不入库
    return success_response(data={"markers": store.extract_docx_markers(data)})


@router.get("/training-export-templates/{key}/versions", summary="模板版本历史")
async def list_template_versions(
    key: str,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:training:template")),
) -> Response:
    rows = await store.list_versions(db, key)
    names = await store.resolve_uploader_names(db, rows)
    return success_response(data=[
        store.template_version_dict(row, names.get(row.created_by) or (str(row.created_by) if row.created_by else None))
        for row in rows
    ])


@router.post("/training-export-templates/{key}/upload", summary="上传模板新版本")
async def upload_training_template(
    key: str,
    file: UploadFile = File(...),
    remark: str = Form("", description="备注（如修改内容）"),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:training:template")),
) -> Response:
    _ensure_can_manage(ctx)
    data = await file.read()
    if not data:
        raise AppException(status_code=422, message="模板文件不能为空")
    version = await store.upload_training_template(
        db, key, file.filename, data, user=ctx.user, remark=remark,
    )
    await record_audit_log(
        db, action="hr.training_template.upload", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=version.id,
        new_value={"template_key": key, "version_no": version.version_no, "file_name": version.file_name},
    )
    return success_response(
        data=store.template_version_dict(version, ctx.user.name if ctx.user else None),
        message=f"已上传模板 v{version.version_no}",
    )


@router.get("/training-export-templates/{key}/file", summary="下载模板文件（当前版/历史版/官方默认）")
async def download_training_template(
    key: str,
    version_id: UUID | None = Query(None, description="指定历史版本；缺省=当前自定义版"),
    default: bool = Query(False, description="true=下载仓库默认模板（推荐先下载它再修改）"),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:training:template")),
) -> Response:
    if default:
        tdef = store.get_template_def(key)
        data = store.default_template_bytes(key)
        return Response(
            content=data,
            media_type=_DOCX_MIME,
            headers={"Content-Disposition": content_disposition("attachment", tdef.default_file)},
        )
    if version_id is not None:
        row = await store.get_version(db, key, version_id)
    else:
        row = await store.get_current_version(db, key)
        if row is None:
            tdef = store.get_template_def(key)
            data = store.default_template_bytes(key)
            return Response(
                content=data,
                media_type=_DOCX_MIME,
                headers={"Content-Disposition": content_disposition("attachment", tdef.default_file)},
            )
    data = await store.read_version_bytes(row)
    return Response(
        content=data,
        media_type=_DOCX_MIME,
        headers={"Content-Disposition": content_disposition("attachment", row.file_name)},
    )


@router.post("/training-export-templates/{key}/versions/{version_id}/activate", summary="激活历史版本（回滚）")
async def activate_template_version(
    key: str,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:training:template")),
) -> Response:
    _ensure_can_manage(ctx)
    row = await store.activate_version(db, key, version_id, user=ctx.user)
    await record_audit_log(
        db, action="hr.training_template.activate", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=row.id,
        new_value={"template_key": key, "version_no": row.version_no},
    )
    return success_response(
        data=store.template_version_dict(row, ctx.user.name if ctx.user else None),
        message=f"已切换到 v{row.version_no}",
    )


@router.post("/training-export-templates/{key}/restore-default", summary="恢复官方默认模板")
async def restore_template_default(
    key: str,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:training:template")),
) -> Response:
    _ensure_can_manage(ctx)
    await store.restore_default(db, key)
    await record_audit_log(
        db, action="hr.training_template.restore_default", user=ctx.user,
        resource_type=RESOURCE_TYPE,
        extra={"template_key": key},
    )
    return success_response(message="已恢复官方默认模板")
