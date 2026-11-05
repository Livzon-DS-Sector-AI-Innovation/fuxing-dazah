"""图谱解析 API 路由（仅预览；确认填入复用 /tasks/{id}/calc-fill）。"""

from pathlib import Path

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.core.response import success_response
from app.modules.quality.api._common import router
from app.modules.quality.service.chromatogram import (
    ALLOWED_SUFFIXES,
    MAX_UPLOAD_BYTES,
    ChromatogramParseError,
    extract_peak_table,
    parse_chromatogram_markdown,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission


@router.post("/chromatograms/parse", summary="图谱截图/PDF 解析（MinerU VLM，仅预览不落库）")
async def parse_chromatogram_endpoint(
    file: UploadFile = File(...),
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
    return success_response(data={
        "filename": filename,
        "peaks": peaks,
        "markdown_preview": markdown[:2000],
    })
