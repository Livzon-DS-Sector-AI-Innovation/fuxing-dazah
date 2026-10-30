"""MSDS 智能提取入库 API — 采集列表 / 台账列表 / 统计。

挂载于 /api/v1/safety/msds/...（api/__init__.py 聚合）。

权限说明：写操作（触发解析/重试）面向 safety_admin + dept_leader；
查询面向全部角色。API 层认证沿用现有占位机制（前端 SSO 接入后统一收紧），
角色策略在业务 Agent 侧由 permissions.py 强制。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas.msds import (
    ARCHIVE_STATUS_OPTIONS,
    PARSE_STATUS_OPTIONS,
    REVIEW_STATUS_OPTIONS,
    TYPO_REVIEW_STATUS_OPTIONS,
    MsdsCollectionResponse,
    MsdsDocumentResponse,
    MsdsStatsResponse,
)
from app.modules.safety.service.msds import MsdsService

msds_router = APIRouter()


@msds_router.get(
    "/msds/enums", response_model=ApiResponse,
    summary="获取 MSDS 枚举选项",
)
async def get_enums():
    return ApiResponse(data={
        "parse_status": PARSE_STATUS_OPTIONS,
        "review_status": REVIEW_STATUS_OPTIONS,
        "archive_status": ARCHIVE_STATUS_OPTIONS,
        "typo_review_status": TYPO_REVIEW_STATUS_OPTIONS,
    })


@msds_router.get(
    "/msds/stats", response_model=ApiResponse,
    summary="MSDS 统计仪表盘",
)
async def get_stats(
    db: AsyncSession = Depends(get_db),
):
    service = MsdsService(db)
    stats = await service.get_stats()
    return ApiResponse(data=MsdsStatsResponse(**stats))


@msds_router.get(
    "/msds/collection", response_model=ApiResponse,
    summary="供应商资料采集列表",
)
async def list_collections(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    parse_status: str | None = Query(None, description="解析状态: pending/parsed/failed"),
    keyword: str | None = Query(None, description="关键词搜索"),
    db: AsyncSession = Depends(get_db),
):
    service = MsdsService(db)
    skip = (page - 1) * page_size
    items, total = await service.list_collections(
        skip, page_size, parse_status=parse_status, keyword=keyword,
    )
    return ApiResponse(
        data=[MsdsCollectionResponse.model_validate(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@msds_router.get(
    "/msds/collection/{collection_id}", response_model=ApiResponse,
    summary="供应商资料采集详情",
)
async def get_collection(
    collection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = MsdsService(db)
    item = await service.get_collection(collection_id)
    if not item or item.is_deleted:
        raise HTTPException(status_code=404, detail="采集记录不存在")
    return ApiResponse(data=MsdsCollectionResponse.model_validate(item))


@msds_router.post(
    "/msds/collection/{collection_id}/parse", response_model=ApiResponse,
    summary="触发/重试 AI 解析（自动写回）",
)
async def retry_parse(
    collection_id: uuid.UUID,
    current_user: CurrentUser | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """手动触发采集记录解析（含自动写回 MSDS 表）。

    权限：写操作面向 safety_admin + dept_leader；
    查询面向全部角色。API 层认证沿用现有占位机制（前端 SSO 接入后统一收紧），
    角色策略在业务 Agent 侧由 permissions.py 强制。
    """
    service = MsdsService(db)
    item = await service.get_collection(collection_id)
    if not item or item.is_deleted:
        raise HTTPException(status_code=404, detail="采集记录不存在")
    await service.process_collection(collection_id)
    refreshed = await service.get_collection(collection_id)
    return ApiResponse(data=MsdsCollectionResponse.model_validate(refreshed))


@msds_router.get(
    "/msds", response_model=ApiResponse,
    summary="MSDS 台账列表",
)
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    name: str | None = Query(None, description="物质名称筛选"),
    cas_no: str | None = Query(None, description="CAS号筛选"),
    review_status: str | None = Query(None, description="复核状态筛选"),
    archive_status: str | None = Query(None, description="归档状态筛选"),
    db: AsyncSession = Depends(get_db),
):
    service = MsdsService(db)
    skip = (page - 1) * page_size
    items, total = await service.list_documents(
        skip, page_size,
        name=name, cas_no=cas_no,
        review_status=review_status, archive_status=archive_status,
    )
    return ApiResponse(
        data=[MsdsDocumentResponse.model_validate(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@msds_router.get(
    "/msds/{document_id}", response_model=ApiResponse,
    summary="MSDS 台账详情",
)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = MsdsService(db)
    item = await service.get_document(document_id)
    if not item or item.is_deleted:
        raise HTTPException(status_code=404, detail="台账记录不存在")
    return ApiResponse(data=MsdsDocumentResponse.model_validate(item))


async def _resolve_feishu_record_id(document_id: str, db: AsyncSession) -> str:
    """document_id 兼容双形态：PG 镜像 UUID / 台账表飞书 record_id（直读模式）。"""
    try:
        pg_id = uuid.UUID(document_id)
    except ValueError:
        pg_id = None
    if pg_id is not None:
        service = MsdsService(db)
        item = await service.get_document(pg_id)
        if item and not item.is_deleted and item.feishu_record_id:
            return item.feishu_record_id
        raise HTTPException(status_code=404, detail="台账记录不存在")
    if document_id.startswith("rec"):
        return document_id
    raise HTTPException(status_code=404, detail="台账记录不存在（需 PG id 或 rec 开头的飞书记录 id）")


@msds_router.post(
    "/msds/{document_id}/proofread", response_model=ApiResponse,
    summary="重跑错别字 AI 校对（结果写回台账表「错别字审核/明细」）",
)
async def proofread_document(
    document_id: str,
    current_user: CurrentUser | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """手动触发单条错别字校对（写回管线自动跑，此端点供人工重跑/存量补跑）。

    权限口径同 retry_parse：写操作面向 safety_admin + dept_leader。
    """
    record_id = await _resolve_feishu_record_id(document_id, db)
    from app.modules.safety.service.msds_review import run_proofread_for_record

    result = await run_proofread_for_record(record_id)
    return ApiResponse(data=result)


@msds_router.post(
    "/msds/{document_id}/rebuild-pdf", response_model=ApiResponse,
    summary="强制重建标准 PDF 并替换「MSDS附件」",
)
async def rebuild_document_pdf(
    document_id: str,
    current_user: CurrentUser | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """跳过内容 hash 判定直接重建 PDF（模板修复后追平存量附件用）。

    权限口径同 retry_parse：写操作面向 safety_admin + dept_leader。
    """
    record_id = await _resolve_feishu_record_id(document_id, db)
    from app.modules.safety.service.msds_review import sync_pdf_revision

    result = await sync_pdf_revision(record_id, force=True)
    return ApiResponse(data=result)
