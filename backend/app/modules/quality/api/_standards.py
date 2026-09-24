"""standards API 路由（api.py 拆分）。"""

import uuid

from fastapi import (
    Body,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.quality.api._common import (
    router,
)
from app.modules.quality.models import QualityStandardDocument, QualityStandardItem
from app.modules.quality.repository import (
    create_standard_document,
    create_standard_item,
    delete_standard_document,
    list_standard_documents,
    list_standard_items,
    update_standard_document,
    update_standard_item,
)
from app.modules.quality.schemas import (
    StandardDocumentCreate,
    StandardDocumentUpdate,
    StandardImportConfirm,
    StandardItemCreate,
    StandardItemUpdate,
)
from app.modules.quality.standard_doc_parser import (
    extract_text_async,
    parse_standard_doc,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

# ─── 质量标准文档 / 项目行（SOP 号为匹配键）───


@router.post("/standards/import-doc/preview", summary="上传标准文档仅解析（弹窗确认前不落库）")
async def preview_standard_doc(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """解析 .doc/.docx 返回草稿：文档头 + 项目行；前端人工校正后调用 confirm 落库。"""
    filename = file.filename or "standard.doc"
    if not filename.lower().endswith((".doc", ".docx")):
        raise HTTPException(status_code=400, detail="仅支持 .doc / .docx 格式")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        text = await extract_text_async(content, filename)
    except Exception:
        raise HTTPException(status_code=500, detail="文档文本提取失败")
    if not text.strip():
        raise HTTPException(status_code=400, detail="未能从文档中提取文本")

    parsed = parse_standard_doc(text)
    if not parsed.product_name and not parsed.file_no:
        raise HTTPException(status_code=400, detail="解析失败：未识别出标准文件头信息")
    existing = None
    if parsed.file_no:
        ex = (await db.execute(
            select(QualityStandardDocument).where(
                QualityStandardDocument.file_no == parsed.file_no,
                QualityStandardDocument.is_deleted == False,  # noqa: E712
            )
        )).scalars().first()
        if ex:
            existing = {"id": str(ex.id), "product_name": ex.product_name}
    draft = {
        "document": {
            "file_no": parsed.file_no or filename,
            "product_name": parsed.product_name or filename,
            "product_code": parsed.product_code,
            "product_internal_code": parsed.product_internal_code,
            "specification": parsed.specification,
            "valid_years": parsed.valid_years,
            "effective_date": parsed.effective_date,
            "version": parsed.version,
        },
        "items": [
            {
                "seq": it.seq,
                "category": it.category,
                "item_name": it.item_name,
                "sop_no": it.sop_no,
                "standard_text": it.standard_text,
                "operator": it.operator,
                "limit_min": it.limit_min,
                "limit_max": it.limit_max,
                "method_source": it.method_source,
                "remark": it.remark,
            }
            for it in parsed.items
        ],
        "existing": existing,
    }
    msg = f"解析完成：{len(parsed.items)} 个项目行，请核对修改后确认导入"
    if existing:
        msg = f"⚠ 该文件编号已导入（产品：{existing['product_name']}）——确认后将覆盖更新（替换文档头与项目行，绑定模板保留）"
    return success_response(data=draft, message=msg)


@router.post("/standards/import-doc/confirm", summary="确认导入标准文档（人工校正后落库）")
async def confirm_standard_doc(
    payload: StandardImportConfirm = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    doc_data = payload.document
    existing = (await db.execute(
        select(QualityStandardDocument).where(
            QualityStandardDocument.file_no == doc_data.file_no,
            QualityStandardDocument.is_deleted == False,  # noqa: E712
        )
    )).scalars().first()
    overwritten = False
    if existing:
        # 升级覆盖：同一文件编号视为新版——更新文档头、替换全部项目行，
        # 保留文档 ID 与绑定模板（任务快照引用不断）
        await update_standard_document(
            db, existing.id, **{k: v for k, v in doc_data.model_dump().items() if v is not None}
        )
        doc = existing
        overwritten = True
    else:
        doc = await create_standard_document(db, doc_data.model_dump())
    # 覆盖导入时按 (sop_no, item_name) 复用旧行 ID：历史任务的 standard_item_id
    # 引用不断裂（此前整批软删+重建，旧任务逐份 COA 归属静默错乱）
    reused_items: dict[tuple[str, str], QualityStandardItem] = {}
    if overwritten:
        for item in await list_standard_items(db, doc.id):
            reused_items[(item.sop_no or "", item.item_name)] = item
    created = 0
    reused = 0
    skipped = 0
    seen: set[tuple[str, str]] = set()
    for it in payload.items:
        key = (it.sop_no or "", it.item_name)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        data = it.model_dump()
        if not data.get("standard_text"):
            data["standard_text"] = ""
        old = reused_items.get(key)
        if old is not None:
            try:
                async with db.begin_nested():
                    await update_standard_item(db, old.id, **data)
                reused += 1
            except Exception:
                skipped += 1
            continue
        try:
            # 每条独立保存点：单条失败不污染整个事务
            async with db.begin_nested():
                await create_standard_item(db, doc.id, data)
            created += 1
        except Exception:
            skipped += 1
    if overwritten:
        # 新版中已删除的项目行软删（保留 ID 不复用，历史快照仍可追溯）
        for key, prev_item in reused_items.items():
            if key not in seen:
                prev_item.is_deleted = True
        await db.flush()
    verb = "覆盖更新完成" if overwritten else "确认导入完成"
    msg = f"{verb}：新增 {created} 条、复用 {reused} 条" + (f"，{skipped} 条重复或异常跳过" if skipped else "")
    return success_response(
        data={
            "id": str(doc.id),
            "file_no": doc.file_no,
            "created_items": created,
            "reused_items": reused,
            "skipped_items": skipped,
            "overwritten": overwritten,
        },
        message=msg,
        status_code=201,
    )


@router.post("/standards/import-doc", summary="上传标准文档解析导入")
async def import_standard_doc(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    """上传 .doc/.docx 质量标准文件：解析文件头+项目行。

    数值标准结构化（operator/limit），纯文字标准保留（operator/limit 为空，人工判定）。
    返回解析草稿与落库结果，前端可继续在明细表格中校正。
    """
    filename = file.filename or "standard.doc"
    if not filename.lower().endswith((".doc", ".docx")):
        raise HTTPException(status_code=400, detail="仅支持 .doc / .docx 格式")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        text = await extract_text_async(content, filename)
    except Exception:
        raise HTTPException(status_code=500, detail="文档文本提取失败")
    if not text.strip():
        raise HTTPException(status_code=400, detail="未能从文档中提取文本")

    parsed = parse_standard_doc(text)
    if not parsed.product_name and not parsed.file_no:
        raise HTTPException(status_code=400, detail="解析失败：未识别出标准文件头信息")
    # 重复导入拦截：同文件编号已存在时友好提示（避免唯一约束 500）
    if parsed.file_no:
        existing = (await db.execute(
            select(QualityStandardDocument).where(
                QualityStandardDocument.file_no == parsed.file_no,
                QualityStandardDocument.is_deleted == False,  # noqa: E712
            )
        )).scalars().first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"该文件编号已导入（产品：{existing.product_name}），如需更新请先删除后重新导入",
            )

    doc = await create_standard_document(db, {
        "file_no": parsed.file_no or filename,
        "product_name": parsed.product_name or filename,
        "product_code": parsed.product_code,
        "product_internal_code": parsed.product_internal_code,
        "specification": parsed.specification,
        "valid_years": parsed.valid_years,
        "effective_date": parsed.effective_date,
        "version": parsed.version,
    })
    created = 0
    skipped = 0
    for it in parsed.items:
        try:
            # 每条独立保存点：单条失败（重复等）不污染整个事务，文档头与其余行正常落库
            async with db.begin_nested():
                await create_standard_item(db, doc.id, {
                    "seq": it.seq,
                    "category": it.category,
                    "item_name": it.item_name,
                    "sop_no": it.sop_no,
                    "standard_text": it.standard_text,
                    "operator": it.operator,
                    "limit_min": it.limit_min,
                    "limit_max": it.limit_max,
                    "method_source": it.method_source,
                    "remark": it.remark,
                })
            created += 1
        except Exception:
            skipped += 1
    msg = f"解析导入完成：{created}/{len(parsed.items)} 条标准行（含文字标准，人工判定）"
    if skipped:
        msg += f"，{skipped} 条因重复或异常跳过"
    return success_response(
        data={
            "id": str(doc.id),
            "file_no": doc.file_no,
            "product_name": doc.product_name,
            "created_items": created,
            "parsed_items": len(parsed.items),
            "skipped_items": skipped,
        },
        message=msg,
        status_code=201,
    )


@router.get("/standards/documents", summary="质量标准文档列表")
async def list_standard_docs(
    product_name: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    docs = await list_standard_documents(db, product_name=product_name)
    return success_response(data=[
        {
            "id": str(d.id),
            "file_no": d.file_no,
            "product_name": d.product_name,
            "product_code": d.product_code,
            "product_internal_code": d.product_internal_code,
            "specification": d.specification,
            "valid_years": d.valid_years,
            "effective_date": d.effective_date,
            "version": d.version,
            "template_path": d.template_path,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ])


@router.post("/standards/documents", summary="创建质量标准文档")
async def create_standard_doc(
    payload: StandardDocumentCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    doc = await create_standard_document(db, payload.model_dump())
    return success_response(data={"id": str(doc.id)}, message="标准文档创建成功", status_code=201)


@router.put("/standards/documents/{doc_id}", summary="更新质量标准文档")
async def update_standard_doc(
    doc_id: uuid.UUID,
    payload: StandardDocumentUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    doc = await update_standard_document(db, doc_id, **updates)
    if not doc:
        raise HTTPException(status_code=404, detail="标准文档不存在")
    return success_response(message="已更新")


@router.delete("/standards/documents/{doc_id}", summary="删除质量标准文档")
async def delete_standard_doc(
    doc_id: uuid.UUID, db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    doc = await delete_standard_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="标准文档不存在")
    return success_response(message="已删除")


@router.get("/standards/documents/{doc_id}/items", summary="标准项目行列表")
async def list_standard_doc_items(
    doc_id: uuid.UUID, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items = await list_standard_items(db, doc_id)
    return success_response(data=[
        {
            "id": str(it.id),
            "seq": it.seq,
            "category": it.category,
            "item_name": it.item_name,
            "sop_no": it.sop_no,
            "standard_text": it.standard_text,
            "operator": it.operator,
            "limit_min": it.limit_min,
            "limit_max": it.limit_max,
            "method_source": it.method_source,
            "remark": it.remark,
        }
        for it in items
    ])


@router.post("/standards/documents/{doc_id}/items", summary="新增标准项目行")
async def create_standard_doc_item(
    doc_id: uuid.UUID,
    payload: StandardItemCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    it = await create_standard_item(db, doc_id, payload.model_dump())
    return success_response(data={"id": str(it.id)}, message="已添加", status_code=201)


@router.put("/standards/items/{item_id}", summary="更新标准项目行")
async def update_standard_doc_item(
    item_id: uuid.UUID,
    payload: StandardItemUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    it = await update_standard_item(db, item_id, **updates)
    if not it:
        raise HTTPException(status_code=404, detail="标准行不存在")
    return success_response(message="已更新")
