"""File proxy endpoints — MinIO / local dual-mode file serving.

All file access through this proxy; browsers never connect to MinIO directly.
Supports backward compatibility with legacy local paths (uploads/safety/...).
"""

import logging
import os
import urllib.parse
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.storage import get_object
from app.core.storage import is_enabled as minio_enabled

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


def _resolve_local_path(file_path: str) -> str | None:
    """Resolve a stored file path to an actual local filesystem path.

    Handles three storage conventions:
      1. Clean relative paths (new): ``safety/hazard/file.jpg``
         → ``{cwd}/uploads/safety/hazard/file.jpg``
      2. Legacy prefix paths (old): ``uploads/safety/hazard/file.jpg``
         → ``{cwd}/uploads/safety/hazard/file.jpg`` (via stripping prefix
         and rejoining with uploads base)
      3. Absolute paths (very old / cross-drive): ``E:/.../uploads/...``
         → used as-is if the file exists
    """
    cwd = os.path.abspath(".")
    uploads_base = os.path.abspath("./uploads")

    # 1. Try joining with uploads base (handles clean paths + legacy prefix paths)
    #    If path starts with "uploads/", strip it to avoid double prefix:
    #      uploads/safety/hazard/f.jpg  →  safety/hazard/f.jpg  →  OK
    #      safety/hazard/f.jpg          →  safety/hazard/f.jpg  →  OK
    if file_path.startswith("uploads/"):
        relative = file_path[len("uploads/"):]
    elif file_path.startswith("uploads\\"):
        relative = file_path[len("uploads\\"):]
    else:
        relative = file_path
    candidate = os.path.normpath(os.path.join(uploads_base, relative))
    if os.path.isfile(candidate):
        return candidate

    # 2. Try the path directly (handles absolute paths and edge cases)
    if os.path.isabs(file_path) and os.path.isfile(file_path):
        return file_path

    # 3. Try relative to cwd directly (for paths already anchored at cwd)
    candidate = os.path.normpath(os.path.join(cwd, file_path))
    if os.path.isfile(candidate):
        return candidate

    return None


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

    # URL-decode in case the client encoded special characters (e.g. %2F from
    # encodeURIComponent). In most cases this is a no-op on already-decoded paths.
    file_path = urllib.parse.unquote(file_path)

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
        # ── Fallback: try local paths (MinIO can be unreachable) ──
        local_path = _resolve_local_path(file_path)
        if local_path:
            return FileResponse(local_path, media_type=content_type)
        raise HTTPException(status_code=404, detail="File not found")

    # ── Local mode ──
    local_path = _resolve_local_path(file_path)
    if local_path:
        return FileResponse(local_path, media_type=content_type)

    raise HTTPException(status_code=404, detail="File not found")
