"""File proxy endpoints — MinIO / local dual-mode file serving.

All file access through this proxy; browsers never connect to MinIO directly.
Supports backward compatibility with legacy local paths (uploads/safety/...).
"""

import logging
import os
from io import BytesIO

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.storage import get_object, is_enabled as minio_enabled

logger = logging.getLogger(__name__)

files_router = APIRouter()

# ── MIME type mapping (extension -> content-type) ──
_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".zip": "application/zip",
}


def _guess_content_type(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    return _MIME_TYPES.get(ext, "application/octet-stream")


@files_router.get(
    "/files/{file_path:path}",
    summary="代理文件访问（MinIO / 本地双模式）",
    description="通过 object_key 或本地路径返回文件内容。支持向后兼容旧路径。",
)
async def serve_file(
    file_path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Serve a file from MinIO or local disk. Supports legacy paths."""

    content_type = _guess_content_type(file_path)

    if minio_enabled():
        # ── MinIO mode: try object_key first ──
        result = get_object("safety", file_path)
        if result is not None:
            data, ct = result
            return StreamingResponse(
                BytesIO(data),
                media_type=ct or content_type,
            )
        # ── Fallback: try legacy local path ──
        uploads_base = os.path.abspath("./uploads")
        local_path = os.path.normpath(os.path.join(uploads_base, file_path))
        if os.path.isfile(local_path):
            return FileResponse(local_path, media_type=content_type)
        # ── Fallback: file_path as absolute path ──
        if os.path.isabs(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path, media_type=content_type)
        # ── Not found ──
        raise HTTPException(status_code=404, detail="File not found")

    # ── Local mode ──
    # Try as relative path first
    uploads_base = os.path.abspath("./uploads")
    local_path = os.path.normpath(os.path.join(uploads_base, file_path))
    if os.path.isfile(local_path):
        return FileResponse(local_path, media_type=content_type)

    # Try as absolute path (legacy data)
    if os.path.isabs(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path, media_type=content_type)

    raise HTTPException(status_code=404, detail="File not found")
