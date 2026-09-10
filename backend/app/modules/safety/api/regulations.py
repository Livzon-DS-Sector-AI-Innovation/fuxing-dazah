"""Safety API — regulations endpoints."""

import os
import uuid
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.core.storage import is_enabled as minio_enabled
from app.core.storage import upload_object
from app.modules.safety.schemas import (
    OperationRegulationCreate,
    OperationRegulationResponse,
    OperationRegulationUpdate,
    RegulationReviseRequest,
    RegulationRevisionCreate,
    RegulationRevisionResponse,
    RegulationRevisionUpdate,
    SopContentUpdate,
    SopGenerateResponse,
)
from app.modules.safety.service import (
    RegulationService,
    SopGeneratorService,
)

regulations_router = APIRouter()


@regulations_router.get("/regulations", response_model=ApiResponse, summary="获取安全操作规程列表")
async def get_regulations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    position: str | None = None,
    keyword: str | None = None,
    status: str | None = Query(None, description="操规状态，逗号分隔多值: draft,generated,reviewed,exported"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全操作规程列表，支持按岗位、关键词和状态筛选"""
    service = RegulationService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_regulations(skip, page_size, position, keyword, status)
    return ApiResponse(
        data=[OperationRegulationResponse.model_validate(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@regulations_router.get(
    "/regulations/{regulation_id}",
    response_model=ApiResponse,
    summary="获取安全操作规程详情",
)
async def get_regulation(
    regulation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全操作规程详情，包含修订记录"""
    service = RegulationService(db)
    item = await service.get_regulation(regulation_id)
    if not item:
        return ApiResponse(code=404, message="操规不存在")
    return ApiResponse(data=OperationRegulationResponse.model_validate(item))


@regulations_router.post("/regulations", response_model=ApiResponse, summary="创建安全操作规程")
async def create_regulation(
    data: OperationRegulationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建安全操作规程"""
    service = RegulationService(db)
    item = await service.create_regulation(data)
    await db.commit()
    return ApiResponse(data=OperationRegulationResponse.model_validate(item))


@regulations_router.put(
    "/regulations/{regulation_id}",
    response_model=ApiResponse,
    summary="更新安全操作规程",
)
async def update_regulation(
    regulation_id: uuid.UUID,
    data: OperationRegulationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新安全操作规程"""
    service = RegulationService(db)
    item = await service.update_regulation(regulation_id, data)
    if not item:
        return ApiResponse(code=404, message="操规不存在")
    await db.commit()
    return ApiResponse(data=OperationRegulationResponse.model_validate(item))


@regulations_router.delete(
    "/regulations/{regulation_id}",
    response_model=ApiResponse,
    summary="删除安全操作规程",
)
async def delete_regulation(
    regulation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除安全操作规程"""
    service = RegulationService(db)
    result = await service.delete_regulation(regulation_id)
    if not result:
        return ApiResponse(code=404, message="操规不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@regulations_router.post(
    "/regulations/{regulation_id}/upload",
    response_model=ApiResponse,
    summary="上传操规文档",
)
async def upload_regulation_document(
    regulation_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """上传操规文档并更新操规记录"""

    file_ext = os.path.splitext(file.filename or ".md")[1]
    safe_name = f"{regulation_id}_{int(datetime.now().timestamp())}{file_ext}"
    content = await file.read()

    if minio_enabled():
        object_key = f"regulation/{safe_name}"
        upload_object("safety", object_key, content, len(content), file.content_type or "application/octet-stream")
        stored_path = object_key
    else:
        upload_dir = os.path.join("uploads", "safety", "regulations")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, safe_name)
        with open(file_path, "wb") as f:
            f.write(content)
        stored_path = file_path

    service = RegulationService(db)
    item = await service.upload_regulation_document(
        regulation_id, file.filename or "unknown", stored_path
    )
    if not item:
        return ApiResponse(code=404, message="操规不存在")
    await db.commit()
    return ApiResponse(data=OperationRegulationResponse.model_validate(item))


# ==================== 操规修订记录 Routes ====================


@regulations_router.get("/revisions", response_model=ApiResponse, summary="获取修订记录列表")
async def get_revisions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    regulation_id: uuid.UUID | None = None,
    revision_type: str | None = None,
    review_opinion: str | None = None,
    revision_scope: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取修订记录列表，支持多条件筛选"""
    service = RegulationService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_revisions(
        skip, page_size, regulation_id, revision_type, review_opinion, revision_scope
    )
    return ApiResponse(
        data=[RegulationRevisionResponse.model_validate(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@regulations_router.get(
    "/revisions/{revision_id}",
    response_model=ApiResponse,
    summary="获取修订记录详情",
)
async def get_revision(
    revision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取修订记录详情，包含关联的危险源辨识记录"""
    service = RegulationService(db)
    item = await service.get_revision(revision_id)
    if not item:
        return ApiResponse(code=404, message="修订记录不存在")
    return ApiResponse(data=RegulationRevisionResponse.model_validate(item))


@regulations_router.post("/revisions", response_model=ApiResponse, summary="创建修订记录")
async def create_revision(
    data: RegulationRevisionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建修订记录，自动从操规表获取旧文档链接"""
    service = RegulationService(db)
    item = await service.create_revision(data)
    if not item:
        return ApiResponse(code=404, message="关联的操规不存在")
    await db.commit()
    return ApiResponse(data=RegulationRevisionResponse.model_validate(item))


@regulations_router.put(
    "/revisions/{revision_id}",
    response_model=ApiResponse,
    summary="更新修订记录",
)
async def update_revision(
    revision_id: uuid.UUID,
    data: RegulationRevisionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新修订记录"""
    service = RegulationService(db)
    item = await service.update_revision(revision_id, data)
    if not item:
        return ApiResponse(code=404, message="修订记录不存在")
    await db.commit()
    return ApiResponse(data=RegulationRevisionResponse.model_validate(item))


@regulations_router.delete(
    "/revisions/{revision_id}",
    response_model=ApiResponse,
    summary="删除修订记录",
)
async def delete_revision(
    revision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除修订记录"""
    service = RegulationService(db)
    result = await service.delete_revision(revision_id)
    if not result:
        return ApiResponse(code=404, message="修订记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ── 人工修订 ──


@regulations_router.post(
    "/revisions/{revision_id}/manual-complete",
    response_model=ApiResponse,
    summary="完成人工修订",
)
async def manual_revision_complete(
    revision_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """上传修订后的文档，完成人工修订流程：
    1. 保存新文档（MinIO 或本地）
    2. 更新修订记录（新文档链接 + 审核通过）
    3. 同步更新操规表文档链接
    """

    file_ext = os.path.splitext(file.filename or ".md")[1]
    safe_name = f"revision_{revision_id}_{int(datetime.now().timestamp())}{file_ext}"
    content = await file.read()

    if minio_enabled():
        object_key = f"regulation/{safe_name}"
        upload_object("safety", object_key, content, len(content), file.content_type or "application/octet-stream")
        stored_path = object_key
    else:
        upload_dir = os.path.join("uploads", "safety", "regulations")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, safe_name)
        with open(file_path, "wb") as f:
            f.write(content)
        stored_path = file_path

    service = RegulationService(db)
    item = await service.manual_revision_complete(
        revision_id, stored_path, file.filename
    )
    if not item:
        return ApiResponse(code=400, message="无法完成修订，当前状态不允许或修订类型不是人工修订")
    await db.commit()
    return ApiResponse(data=RegulationRevisionResponse.model_validate(item))


# ── AI 修订 ──


@regulations_router.post(
    "/revisions/{revision_id}/ai-generate",
    response_model=ApiResponse,
    summary="AI生成修订版本",
)
async def ai_revision_generate(
    revision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """AI根据修订意见生成修订后的操规文档（返回供用户确认，不持久化）"""
    service = RegulationService(db)
    result = await service.ai_revision_generate(revision_id)
    if not result:
        return ApiResponse(code=400, message="无法生成，修订类型不是AI修订或修订记录不存在")
    return ApiResponse(data=result)


@regulations_router.post(
    "/revisions/{revision_id}/ai-confirm",
    response_model=ApiResponse,
    summary="确认AI修订版本",
)
async def ai_revision_confirm(
    revision_id: uuid.UUID,
    generated_content: str = Query(..., description="AI生成的修订后完整内容"),
    document_name: str | None = Query(None, description="文档名称（可选）"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """用户确认AI生成的修订内容后，保存文档并更新所有关联记录"""
    service = RegulationService(db)
    item = await service.ai_revision_confirm(
        revision_id, generated_content, document_name
    )
    if not item:
        return ApiResponse(code=400, message="无法确认，修订类型不是AI修订或修订记录不存在")
    await db.commit()
    return ApiResponse(data=RegulationRevisionResponse.model_validate(item))


# ── 修订范围识别 ──


@regulations_router.post(
    "/revisions/{revision_id}/identify-scope",
    response_model=ApiResponse,
    summary="AI识别修订范围",
)
async def identify_revision_scope(
    revision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """AI分析修订意见，识别修订范围（工艺/安全要求）。
    若识别出工艺变更，自动触发危险源辨识修订流程。
    """
    service = RegulationService(db)
    item = await service.identify_revision_scope(revision_id)
    if not item:
        return ApiResponse(code=404, message="修订记录不存在")
    await db.commit()
    return ApiResponse(data=RegulationRevisionResponse.model_validate(item))


# ═══════════════════════════════════════════════════════════════════
# SOP 标准化生成（调用 safety-sop-generator 插件）
# ═══════════════════════════════════════════════════════════════════


@regulations_router.post(
    "/regulations/generate",
    response_model=ApiResponse,
    summary="上传旧版操规并生成标准化版本",
)
async def generate_sop(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """上传旧版操规初稿（.docx），自动运行三层 pipeline 生成 9 章标准化操规。

    返回提取的元信息（产品/岗位/部门/编号）和完整 Markdown 内容，
    前端进入编辑面板供用户审阅修改。
    """
    if not file.filename or not file.filename.endswith(".docx"):
        return ApiResponse(code=400, message="仅支持 .docx 格式的操规初稿")

    service = SopGeneratorService(db)
    result = await service.generate_from_draft(file)
    await db.commit()

    # 自动 AI 审核：必须在本请求 commit 之后触发，否则后台独立 session
    # 在 READ COMMITTED 下看不到刚插入的记录（D6 竞态）。process 类型在
    # 生成后由后台任务执行 AI 审核（channel=system），不阻塞响应。
    if result.get("ai_review_auto"):
        import asyncio

        asyncio.create_task(
            service.run_ai_review(
                uuid.UUID(str(result["regulation_id"])), channel="system"
            )
        )

    return ApiResponse(data=SopGenerateResponse(**result).model_dump())


@regulations_router.get(
    "/regulations/{regulation_id}/content",
    response_model=ApiResponse,
    summary="获取操规标准化内容",
)
async def get_sop_content(
    regulation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取操规的标准化 Markdown 内容，供编辑器加载。"""
    service = SopGeneratorService(db)
    result = await service.get_content(regulation_id)
    if not result:
        return ApiResponse(code=404, message="操规不存在")

    return ApiResponse(data=result)


@regulations_router.put(
    "/regulations/{regulation_id}/content",
    response_model=ApiResponse,
    summary="保存编辑后的操规内容",
)
async def update_sop_content(
    regulation_id: uuid.UUID,
    data: SopContentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """保存用户编辑后的标准化 Markdown 内容，可选更新状态。"""
    service = SopGeneratorService(db)
    item = await service.update_content(
        regulation_id, data.content, data.status
    )
    if not item:
        return ApiResponse(code=404, message="操规不存在")
    await db.commit()

    return ApiResponse(
        data={
            "regulation_id": str(regulation_id),
            "status": item.status if hasattr(item, "status") else "reviewed",
        },
        message="内容保存成功",
    )


@regulations_router.post(
    "/regulations/{regulation_id}/revise",
    response_model=ApiResponse,
    summary="在线修订操规",
)
async def revise_regulation(
    regulation_id: uuid.UUID,
    data: "RegulationReviseRequest",
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """保存修订后的操规内容，并自动生成一条修订记录。

    与 /content 端点不同，本端点会额外：
    - 自动生成修订编号 (REV-{操规编号}-{时间戳})
    - 创建 RegulationRevision 记录（revision_type=manual, review_opinion=approved）
    - 记录审计日志
    """
    service = RegulationService(db)
    result = await service.revise_regulation(
        regulation_id,
        content=data.content,
        revision_opinion=data.revision_opinion,
        reviser_name=data.reviser_name,
    )
    if not result:
        return ApiResponse(code=404, message="操规不存在")
    await db.commit()
    return ApiResponse(data=result, message="修订保存成功")


@regulations_router.post(
    "/regulations/{regulation_id}/export",
    summary="导出标准化操规（PDF / WORD）",
)
async def export_sop_pdf(
    regulation_id: uuid.UUID,
    format: str = Query("pdf", description="导出格式: pdf 或 docx"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """将存储的标准化 Markdown 渲染为 PDF 或 WORD（.docx），返回文件下载。"""
    from io import BytesIO

    from fastapi.responses import StreamingResponse

    service = SopGeneratorService(db)
    exported = await service.export(regulation_id, format)

    if not exported:
        return ApiResponse(code=400, message="导出失败：操规不存在或内容为空")

    file_path, media_type = exported
    is_docx = media_type.endswith("wordprocessingml.document")
    ext = ".docx" if is_docx else ".pdf"

    # 统一经 service.read_exported_file 读取（MinIO object key 或本地路径）
    data = await service.read_exported_file(file_path)
    if data is None:
        return ApiResponse(code=400, message="导出失败：文件不存在")

    await db.commit()

    # Generate a friendly download filename (RFC 5987 encoded for non-ASCII chars)
    filename = f"标准化操规_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
    encoded_filename = quote(filename)

    return StreamingResponse(
        BytesIO(data),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        },
    )


@regulations_router.post(
    "/regulations/{regulation_id}/ai-review",
    summary="重新执行操规 AI 审核",
)
async def rerun_regulation_ai_review(
    regulation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动重试 AI 审核（对照源文档重新审核当前内容）。

    已有进行中审核（reviewing）时幂等跳过；
    触发后立即返回，审核在后台独立 session 执行。
    """
    import asyncio

    service = SopGeneratorService(db)
    reg = await service.repo.get_regulation_by_id(regulation_id)
    if not reg:
        return ApiResponse(code=404, message="操规不存在")
    if reg.ai_review_status == "reviewing":
        return ApiResponse(code=409, message="AI 审核进行中，请勿重复触发")
    if not reg.content:
        return ApiResponse(code=400, message="操规内容为空，无法审核")

    # 重置为待审（同一请求 session 提交），随后后台任务接管状态流转
    await service.repo.update_regulation(
        regulation_id,
        {"ai_review_status": "pending", "ai_review_note": None},
    )
    await db.commit()
    asyncio.create_task(service.run_ai_review(regulation_id, channel="web"))
    return ApiResponse(
        data={"regulation_id": str(regulation_id), "ai_review_status": "pending"},
        message="已触发 AI 审核",
    )
