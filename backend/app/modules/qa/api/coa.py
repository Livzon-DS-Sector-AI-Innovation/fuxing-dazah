"""QA COA HTTP API：产品/客户标准配置、docx 导入预览、出具登记、矩阵透视、
模板标注与回填、生成留档与验证。

挂在 QA 模块路由下（``/api/v1/qa/coa``）。读取放行模块全域读码
``qa:all:read``、COA 专用读码或 coa 写码（写权限隐含读）。
"""

from __future__ import annotations

import asyncio
import uuid
from html import escape
from string import Template
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.response import paginated_response, success_response
from app.modules.qa import file_service
from app.modules.qa.api._deps import coa_issue, coa_manage, coa_read
from app.modules.qa.schemas.coa import (
    CoaProductCreate,
    CoaProductFieldsReplace,
    CoaProductUpdate,
    CoaReportCreate,
    CoaReportUpdate,
    CoaStandardCreate,
    CoaStandardFieldsReplace,
    CoaStandardItemsReplace,
    CoaStandardUpdate,
    CoaTemplateBindingIn,
)
from app.modules.qa.service import coa as service
from app.platform.identity.models import User

router = APIRouter()


# ───────────────────────── 产品 ─────────────────────────


@router.get("/coa/products", summary="COA 产品列表")
async def list_products(
    user: User = Depends(coa_read),
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(default=False, description="只看启用产品"),
) -> Any:
    return success_response(
        data=await service.list_products(db, active_only=active_only)
    )


@router.post("/coa/products", summary="新增 COA 产品", status_code=201)
async def create_product(
    payload: CoaProductCreate,
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.create_product(db, payload, user), status_code=201
    )


@router.patch("/coa/products/{product_id}", summary="编辑 COA 产品")
async def update_product(
    payload: CoaProductUpdate,
    product_id: uuid.UUID,
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.update_product(db, product_id, payload, user)
    )


