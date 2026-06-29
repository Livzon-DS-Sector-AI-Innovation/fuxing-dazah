"""Safety API — knowledge endpoints."""

import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.core.storage import is_enabled as minio_enabled, upload_object
from app.modules.safety.schemas import (
    SafetyKnowledgeArticleCreate,
    SafetyKnowledgeArticleResponse,
    SafetyKnowledgeArticleUpdate,
)
from app.modules.safety.service import (
    KnowledgeService,
)

knowledge_router = APIRouter()


@knowledge_router.get("/knowledge-articles", response_model=ApiResponse, summary="获取安全知识库文章列表")
async def get_knowledge_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    category: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全知识库文章列表"""
    service = KnowledgeService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_articles(skip, page_size, category, status, keyword)
    return ApiResponse(
        data=[SafetyKnowledgeArticleResponse.model_validate(a) for a in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@knowledge_router.post("/knowledge-articles", response_model=ApiResponse, summary="创建安全知识库文章")
async def create_knowledge_article(
    data: SafetyKnowledgeArticleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建安全知识库文章"""
    service = KnowledgeService(db)
    item = await service.create_article(data)
    await db.commit()
    return ApiResponse(data=SafetyKnowledgeArticleResponse.model_validate(item))


@knowledge_router.get("/knowledge-articles/{article_id}", response_model=ApiResponse, summary="获取安全知识库文章详情")
async def get_knowledge_article(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全知识库文章详情"""
    service = KnowledgeService(db)
    item = await service.get_article(article_id)
    if not item:
        return ApiResponse(code=404, message="文章不存在")
    return ApiResponse(data=SafetyKnowledgeArticleResponse.model_validate(item))


@knowledge_router.put("/knowledge-articles/{article_id}", response_model=ApiResponse, summary="更新安全知识库文章")
async def update_knowledge_article(
    article_id: uuid.UUID,
    data: SafetyKnowledgeArticleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新安全知识库文章"""
    service = KnowledgeService(db)
    item = await service.update_article(article_id, data)
    if not item:
        return ApiResponse(code=404, message="文章不存在")
    await db.commit()
    return ApiResponse(data=SafetyKnowledgeArticleResponse.model_validate(item))


@knowledge_router.delete("/knowledge-articles/{article_id}", response_model=ApiResponse, summary="删除安全知识库文章")
async def delete_knowledge_article(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除安全知识库文章"""
    service = KnowledgeService(db)
    result = await service.delete_article(article_id)
    if not result:
        return ApiResponse(code=404, message="文章不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@knowledge_router.post("/knowledge-articles/{article_id}/publish", response_model=ApiResponse, summary="发布知识库文章")
async def publish_knowledge_article(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """发布文章（草稿→已发布）"""
    service = KnowledgeService(db)
    item = await service.publish_article(article_id)
    if not item:
        return ApiResponse(code=400, message="无法发布，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SafetyKnowledgeArticleResponse.model_validate(item))


@knowledge_router.post("/knowledge-articles/{article_id}/archive", response_model=ApiResponse, summary="归档知识库文章")
async def archive_knowledge_article(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """归档文章（已发布→已归档）"""
    service = KnowledgeService(db)
    item = await service.archive_article(article_id)
    if not item:
        return ApiResponse(code=400, message="无法归档，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SafetyKnowledgeArticleResponse.model_validate(item))


@knowledge_router.post("/knowledge-articles/{article_id}/upload", response_model=ApiResponse, summary="上传知识库文章附件")
async def upload_knowledge_article_attachment(
    article_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """上传知识库文章附件"""

    file_ext = os.path.splitext(file.filename or ".bin")[1]
    safe_name = f"{article_id}_{int(datetime.now().timestamp())}{file_ext}"
    content = await file.read()

    if minio_enabled():
        object_key = f"knowledge/{safe_name}"
        upload_object("safety", object_key, content, len(content), file.content_type or "application/octet-stream")
        stored_path = object_key
    else:
        upload_dir = os.path.join("uploads", "safety", "knowledge")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, safe_name)
        with open(file_path, "wb") as f:
            f.write(content)
        stored_path = file_path

    from app.modules.safety.repository import SafetyRepository
    repo = SafetyRepository(db)
    item = await repo.update_knowledge_article(
        article_id,
        {
            "attachment_path": stored_path,
            "attachment_original_name": file.filename or "unknown",
        },
    )
    if not item:
        return ApiResponse(code=404, message="文章不存在")
    await db.commit()
    return ApiResponse(data=SafetyKnowledgeArticleResponse.model_validate(item))


