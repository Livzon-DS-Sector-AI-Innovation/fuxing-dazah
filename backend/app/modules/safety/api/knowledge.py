"""Safety API — knowledge endpoints."""

import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.core.storage import is_enabled as minio_enabled
from app.core.storage import upload_object
from app.modules.safety.schemas import (
    BatchGenerateCardsRequest,
    DuplicateCheckRequest,
    GeneratePptRequest,
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
    page_size: int = Query(20, ge=1, le=1000),
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


# ── AI 智能解析 ──


@knowledge_router.post("/knowledge-articles/parse", response_model=ApiResponse, summary="AI 解析文档元数据")
async def parse_knowledge_document(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """上传文档文件，AI 自动解析提取元数据（不存库）"""
    allowed_exts = {".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".md"}
    file_ext = os.path.splitext(file.filename or ".txt")[1].lower()
    if file_ext not in allowed_exts:
        return ApiResponse(
            code=400,
            message=f"不支持的文件格式: {file_ext}，支持: {', '.join(sorted(allowed_exts))}",
        )

    service = KnowledgeService(db)
    try:
        result = await service.parse_document_metadata(file)
        return ApiResponse(data=result.model_dump())
    except ValueError as e:
        return ApiResponse(code=400, message=str(e))
    except Exception as e:
        return ApiResponse(code=500, message=f"文档解析失败: {str(e)}")


@knowledge_router.post("/knowledge-articles/batch-parse", response_model=ApiResponse, summary="批量 AI 解析文档")
async def batch_parse_knowledge_documents(
    files: list[UploadFile],
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """批量上传文档文件，AI 解析元数据（不存库）"""
    service = KnowledgeService(db)
    results = await service.batch_parse_documents(files)
    return ApiResponse(
        data=[r.model_dump() for r in results],
        meta={"total": len(results)},
    )


# ── 重复检测 ──


@knowledge_router.post("/knowledge-articles/check-duplicate", response_model=ApiResponse, summary="检测重复文档")
async def check_duplicate_article(
    data: DuplicateCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """检测知识库中是否已有相似文档"""
    service = KnowledgeService(db)
    result = await service.check_duplicate(data.title, data.content)
    return ApiResponse(data=result.model_dump())


# ── 版本管理 ──


@knowledge_router.get("/knowledge-articles/{article_id}/versions", response_model=ApiResponse, summary="获取文档版本链")
async def get_article_version_chain(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取文档的完整版本链（从旧到新排列）"""
    service = KnowledgeService(db)
    chain = await service.get_version_chain(article_id)
    if not chain:
        return ApiResponse(code=404, message="文档不存在")
    return ApiResponse(data=[v.model_dump() for v in chain])


@knowledge_router.post("/knowledge-articles/{article_id}/new-version", response_model=ApiResponse, summary="创建新版本")
async def create_new_article_version(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """基于现有文档创建新版本（自动复制基本信息，旧版标记为被替代）"""
    service = KnowledgeService(db)
    new_article, version_chain = await service.create_new_version(article_id)
    if not new_article:
        return ApiResponse(code=404, message="原文档不存在")
    await db.commit()
    return ApiResponse(data={
        "new_article": SafetyKnowledgeArticleResponse.model_validate(new_article).model_dump(),
        "version_chain": [v.model_dump() for v in version_chain],
    })


# ── 知识卡片管理 ──


@knowledge_router.post("/knowledge-articles/{article_id}/generate-card", response_model=ApiResponse, summary="AI 生成知识卡片")
async def generate_knowledge_card(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """从文档全文 AI 生成 6 维度结构化知识卡片，用于 Agent 知识注入。"""
    service = KnowledgeService(db)
    result = await service.generate_knowledge_card(article_id)
    if not result:
        return ApiResponse(code=404, message="文档不存在")
    await db.commit()
    return ApiResponse(data=result.model_dump())


@knowledge_router.get("/knowledge-articles/{article_id}/agent-stats", response_model=ApiResponse, summary="获取知识卡片 Agent 使用统计")
async def get_agent_usage_stats(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取该文档知识卡片被各 Agent 注入的使用频次统计。"""
    service = KnowledgeService(db)
    result = await service.get_agent_usage_stats(article_id)
    if not result:
        return ApiResponse(code=404, message="文档不存在")
    return ApiResponse(data=result.model_dump())


@knowledge_router.post("/knowledge-articles/batch/generate-cards", response_model=ApiResponse, summary="批量生成知识卡片")
async def batch_generate_knowledge_cards(
    data: BatchGenerateCardsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """批量对多个文档 AI 生成知识卡片（顺序执行，单条失败不影响其他）。"""
    service = KnowledgeService(db)
    result = await service.batch_generate_cards(data.article_ids)
    await db.commit()
    return ApiResponse(data=result.model_dump())


# ── AI PPT 生成 ──


@knowledge_router.post("/knowledge-articles/{article_id}/generate-ppt", response_model=ApiResponse, summary="AI 生成 PPT")
async def generate_ppt(
    article_id: uuid.UUID,
    data: GeneratePptRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """从文档全文 AI 生成培训 PPT（.pptx 文件），返回下载 URL。"""
    service = KnowledgeService(db)
    template = data.template if data else "training"
    style = data.style if data else "professional"
    result = await service.generate_ppt(article_id, template=template, style=style)
    if not result:
        return ApiResponse(code=404, message="文档不存在")
    return ApiResponse(data=result.model_dump())


@knowledge_router.get("/knowledge-articles/{article_id}/ppt-history", response_model=ApiResponse, summary="获取 PPT 生成历史")
async def get_ppt_history(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取文档的 PPT 生成历史记录列表。"""
    service = KnowledgeService(db)
    result = await service.get_ppt_history(article_id)
    return ApiResponse(data=result.model_dump())


# ── AI 摘要生成 ──


@knowledge_router.post("/knowledge-articles/{article_id}/generate-summary", response_model=ApiResponse, summary="AI 生成摘要")
async def generate_summary(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """从文档全文 AI 生成结构化摘要并保存。"""
    service = KnowledgeService(db)
    result = await service.generate_summary(article_id)
    if not result:
        return ApiResponse(code=404, message="文档不存在")
    await db.commit()
    return ApiResponse(data=result.model_dump())


# ── 语义搜索 ──


@knowledge_router.get("/knowledge-articles/semantic-search", response_model=ApiResponse, summary="语义搜索知识库")
async def semantic_search_articles(
    q: str = Query(..., description="自然语言搜索查询"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """用自然语言搜索知识库文档（AI 解析查询意图 + 关键词匹配）"""
    service = KnowledgeService(db)
    skip = (page - 1) * page_size
    items, total = await service.semantic_search(q, skip=skip, limit=page_size)
    return ApiResponse(
        data=items,
        meta={"page": page, "page_size": page_size, "total": total},
    )


# ── Bitable 同步 ──


@knowledge_router.post("/knowledge-articles/sync", response_model=ApiResponse, summary="从 Bitable 同步知识库")
async def sync_knowledge_from_bitable(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """从飞书多维表格全量同步知识库文档（安全管理制度 + 法规标准 + 设备说明书）。

    以 Bitable 为数据源，三阶段同步：
    - CREATE：Bitable 有、平台无
    - UPDATE：双方都有，字段有差异
    - DELETE：平台有、Bitable 无（软删除）
    """
    service = KnowledgeService(db)
    result = await service.sync_from_bitable()
    await db.commit()
    return ApiResponse(data=result.model_dump())


