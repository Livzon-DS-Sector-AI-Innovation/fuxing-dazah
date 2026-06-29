"""Safety API — ai_workflow endpoints."""

import os
import uuid

from fastapi import APIRouter, Depends, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    AIWorkflowConfigCreate,
    AIWorkflowConfigResponse,
    AIWorkflowConfigUpdate,
    KnowledgeAttachmentRequest,
    ReferenceAttachmentResponse,
)
from app.modules.safety.service import (
    AttachmentService,
    ConfigService,
)

ai_workflow_router = APIRouter()


@ai_workflow_router.get(
    "/ai-workflow-configs",
    response_model=ApiResponse,
    summary="获取 AI 工作流配置列表",
)
async def get_ai_workflow_configs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=500, description="每页条数"),
    module_code: str | None = Query(None, description="模块代码"),
    is_enabled: bool | None = Query(None, description="是否启用"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取 AI 工作流配置列表，可按模块代码过滤"""
    service = ConfigService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_ai_workflow_configs(
        skip, page_size, module_code, is_enabled
    )
    return ApiResponse(
        data=[AIWorkflowConfigResponse.model_validate(item) for item in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@ai_workflow_router.get(
    "/ai-workflow-configs/{config_id}",
    response_model=ApiResponse,
    summary="获取 AI 工作流配置详情",
)
async def get_ai_workflow_config(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取单个 AI 工作流配置详情"""
    service = ConfigService(db)
    item = await service.get_ai_workflow_config(config_id)
    if not item:
        return ApiResponse(code=404, message="配置不存在")
    return ApiResponse(data=AIWorkflowConfigResponse.model_validate(item))


@ai_workflow_router.post(
    "/ai-workflow-configs",
    response_model=ApiResponse,
    summary="创建 AI 工作流配置",
)
async def create_ai_workflow_config(
    data: AIWorkflowConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建新的 AI 工作流配置"""
    service = ConfigService(db)
    item = await service.create_ai_workflow_config(data)
    await db.commit()
    return ApiResponse(data=AIWorkflowConfigResponse.model_validate(item))


@ai_workflow_router.put(
    "/ai-workflow-configs/{config_id}",
    response_model=ApiResponse,
    summary="更新 AI 工作流配置",
)
async def update_ai_workflow_config(
    config_id: uuid.UUID,
    data: AIWorkflowConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新 AI 工作流配置"""
    service = ConfigService(db)
    item = await service.update_ai_workflow_config(config_id, data)
    if not item:
        return ApiResponse(code=404, message="配置不存在")
    await db.commit()
    return ApiResponse(data=AIWorkflowConfigResponse.model_validate(item))


@ai_workflow_router.delete(
    "/ai-workflow-configs/{config_id}",
    response_model=ApiResponse,
    summary="删除 AI 工作流配置",
)
async def delete_ai_workflow_config(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除 AI 工作流配置"""
    service = ConfigService(db)
    result = await service.delete_ai_workflow_config(config_id)
    if not result:
        return ApiResponse(code=404, message="配置不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ==================== AI 工作流附件 Routes ====================


@ai_workflow_router.post(
    "/ai-workflow-configs/attachments/upload",
    response_model=ApiResponse,
    summary="上传 AI 工作流调用文档附件",
)
async def upload_workflow_attachment(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """上传调用文档附件（PDF/Word/Excel/TXT/MD），自动转换为 Markdown 供 AI 读取。

    返回附件元数据，前端将其存入 reference_docs.attachments 列表。
    """
    service = AttachmentService()
    try:
        metadata = await service.upload_attachment(file)
        return ApiResponse(data=ReferenceAttachmentResponse(**metadata).model_dump())
    except ValueError as e:
        return ApiResponse(code=400, message=str(e))


@ai_workflow_router.get(
    "/ai-workflow-configs/attachments/{attachment_id}/preview",
    summary="预览 AI 工作流调用文档附件",
)
async def preview_workflow_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """预览上传的附件原始文件（浏览器内嵌预览或触发下载）。"""
    from app.core.storage import get_object as minio_get, is_enabled as _minio_enabled
    from fastapi.responses import StreamingResponse
    from io import BytesIO

    service = AttachmentService()
    file_path = service.get_preview_path(attachment_id)

    # 知识库附件（无原始文件）— 返回 MD 预览
    if not file_path:
        if _minio_enabled():
            result = minio_get("safety", f"ai-workflow/md/{attachment_id}.md")
            if result is not None:
                data, _ = result
                return PlainTextResponse(data.decode("utf-8"), media_type="text/plain; charset=utf-8")
        else:
            md_path = os.path.join(service.UPLOAD_DIR, service.MD_SUBDIR, f"{attachment_id}.md")
            if os.path.exists(md_path):
                with open(md_path, encoding="utf-8") as f:
                    content = f.read()
                return PlainTextResponse(content, media_type="text/plain; charset=utf-8")
        return ApiResponse(code=404, message="附件不存在或已被删除")

    # MinIO mode: file_path is an object_key prefix; try common extensions
    if _minio_enabled() and not os.path.exists(file_path):
        for ext in (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md", ".png", ".jpg", ".jpeg"):
            full_key = f"{file_path}{ext}"
            result = minio_get("safety", full_key)
            if result is not None:
                data, ct = result
                return StreamingResponse(BytesIO(data), media_type=ct or "application/octet-stream")
        # Also try as-is (might be a full object_key)
        result = minio_get("safety", file_path)
        if result is not None:
            data, ct = result
            return StreamingResponse(BytesIO(data), media_type=ct or "application/octet-stream")
        return ApiResponse(code=404, message="附件不存在或已被删除")

    # Local mode
    # 根据文件类型设置 media_type
    ext = os.path.splitext(file_path)[1].lower()
    media_types = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".txt": "text/plain; charset=utf-8",
        ".md": "text/plain; charset=utf-8",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(file_path, media_type=media_type, filename=os.path.basename(file_path))


@ai_workflow_router.delete(
    "/ai-workflow-configs/attachments/{attachment_id}",
    response_model=ApiResponse,
    summary="删除 AI 工作流调用文档附件",
)
async def delete_workflow_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除附件及其关联的原始文件和 Markdown 文件。"""
    service = AttachmentService()
    deleted = await service.delete_attachment(attachment_id)
    if not deleted:
        return ApiResponse(code=404, message="附件不存在或已被删除")
    return ApiResponse(message="附件已删除")


@ai_workflow_router.post(
    "/ai-workflow-configs/attachments/from-knowledge",
    response_model=ApiResponse,
    summary="从知识库创建 AI 工作流调用文档附件",
)
async def create_workflow_attachments_from_knowledge(
    body: KnowledgeAttachmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """选择知识库文章作为调用文档附件，自动转为 Markdown 供 AI 读取。

    返回附件元数据列表，前端将其追加到 reference_docs.attachments。
    """
    service = AttachmentService()
    results = await service.create_knowledge_attachments(body.knowledge_ids, db)
    return ApiResponse(
        data=[ReferenceAttachmentResponse(**r).model_dump() for r in results],
        meta={"total": len(results)},
    )


