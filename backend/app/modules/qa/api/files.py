"""QA 文件内容端点：提取重试、处理结果与产物、原文件预览下载。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.core.response import success_response
from app.modules.qa import file_service, service
from app.modules.qa.api._deps import (
    qa_read,
    version_create,
)
from app.modules.qa.models import DocumentExtractionArtifact
from app.modules.qa.repository import (
    get_file,
    get_latest_extraction_run_any_status,
)
from app.modules.qa.schemas import (
    DocumentProcessingResultOut,
    ProcessingResultView,
)
from app.platform.identity.models import User
from app.shared.schemas import ApiResponse

router = APIRouter()


@router.post("/document-files/{file_id}/retry", summary="重试正文提取")
async def retry_file_extraction(
    file_id: uuid.UUID,
    user: User = Depends(version_create),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.retry_extraction(db, file_id, user)
    return success_response({"id": row.id, "extraction_status": row.extraction_status})


@router.get(
    "/document-files/{file_id}/processing-results",
    response_model=ApiResponse,
    summary="查看文件解析与分块结果",
)
async def get_file_processing_results(
    file_id: uuid.UUID,
    user: User = Depends(qa_read),
    db: AsyncSession = Depends(get_db),
    view: ProcessingResultView = Query("raw_blocks"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    content_limit: int = Query(
        800,
        ge=100,
        le=2000,
        description="每个正文预览最多返回的字符数；完整正文仍保留在受保护的内部存储中",
    ),
) -> Any:
    data = await service.document_processing_results(
        db,
        file_id,
        view=view,
        page=page,
        page_size=page_size,
        content_limit=content_limit,
    )
    # 本端点能按页把整篇正文取走（content_limit 上限 2000），与 /content
    # 预览/下载是同一份受保护内容；不写审计等于把下载审计整条绕过去。
    from app.modules.qa.service import _audit

    await _audit(
        db,
        action="view_processing_results",
        user=user,
        resource_type="document_file",
        resource_id=file_id,
        extra={"view": view, "page": page, "page_size": page_size},
    )
    return success_response(
        DocumentProcessingResultOut.model_validate(data).model_dump(mode="json")
    )


@router.get("/document-files/{file_id}/artifacts", summary="查看文件提取产物")
async def list_file_artifacts(
    file_id: uuid.UUID,
    user: User = Depends(qa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    file_row = await get_file(db, file_id)
    if file_row is None:
        raise NotFoundException("文件", str(file_id))
    query = (
        select(DocumentExtractionArtifact)
        .where(
            DocumentExtractionArtifact.file_id == file_id,
            DocumentExtractionArtifact.is_deleted.is_(False),
        )
        .order_by(
            DocumentExtractionArtifact.created_at.desc(),
            DocumentExtractionArtifact.source_name,
        )
    )
    # 重解析期间 current 指针仍然可能指向上一版成功运行；此时不应把
    # 旧产物返回给前端，否则前端会误以为当前批次已经完成。产物列表
    # 始终只绑定一个明确的运行，且 queued/processing 运行暂不展示产物。
    latest_run = await get_latest_extraction_run_any_status(db, file_id)
    if file_row.extraction_status in {"queued", "processing"} or (
        latest_run is not None and latest_run.status in {"queued", "processing"}
    ):
        return success_response({"items": [], "total": 0})
    artifact_run_id = file_row.current_extraction_run_id
    if artifact_run_id is None and latest_run is not None:
        artifact_run_id = latest_run.id
    if artifact_run_id is not None:
        query = query.where(
            DocumentExtractionArtifact.extraction_run_id == artifact_run_id
        )
    else:
        return success_response({"items": [], "total": 0})
    result = await db.execute(query)
    items = [
        {
            "id": item.id,
            "file_id": item.file_id,
            "extraction_run_id": item.extraction_run_id,
            "artifact_type": item.artifact_type,
            "source_name": item.source_name,
            "mime_type": item.mime_type,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "created_at": item.created_at,
        }
        for item in result.scalars()
    ]
    return success_response({"items": items, "total": len(items)})


@router.get(
    "/document-files/{file_id}/artifacts/{artifact_id}/content",
    summary="预览或下载文件提取产物",
)
async def get_file_artifact_content(
    file_id: uuid.UUID,
    artifact_id: uuid.UUID,
    user: User = Depends(qa_read),
    db: AsyncSession = Depends(get_db),
    download: bool = False,
) -> StreamingResponse:
    # 和列表端点、原件端点同一道软删闸门：产物行自己带 is_deleted，但文件
    # 被软删之后它的提取产物也得跟着不可达，否则文件 404 了产物还能整包拖走。
    file_row = await get_file(db, file_id)
    if file_row is None:
        raise NotFoundException("文件", str(file_id))
    result = await db.execute(
        select(DocumentExtractionArtifact).where(
            DocumentExtractionArtifact.id == artifact_id,
            DocumentExtractionArtifact.file_id == file_id,
            DocumentExtractionArtifact.is_deleted.is_(False),
        )
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise NotFoundException("文件提取产物", str(artifact_id))
    content = await asyncio.to_thread(file_service.read_object, artifact.storage_key)
    if content is None:
        raise NotFoundException("文件提取产物内容", str(artifact_id))
    data, stored_mime = content
    mime = artifact.mime_type or stored_mime
    await service._audit(
        db,
        action="download" if download else "preview",
        user=user,
        resource_type="document_extraction_artifact",
        resource_id=artifact.id,
        extra={"file_id": str(file_id), "artifact_type": artifact.artifact_type},
    )
    # 产物的 MIME 来自远端 ZIP 成员名，不能凭它决定是否 inline 渲染。
    inline_type = None if download else file_service.inline_media_type(mime)
    if inline_type:
        disposition, media_type = "inline", inline_type
    else:
        # 不内联就必须是附件；下载时保留真实类型方便系统关联，预览但类型
        # 不安全时连类型一起降级，不给浏览器任何可执行的口径。
        disposition = "attachment"
        media_type = (mime if download else None) or "application/octet-stream"
    return StreamingResponse(
        iter([data]),
        media_type=media_type,
        headers={
            "Content-Disposition": file_service.content_disposition(
                disposition, artifact.source_name
            ),
            "X-Content-SHA256": artifact.sha256,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/document-files/{file_id}/content", summary="预览或下载质量文件")
async def get_file_content(
    file_id: uuid.UUID,
    user: User = Depends(qa_read),
    db: AsyncSession = Depends(get_db),
    download: bool = False,
) -> StreamingResponse:
    row = await get_file(db, file_id)
    if row is None:
        raise NotFoundException("文件", str(file_id))
    # MinIO 客户端与本地 read_bytes 都是阻塞调用，单文件最大 50MB：放进线程池，
    # 否则会占住事件循环，阻塞同 worker 的其它请求。
    content = await asyncio.to_thread(file_service.read_file, row.storage_key)
    if content is None:
        raise NotFoundException("文件内容", str(file_id))
    data, stored_mime = content
    mime = row.mime_type or stored_mime
    from app.modules.qa.service import _audit

    await _audit(
        db,
        action="download" if download else "preview",
        user=user,
        resource_type="document_file",
        resource_id=row.id,
        extra={"sha256": row.sha256, "size_bytes": row.size_bytes},
    )
    disposition = (
        "attachment"
        if download or row.extension.lower().lstrip(".") != "pdf"
        else "inline"
    )
    headers = {
        "Content-Disposition": file_service.content_disposition(
            disposition, row.original_filename
        ),
        "X-Content-SHA256": row.sha256,
    }
    return StreamingResponse(iter([data]), media_type=mime, headers=headers)


# ───────────────────────── 搜索与审计 ─────────────────────────
