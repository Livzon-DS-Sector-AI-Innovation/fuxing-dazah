"""Info Query API — conversational RAG chat endpoint.

Uses HybridRetriever to find relevant regulation chunks, then feeds them
as context to the AI model (DeepSeek) for a cited, conversational answer.

POST /api/v1/safety/knowledge/chat
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.modules.safety.knowledge.query_service import run_knowledge_chat
from app.modules.safety.schemas import (
    InfoQueryRequest,
    InfoQueryResponse,
    InfoQuerySource,
)

logger = logging.getLogger(__name__)

info_query_router = APIRouter()


@info_query_router.post(
    "/knowledge/chat",
    response_model=ApiResponse,
    summary="知识库对话查询（RAG + AI）",
)
async def knowledge_chat(
    body: InfoQueryRequest,
    db: AsyncSession = Depends(get_db),
):
    """对话式查询安全知识库。

    使用 RAG 检索相关法规条款，通过 AI 模型生成带引用的自然语言回答。
    """
    # Convert history dicts
    history = [{"role": m.role, "content": m.content} for m in body.history]

    # Run the shared RAG pipeline
    answer, source_dicts = await run_knowledge_chat(
        query=body.query,
        history=history,
        db=db,
        channel="web",
    )

    # Convert source dicts to Pydantic models
    sources = [
        InfoQuerySource(
            doc_title=s["doc_title"],
            article_ref=s["article_ref"],
            chunk_text=s["chunk_text"],
            doc_category=s["doc_category"],
            feishu_url=s["feishu_url"],
        )
        for s in source_dicts
    ]

    return ApiResponse(
        data=InfoQueryResponse(
            answer=answer,
            sources=sources,
        ).model_dump()
    )


@info_query_router.post(
    "/knowledge/cache/invalidate",
    response_model=ApiResponse,
    summary="清除知识库缓存（Chat + RAG）",
)
async def invalidate_cache():
    """递增缓存 epoch，使所有旧 Chat/RAG 缓存即时失效。

    当知识库内容变更（新增/更新/删除法规文档）后调用此接口，
    确保后续查询使用最新数据而非过期缓存。
    """
    from app.modules.safety.knowledge.cache import invalidate_knowledge_cache

    await invalidate_knowledge_cache()
    return ApiResponse(
        data={"message": "知识库缓存已清除（epoch 递增）", "status": "ok"}
    )