@router.get(
    "/coa/products/{product_id}/fields", summary="产品批次信息字段配置列表"
)
async def list_product_fields(
    product_id: uuid.UUID,
    user: User = Depends(coa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.list_product_fields(db, product_id)
    )


@router.put(
    "/coa/products/{product_id}/fields",
    summary="产品批次信息字段配置全量替换",
)
async def replace_product_fields(
    payload: CoaProductFieldsReplace,
    product_id: uuid.UUID,
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.replace_product_fields(db, product_id, payload, user)
    )


# ───────────────────────── 客户标准 ─────────────────────────


@router.get("/coa/standards", summary="客户标准列表")
async def list_standards(
    user: User = Depends(coa_read),
    db: AsyncSession = Depends(get_db),
    product_id: uuid.UUID | None = Query(default=None, description="按产品过滤"),
    active_only: bool = Query(default=False, description="只看启用标准"),
) -> Any:
    return success_response(
        data=await service.list_standards(
            db, product_id=product_id, active_only=active_only
        )
    )


@router.get("/coa/standards/{standard_id}", summary="客户标准详情（含项目）")
async def get_standard(
    standard_id: uuid.UUID,
    user: User = Depends(coa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(data=await service.get_standard_detail(db, standard_id))


@router.post("/coa/standards", summary="新建客户标准（含首批项目）", status_code=201)
async def create_standard(
    payload: CoaStandardCreate,
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.create_standard(db, payload, user), status_code=201
    )


@router.patch("/coa/standards/{standard_id}", summary="编辑客户标准头")
async def update_standard(
    payload: CoaStandardUpdate,
    standard_id: uuid.UUID,
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.update_standard(db, standard_id, payload, user)
    )


@router.delete("/coa/standards/{standard_id}", summary="删除客户标准")
async def delete_standard(
    standard_id: uuid.UUID,
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.delete_standard(db, standard_id, user)
    return success_response(data=None)


@router.put(
    "/coa/standards/{standard_id}/fields",
    summary="标准批次信息字段覆盖全量替换（与产品默认解耦）",
)
async def replace_standard_fields(
    payload: CoaStandardFieldsReplace,
    standard_id: uuid.UUID,
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.replace_standard_fields(db, standard_id, payload, user)
    )


@router.delete(
    "/coa/standards/{standard_id}/fields",
    summary="恢复产品默认批次信息字段（删标准覆盖）",
)
async def restore_standard_fields(
    standard_id: uuid.UUID,
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(data=await service.restore_standard_fields(db, standard_id))


@router.put("/coa/standards/{standard_id}/items", summary="标准项目全量替换")
async def replace_items(
    payload: CoaStandardItemsReplace,
    standard_id: uuid.UUID,
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.replace_items(db, standard_id, payload, user)
    )


@router.post(
    "/coa/standards/import-preview",
    summary="docx 导入预览：客户标准草稿（不落库）",
)
async def import_standard_preview(
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(description="COA docx 报告文件"),
) -> Any:
    data = await file.read()
    return success_response(
        data=await service.import_standard_preview(
            db, data, filename=file.filename or "coa.docx"
        )
    )


# ───────────────────────── 模板标注 ─────────────────────────


@router.put(
    "/coa/standards/{standard_id}/template",
    summary="上传/替换 COA 模板 docx（换文件后原标注作废）",
)
async def upload_template(
    standard_id: uuid.UUID,
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(description="COA 模板 docx"),
) -> Any:
    data = await file.read()
    return success_response(
        data=await service.upload_template(
            db,
            standard_id,
            data,
            filename=file.filename,
            content_type=file.content_type,
            user=user,
        )
    )


@router.get(
    "/coa/standards/{standard_id}/template",
    summary="COA 模板状态、网格与已确认的标注",
)
async def get_template(
    standard_id: uuid.UUID,
    user: User = Depends(coa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(data=await service.get_template(db, standard_id))


@router.post(
    "/coa/standards/{standard_id}/template/annotate",
    summary="AI 标注模板数据位（提案，不落库；保存前须人工确认）",
)
async def annotate_template(
    standard_id: uuid.UUID,
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(data=await service.annotate_template(db, standard_id))


@router.put(
    "/coa/standards/{standard_id}/template/binding",
    summary="保存人工确认后的模板标注",
)
async def save_template_binding(
    payload: CoaTemplateBindingIn,
    standard_id: uuid.UUID,
    user: User = Depends(coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.save_template_binding(db, standard_id, payload, user)
    )


# ───────────────────────── 出具登记 ─────────────────────────


@router.get("/coa/reports", summary="出具登记列表（按产品）")
async def list_reports(
    user: User = Depends(coa_read),
    db: AsyncSession = Depends(get_db),
    product_id: uuid.UUID = Query(description="产品 id"),
) -> Any:
    return success_response(data=await service.list_reports(db, product_id))


@router.get("/coa/reports/matrix", summary="产品维度矩阵（所有 COA × 所有项目）")
async def report_matrix(
    user: User = Depends(coa_read),
    db: AsyncSession = Depends(get_db),
    product_id: uuid.UUID = Query(description="产品 id"),
    standard_id: list[uuid.UUID] | None = Query(
        default=None, description="按标准筛列（可多个）"
    ),
) -> Any:
    return success_response(
        data=await service.matrix(db, product_id, standard_ids=standard_id)
    )


@router.get("/coa/reports/{report_id}", summary="COA 报告详情（含结果值）")
async def get_report(
    report_id: uuid.UUID,
    user: User = Depends(coa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(data=await service.get_report_detail(db, report_id))


@router.post(
    "/coa/reports",
    summary="出具登记（手工/导入统一落库；业务键=产品+模板+批号，batch_data=模板动态批次字段）",
    status_code=201,
)
async def create_report(
    payload: CoaReportCreate,
    user: User = Depends(coa_issue),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.create_report(db, payload, user), status_code=201
    )


@router.patch("/coa/reports/{report_id}", summary="编辑 COA 报告")
async def update_report(
    payload: CoaReportUpdate,
    report_id: uuid.UUID,
    user: User = Depends(coa_issue),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.update_report(db, report_id, payload, user)
    )


@router.delete("/coa/reports/{report_id}", summary="作废 COA 报告")
async def delete_report(
    report_id: uuid.UUID,
    user: User = Depends(coa_issue),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.delete_report(db, report_id, user)
    return success_response(data=None)


@router.post(
    "/coa/reports/import-preview",
    summary="docx 导入预览：标准匹配 + 项目对齐 + 值预填（不落库）",
)
async def import_report_preview(
    user: User = Depends(coa_issue),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(description="COA docx 报告文件"),
    standard_id: uuid.UUID | None = Query(
        default=None, description="显式指定标准（缺省按报告编号自动匹配）"
    ),
) -> Any:
    data = await file.read()
    return success_response(
        data=await service.import_report_preview(
            db, data, standard_id=standard_id, filename=file.filename or "coa.docx"
        )
    )


@router.post(
    "/coa/reports/{report_id}/render",
    summary="按模板标注生成 COA docx（dry_run=true 只预检不生成）；出文件即留档",
)
async def render_report(
    report_id: uuid.UUID,
    user: User = Depends(coa_issue),
    db: AsyncSession = Depends(get_db),
    dry_run: bool = Query(default=False, description="true=只返回预检结果，不生成文件"),
) -> Any:
    if dry_run:
        return success_response(data=await service.check_report_render(db, report_id))
    data, filename, _check = await service.render_report_docx(db, report_id, user)
    return StreamingResponse(
        iter([data]),
        media_type=service.COA_DOCX_MIME,
        headers={
            "Content-Disposition": file_service.content_disposition("attachment", filename)
        },
    )


@router.get(
    "/coa/reports/{report_id}/print",
    summary="COA 快速打印：生成 PDF 供浏览器直接打开打印（转换结果有缓存；出文件即留档）",
)
async def print_report(
    report_id: uuid.UUID,
    user: User = Depends(coa_issue),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        data, filename = await service.render_report_pdf(db, report_id, user)
    except AppException as exc:
        # 这个地址是在新标签页里直接打开的：给人一页看得懂的提示，而不是一段 JSON
        return _print_error_page(exc)
    return Response(
        content=data,
        media_type=service.COA_PDF_MIME,
        headers={
            # 同一个地址在数据改过之后必须拿到新的：不让浏览器缓存
            "Cache-Control": "no-store",
            "Content-Disposition": file_service.content_disposition("inline", filename),
            "X-Content-Type-Options": "nosniff",
        },
    )


# 新标签页里直接打开的地址，出错时给一页看得懂的提示。不引任何外部资源，内网离线也能显示。
_PRINT_ERROR_PAGE = Template(
    """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>COA 打印版没有生成</title>
<style>
  body { margin: 0; background: #f5f6f8; color: #1f2329;
         font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }
  main { max-width: 560px; margin: 12vh auto; padding: 32px 36px; background: #fff;
         border-radius: 8px; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08); }
  h1 { margin: 0 0 12px; font-size: 18px; }
  p { margin: 0; line-height: 1.7; color: #4a4f55; }
  ul { margin: 10px 0 0; padding-left: 20px; line-height: 1.8; color: #646a73; }
  .hint { margin-top: 18px; font-size: 13px; color: #8f959e; }
</style>
</head>
<body>
<main>
  <h1>COA 打印版没有生成</h1>
  <p>${message}</p>
  ${details}
  <p class="hint">请回到出具登记页处理后重试，或改用「下载 COA」用 Word / WPS 打开后打印。本页可以直接关闭。</p>
</main>
</body>
</html>
"""
)


def _print_error_page(exc: AppException) -> HTMLResponse:
    lines = service.print_failure_lines(exc)
    listing = "".join(f"<li>{escape(line)}</li>" for line in lines)
    details = f"<ul>{listing}</ul>" if lines else ""
    page = _PRINT_ERROR_PAGE.substitute(message=escape(str(exc.message)), details=details)
    return HTMLResponse(
        status_code=exc.status_code,
        content=page,
        headers={"Cache-Control": "no-store"},
    )


# ───────────────────────── 生成留档与验证 ─────────────────────────


@router.get("/coa/renders", summary="COA 生成留档列表（每次生成一条，新的在前）")
async def list_renders(
    user: User = Depends(coa_read),
    db: AsyncSession = Depends(get_db),
    product_id: uuid.UUID | None = Query(default=None, description="按产品筛"),
    report_id: uuid.UUID | None = Query(default=None, description="按报告筛"),
    batch_no: str | None = Query(default=None, description="批号模糊匹配"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Any:
    items, total = await service.list_renders(
        db,
        product_id=product_id,
        report_id=report_id,
        batch_no=batch_no,
        page=page,
        page_size=page_size,
    )
    return paginated_response(items, page, page_size, total)


@router.get("/coa/renders/{record_id}/file", summary="下载留档的系统原件")
async def download_render_file(
    record_id: uuid.UUID,
    user: User = Depends(coa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    record = await service.get_render_record_or_404(db, record_id)
    data = await asyncio.to_thread(service.read_render_file, record)
    if data is None:
        raise AppException(status_code=409, message="留档原件已不在存储里")
    return StreamingResponse(
        iter([data]),
        media_type=service.COA_DOCX_MIME,
        headers={
            "Content-Disposition": file_service.content_disposition(
                "attachment", record.filename
            )
        },
    )


@router.post("/coa/renders/verify", summary="COA 验证：上传一份 docx，比对系统留档")
async def verify_render(
    user: User = Depends(coa_read),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(description="待验证的 COA docx"),
    report_id: uuid.UUID | None = Form(
        default=None, description="指定报告时只跟它的留档比；不指定按文件里的批号找"
    ),
) -> Any:
    data = await file.read()
    return success_response(
        data=await service.verify_docx(
            db, data, filename=file.filename, report_id=report_id
        )
    )
