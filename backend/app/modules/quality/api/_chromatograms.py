"""图谱解析 API 路由（解析预览 + 可选归档原图；确认填入复用 /tasks/{id}/calc-fill）。"""

import uuid
from pathlib import Path

from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.quality import storage as quality_storage
from app.modules.quality.api._common import _safe_filename, router
from app.modules.quality.repository import create_task_attachment, get_test_task
from app.modules.quality.service.chromatogram import (
    ALLOWED_SUFFIXES,
    MAX_UPLOAD_BYTES,
    ChromatogramParseError,
    extract_peak_table,
    parse_chromatogram_markdown,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission


@router.post("/chromatograms/parse", summary="图谱截图/PDF 解析（MinerU VLM，仅预览；带 task_id 时原图归档为任务附件）")
async def parse_chromatogram_endpoint(
    file: UploadFile = File(...),
    task_id: uuid.UUID | None = Form(default=None, description="检验任务 ID（提供时原图归档留痕）"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:fill")),
) -> JSONResponse:
    filename = file.filename or "chromatogram"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=422, detail=f"不支持的文件类型 {suffix or '(无后缀)'}，仅支持图片/PDF")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="文件内容为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限")
    try:
        markdown = await parse_chromatogram_markdown(data, filename)
        peaks = extract_peak_table(markdown)
    except ChromatogramParseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # 原图归档留痕（GMP 口径）：解析成功后归档为任务附件，source=chromatogram，
    # 与手工上传附件（source=manual）、计算表解析归档（source=parse）区分。
    archived = False
    if task_id is not None:
        task = await get_test_task(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="检验任务不存在")
        object_key = f"{task_id}/{uuid.uuid4().hex[:12]}_{_safe_filename(filename)}"
        quality_storage.upload_attachment(object_key, data, file.content_type or "application/octet-stream")
        att = await create_task_attachment(db, {
            "task_id": task_id,
            "filename": filename,
            "content_type": file.content_type or "application/octet-stream",
            "object_key": object_key,
            "size": len(data),
            "uploaded_by": _user.id,
            "source": "chromatogram",
            "remark": "图谱解析原图自动归档",
        })
        archived = bool(att.id)

    return success_response(data={
        "filename": filename,
        "peaks": peaks,
        "markdown_preview": markdown[:2000],
        "archived": archived,
    })
