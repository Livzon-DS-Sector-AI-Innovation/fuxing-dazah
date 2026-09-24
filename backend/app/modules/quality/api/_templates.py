"""templates API 路由（api.py 拆分）。"""

import uuid
from pathlib import Path
from typing import Any

from fastapi import (
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.quality import storage as quality_storage
from app.modules.quality.api._common import (
    REPORT_TEMPLATE_DIR,
    _doc_match_info,
    _extract_number_tokens,
    _match_template_to_doc,
    _scan_templates,
    _template_number_tokens,
    router,
)
from app.modules.quality.repository import (
    delete_coa_binding,
    get_standard_document,
    list_coa_bindings,
    list_standard_documents,
    upsert_coa_binding,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission


@router.get("/templates", summary="列出模板（含 SOP 绑定状态）")
async def list_templates(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    quality_storage.sync_templates_from_minio()
    items = _scan_templates(REPORT_TEMPLATE_DIR) if REPORT_TEMPLATE_DIR.exists() else []
    # 一次性加载全部标准文档的号码 token（未绑定模板的匹配建议）
    docs = await list_standard_documents(db)
    doc_tokens = {d.id: _extract_number_tokens(d.file_no or "", d.product_internal_code or "", d.product_code or "", d.version or "") for d in docs}
    bindings = {b.template_path: b for b in await list_coa_bindings(db)}

    def annotate(nodes: list[dict[str, Any]]) -> None:
        for it in nodes:
            if it["type"] == "folder":
                annotate(it.get("children", []))
            else:
                binding = bindings.get(it["path"])
                it["binding"] = (
                    {"sop_no": binding.sop_no, "doc_id": str(binding.standard_document_id), "description": binding.description}
                    if binding else None
                )
                if binding is None:
                    tp_tokens = _template_number_tokens(REPORT_TEMPLATE_DIR / it["path"])
                    it["matched"] = _doc_match_info(_match_template_to_doc(tp_tokens, docs, doc_tokens))

    annotate(items)
    return items


@router.get("/templates/all-placeholders", summary="获取所有模板的所有占位符名称")
async def all_placeholders() -> list[str]:
    names: set[str] = set()

    def walk(items: list[dict[str, Any]]) -> None:
        for item in items:
            if item["type"] == "folder":
                walk(item.get("children", []))
            else:
                for ph in item.get("placeholders", []):
                    names.add(ph["name"])

    walk(_scan_templates(REPORT_TEMPLATE_DIR) if REPORT_TEMPLATE_DIR.exists() else [])
    base = ["流水号", "批号", "规格", "生产日期", "批量_kg", "有效期_年"]
    rest = sorted(n for n in names if n not in base)
    return base + rest


@router.post("/templates/folders", summary="创建文件夹")
async def create_folder(
    name: str = Body(..., embed=True),
    _user: User = Depends(require_permission("quality:template:manage")),
) -> dict[str, Any]:
    p = quality_storage.safe_join(REPORT_TEMPLATE_DIR, name)
    if p is None:
        raise HTTPException(status_code=400, detail="非法文件夹名")
    p.mkdir(parents=True, exist_ok=True)
    return {"name": name}


@router.delete("/templates/folders", summary="删除空文件夹")
async def delete_folder(
    name: str = Body(..., embed=True),
    _user: User = Depends(require_permission("quality:template:manage")),
) -> dict[str, Any]:
    p = quality_storage.safe_join(REPORT_TEMPLATE_DIR, name)
    if p is None or not p.is_dir():
        raise HTTPException(status_code=404, detail="不存在")
    try:
        p.rmdir()
    except OSError:
        raise HTTPException(status_code=400, detail="文件夹不为空") from None
    return {"message": f"已删除 {name}"}


@router.delete("/templates/file", summary="删除单个模板文件")
async def delete_template_file(
    path: str = Body(..., embed=True),
    _user: User = Depends(require_permission("quality:template:manage")),
) -> dict[str, Any]:
    base = REPORT_TEMPLATE_DIR.resolve()
    p = (REPORT_TEMPLATE_DIR / path).resolve()
    if not str(p).startswith(str(base)) or not p.is_file():
        raise HTTPException(status_code=404, detail=f"模板不存在：{path}")
    p.unlink()
    quality_storage.delete_template_object(path)
    return {"message": f"已删除 {path}"}


@router.post("/templates/bindings", summary="绑定/换绑 COA 模板 ↔ 标准文档（COA 唯一）")
async def upsert_template_binding(
    template_path: str = Body(..., embed=True),
    standard_document_id: uuid.UUID | None = Body(default=None, embed=True),
    sop_no: str | None = Body(default=None, embed=True),
    description: str | None = Body(default=None, embed=True),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:template:manage")),
) -> JSONResponse:
    if not quality_storage.ensure_template_local(template_path).is_file():
        raise HTTPException(status_code=404, detail=f"模板不存在：{template_path}")
    if standard_document_id:
        doc = await get_standard_document(db, standard_document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="标准文档不存在")
        sop_no = doc.file_no
    binding = await upsert_coa_binding(
        db, template_path=template_path,
        standard_document_id=standard_document_id, sop_no=sop_no, description=description,
    )
    return success_response(
        data={"template_path": binding.template_path, "sop_no": binding.sop_no,
              "standard_document_id": str(binding.standard_document_id) if binding.standard_document_id else None},
        message="模板绑定已保存",
    )


@router.delete("/templates/bindings/{template_path:path}", summary="解绑 COA 模板")
async def delete_template_binding(
    template_path: str, db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:template:manage")),
) -> JSONResponse:
    binding = await delete_coa_binding(db, template_path)
    if not binding:
        raise HTTPException(status_code=404, detail="绑定不存在")
    return success_response(message="已解绑")


@router.post("/templates/upload", summary="上传模板（自动按 COA 号匹配绑定 SOP）")
async def upload_template(
    folder: str = Form(""),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:template:manage")),
) -> dict[str, Any]:
    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx")
    # 文件名只取最后一段（去掉客户端路径成分，防 .. 穿越）
    filename = Path(file.filename).name
    dest = quality_storage.safe_join(REPORT_TEMPLATE_DIR, folder) if folder else REPORT_TEMPLATE_DIR
    if dest is None or (dest / filename).resolve().is_relative_to(dest.resolve()) is False:
        raise HTTPException(status_code=400, detail="非法路径")
    dest.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="超过5MB")
    saved = dest / filename
    saved.write_bytes(content)
    quality_storage.upload_template(saved)
    # 自动匹配：模板 COA 号 ↔ 编号相同的标准文档（唯一命中才自动建立 COA 侧绑定）
    rel_path = f"{folder}/{filename}" if folder else filename
    docs = await list_standard_documents(db)
    doc_tokens = {d.id: _extract_number_tokens(d.file_no or "", d.product_internal_code or "", d.product_code or "", d.version or "") for d in docs}
    matched = _match_template_to_doc(_template_number_tokens(saved), docs, doc_tokens)
    bound = False
    if matched:
        await upsert_coa_binding(
            db, template_path=rel_path,
            standard_document_id=matched.id, sop_no=matched.file_no,
        )
        bound = True
    return {
        "filename": filename,
        "folder": folder,
        "path": rel_path,
        "matched": _doc_match_info(matched),
        "bound": bound,
    }


@router.get("/templates/{path:path}/download", summary="下载模板")
async def download_template(
    path: str,
    _user: User = Depends(require_permission("quality:report:read")),
) -> FileResponse:
    full = quality_storage.ensure_template_local(path)
    if not full.is_file():
        raise HTTPException(status_code=404, detail="不存在")
    return FileResponse(
        str(full),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=full.name,
    )


@router.delete("/templates/{path:path}", summary="删除模板")
async def delete_template(
    path: str,
    _user: User = Depends(require_permission("quality:template:manage")),
) -> dict[str, Any]:
    full = quality_storage.safe_join(REPORT_TEMPLATE_DIR, path)
    if full is None or not full.is_file():
        raise HTTPException(status_code=404, detail="不存在")
    full.unlink()
    quality_storage.delete_template_object(path)
    return {"message": "已删除"}
