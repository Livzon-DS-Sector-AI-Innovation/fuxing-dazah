"""Quality 模块 API 路由。"""

import re
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path

from docx import Document
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.quality.report_generator import extract_template_placeholders
from app.modules.quality.repository import (
    create_category,
    create_document,
    create_product_standard,
    create_report_record,
    delete_category,
    delete_document,
    delete_inspection_record,
    delete_product_standard,
    get_document,
    get_product_names,
    get_report_record,
    get_summary_by_product,
    list_document_categories,
    list_documents,
    list_inspection_records,
    list_product_standards,
    list_report_records,
    update_product_standard,
)
from app.modules.quality.schemas import (
    GenerateReportRequest,
    InspectionRecordListItem,
    ProductStandardCreate,
    ProductStandardUpdate,
    UploadLcResponse,
)
from app.modules.quality.service import lc_report_service
from app.shared.module_registry import MODULES_BY_CODE

router = APIRouter()
_module = MODULES_BY_CODE["quality"]
REPORT_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "报告模板"
PLACEHOLDER_RE = re.compile(r"\{\{(.+?)\}\}")


@router.get("/", summary=f"{_module.name}模块信息")
async def read_module() -> dict[str, str]:
    return _module.as_dict()


# ─── 液相解析上传 ───


@router.post("/lc/upload", response_model=UploadLcResponse, summary="上传液相计算表并解析")
async def upload_lc_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    filename = file.filename or "unknown.xlsx"
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 或 .xls")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 10MB")
    try:
        return await lc_report_service.parse_and_validate(file_bytes, filename, db=db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"无法解析：{e}") from e


# ─── 检验记录查询 ───


@router.get("/lc/records", summary="分页查询液相解析历史记录")
async def list_lc_records(
    product_name: str | None = Query(default=None, description="产品名称（模糊搜索）"),
    batch_number: str | None = Query(default=None, description="批号（模糊搜索）"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await list_inspection_records(
        db, product_name=product_name, batch_number=batch_number,
        page=page, page_size=page_size,
    )
    return paginated_response(
        data=[
            InspectionRecordListItem(
                id=it.id,
                product_name=it.product_name,
                batch_number=it.batch_number,
                form_id=it.form_id,
                standard_type=it.standard_type,
                all_pass=it.all_pass,
                has_oot=it.has_oot,
                excel_filename=it.excel_filename,
                created_at=it.created_at,
            ).model_dump(mode="json")
            for it in items
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/lc/records/{record_id}", summary="查询单条检验记录详情（含杂质明细）")
async def get_lc_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await lc_report_service.get_record_detail(db, record_id)
    if not detail:
        raise HTTPException(status_code=404, detail="检验记录不存在")
    return success_response(data=detail.model_dump(mode="json"))


@router.delete("/lc/records/{record_id}", summary="删除检验记录（软删除）")
async def delete_lc_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await delete_inspection_record(db, record_id)
    if not result:
        raise HTTPException(status_code=404, detail="检验记录不存在")
    return success_response(message="已删除")


# ─── 模板管理 ───


def _scan_templates(root: Path) -> list[dict]:
    items = []
    for p in sorted(root.iterdir()):
        if p.is_dir():
            items.append({"type": "folder", "name": p.name, "children": _scan_templates(p)})
        elif p.suffix == ".docx":
            phs = extract_template_placeholders(str(p))
            st = p.stat()
            items.append({
                "type": "template",
                "filename": p.name,
                "size_kb": round(st.st_size / 1024, 1),
                "modified": st.st_mtime,
                "placeholder_count": len(phs),
                "placeholders": [
                    {"name": ph.name, "decimals": ph.decimals, "suffix": ph.suffix}
                    for ph in phs
                ],
            })
    return items


@router.get("/templates", summary="列出模板")
async def list_templates():
    return _scan_templates(REPORT_TEMPLATE_DIR) if REPORT_TEMPLATE_DIR.exists() else []


@router.get("/templates/all-placeholders", summary="获取所有模板的所有占位符名称")
async def all_placeholders():
    names: set[str] = set()

    def walk(items: list[dict]):
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
async def create_folder(name: str = Body(..., embed=True)):
    (REPORT_TEMPLATE_DIR / name).mkdir(parents=True, exist_ok=True)
    return {"name": name}


@router.delete("/templates/folders", summary="删除空文件夹")
async def delete_folder(name: str = Body(..., embed=True)):
    p = REPORT_TEMPLATE_DIR / name
    if not p.exists():
        raise HTTPException(status_code=404, detail="不存在")
    try:
        p.rmdir()
    except OSError:
        raise HTTPException(status_code=400, detail="文件夹不为空") from None
    return {"message": f"已删除 {name}"}


@router.post("/templates/upload", summary="上传模板")
async def upload_template(folder: str = Form(""), file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx")
    dest = REPORT_TEMPLATE_DIR / folder
    dest.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="超过5MB")
    (dest / file.filename).write_bytes(content)
    return {"filename": file.filename, "folder": folder}


@router.get("/templates/{path:path}/download", summary="下载模板")
async def download_template(path: str):
    full = REPORT_TEMPLATE_DIR / path
    if not full.exists():
        raise HTTPException(status_code=404, detail="不存在")
    return FileResponse(
        str(full),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=full.name,
    )


@router.delete("/templates/{path:path}", summary="删除模板")
async def delete_template(path: str):
    full = REPORT_TEMPLATE_DIR / path
    if not full.exists():
        raise HTTPException(status_code=404, detail="不存在")
    full.unlink()
    return {"message": "已删除"}


# ─── 产品代码管理 ───

PRODUCTS_FILE = REPORT_TEMPLATE_DIR.parent / "products.json"


def _load_products() -> list[dict]:
    import json

    if PRODUCTS_FILE.exists():
        try:
            return json.loads(PRODUCTS_FILE.read_text())
        except Exception:
            pass
    return []


def _save_products(data: list[dict]):
    import json

    PRODUCTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


@router.get("/products", summary="列出产品代码映射")
async def list_products():
    return _load_products()


@router.post("/products", summary="保存产品代码映射")
async def save_products(data: list[dict] = Body(...)):
    _save_products(data)
    return {"message": "已保存", "count": len(data)}


# ─── 报告生成 ───


def _replace_placeholders(para, data: dict):
    full = para.text
    matches = list(PLACEHOLDER_RE.finditer(full))
    if not matches:
        return
    new_text = full
    for m in reversed(matches):
        raw = m.group(1).strip()
        key = raw.split("|")[0].strip()
        val = str(data.get(key, "-"))
        new_text = new_text[: m.start()] + val + new_text[m.end() :]
    if para.runs:
        para.runs[0].text = new_text
        for r in para.runs[1:]:
            r.text = ""


@router.post("/report/generate", summary="生成报告单")
async def generate_report(
    payload: GenerateReportRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    tp = REPORT_TEMPLATE_DIR / payload.template
    if not tp.exists():
        raise HTTPException(status_code=404, detail=f"模板不存在：{payload.template}")

    # 获取填充数据
    fill_data: dict = {}
    product_name = ""
    batch_number = ""
    record_id: uuid.UUID | None = None

    if payload.inspection_record_id:
        # 从数据库加载检验记录自动填充
        detail = await lc_report_service.get_record_detail(db, payload.inspection_record_id)
        if not detail:
            raise HTTPException(status_code=404, detail="检验记录不存在")
        fill_data = lc_report_service.build_report_data(detail.report)
        product_name = detail.product_name
        batch_number = detail.batch_number
        record_id = detail.id
    elif payload.data:
        fill_data = payload.data
        product_name = fill_data.get("产品名称", "")
        batch_number = fill_data.get("批号", "")
    else:
        raise HTTPException(status_code=400, detail="请提供 inspection_record_id 或 data")

    # 填充模板
    doc = Document(str(tp))
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    _replace_placeholders(para, fill_data)
    for para in doc.paragraphs:
        _replace_placeholders(para, fill_data)

    # 保存到临时文件
    output_dir = REPORT_TEMPLATE_DIR / "_generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_batch = batch_number.replace("/", "_").replace("\\", "_")
    output_filename = f"COA-{product_name}-{safe_batch}.docx"
    output_path = output_dir / output_filename
    doc.save(str(output_path))
    file_size = output_path.stat().st_size

    # 保存报告单记录到数据库
    if record_id:
        await create_report_record(
            db=db,
            inspection_record_id=record_id,
            template_path=payload.template,
            product_name=product_name,
            batch_number=batch_number,
            file_path=str(output_path),
            file_size=file_size,
        )

    # 返回文件
    out = BytesIO()
    doc.save(out)
    out.seek(0)
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename={output_filename}"
        },
    )


# ─── 报告单记录 ───


@router.get("/report/records", summary="报告单历史列表")
async def list_reports(
    product_name: str | None = Query(default=None),
    batch_number: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await list_report_records(
        db, product_name=product_name, batch_number=batch_number,
        page=page, page_size=page_size,
    )
    return paginated_response(
        data=[
            {
                "id": str(it.id),
                "inspection_record_id": str(it.inspection_record_id),
                "template_path": it.template_path,
                "product_name": it.product_name,
                "batch_number": it.batch_number,
                "file_path": it.file_path,
                "file_size": it.file_size,
                "created_at": it.created_at.isoformat() if it.created_at else None,
            }
            for it in items
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/report/records/{report_id}/download", summary="下载已生成的报告单")
async def download_report(report_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    report = await get_report_record(db, report_id)
    if not report or not report.file_path:
        raise HTTPException(status_code=404, detail="报告文件不存在")
    fp = Path(report.file_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="报告文件已被清理")
    return FileResponse(
        str(fp),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=fp.name,
    )


# ─── 汇总表 ───


@router.get("/summary/batch/{record_id}", summary="单批次汇总")
async def batch_summary(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await lc_report_service.get_record_detail(db, record_id)
    if not detail:
        raise HTTPException(status_code=404, detail="检验记录不存在")

    # 生成文字化判定摘要
    lines = [
        f"产品：{detail.product_name}",
        f"批号：{detail.batch_number}",
        f"标准：{detail.standard_type or '-'}",
        f"总体判定：{'合格' if detail.all_pass else '不合格'}",
        f"超趋势：{'是' if detail.has_oot else '否'}",
        f"杂质项目数：{len(detail.impurities)}",
    ]
    if detail.report.vancomycin_b:
        vb = detail.report.vancomycin_b
        lines.append(
            f"万古霉素B：{vb.rounded_first} (判定：{'合格' if vb.is_pass else '不合格'})"
        )
    if detail.report.total_impurities:
        ti = detail.report.total_impurities
        lines.append(
            f"总杂质：{ti.rounded_first} (判定：{'合格' if ti.is_pass else '不合格'})"
        )

    return success_response(
        data={
            "record": detail.model_dump(mode="json"),
            "summary_text": "\n".join(lines),
        }
    )


@router.get("/summary/history", summary="多批次历史汇总")
async def history_summary(
    product_name: str | None = Query(default=None, description="产品名称"),
    date_from: str | None = Query(default=None, description="起始日期 ISO 格式"),
    date_to: str | None = Query(default=None, description="结束日期 ISO 格式"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    dt_from = datetime.fromisoformat(date_from) if date_from else None
    dt_to = datetime.fromisoformat(date_to) if date_to else None

    summary = await get_summary_by_product(
        db, product_name=product_name, date_from=dt_from, date_to=dt_to
    )
    return success_response(data=summary)


@router.get("/summary/products", summary="已检验产品列表")
async def list_summary_products(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    names = await get_product_names(db)
    return success_response(data=names)


# ─── 产品标准配置管理 ───


@router.get("/standards", summary="查询产品标准配置列表")
async def list_standards(
    product_name: str | None = Query(default=None, description="产品名称过滤"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items = await list_product_standards(db, product_name=product_name)
    return success_response(data=[
        {
            "id": str(it.id),
            "product_name": it.product_name,
            "item_name": it.item_name,
            "standard_type": it.standard_type,
            "operator": it.operator,
            "limit_value": it.limit_value,
            "oot_haf": it.oot_haf,
            "oot_haa": it.oot_haa,
            "created_at": it.created_at.isoformat() if it.created_at else None,
            "updated_at": it.updated_at.isoformat() if it.updated_at else None,
        }
        for it in items
    ])


@router.post("/standards", summary="新增产品标准配置")
async def create_standard(
    payload: ProductStandardCreate = Body(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    std = await create_product_standard(
        db,
        product_name=payload.product_name,
        item_name=payload.item_name,
        standard_type=payload.standard_type,
        operator=payload.operator,
        limit_value=payload.limit_value,
        oot_haf=payload.oot_haf,
        oot_haa=payload.oot_haa,
    )
    return success_response(data={
        "id": str(std.id),
        "product_name": std.product_name,
        "item_name": std.item_name,
    })


@router.put("/standards/{standard_id}", summary="更新产品标准配置")
async def update_standard(
    standard_id: uuid.UUID,
    payload: ProductStandardUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    std = await update_product_standard(db, standard_id, **updates)
    if not std:
        raise HTTPException(status_code=404, detail="标准配置不存在")
    return success_response(message="已更新")


@router.delete("/standards/{standard_id}", summary="删除产品标准配置")
async def delete_standard(
    standard_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    std = await delete_product_standard(db, standard_id)
    if not std:
        raise HTTPException(status_code=404, detail="标准配置不存在")
    return success_response(message="已删除")


@router.post("/standards/upload", summary="批量导入产品标准配置（Excel）")
async def upload_standards(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """上传 Excel 文件批量导入产品标准配置。

    表头：产品名称 | 指标名称 | 标准类型 | 运算符 | 限度值 | OOT(HAF) | OOT(HAA)
    标准类型和运算符可选，默认分别为空和 ≤。
    """
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 或 .xls 格式")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="文件为空")

    import openpyxl
    wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    ws = wb.active if wb.active else wb[wb.sheetnames[0]]

    created = 0
    skipped = 0
    errors: list[str] = []

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not row[0]:
            continue  # 跳过空行

        product_name = str(row[0]).strip() if row[0] else ""
        item_name = str(row[1]).strip() if len(row) > 1 and row[1] else ""

        if not product_name or not item_name:
            errors.append(f"第{row_idx}行：产品名称或指标名称为空，跳过")
            skipped += 1
            continue

        standard_type = str(row[2]).strip() if len(row) > 2 and row[2] else None
        operator = str(row[3]).strip() if len(row) > 3 and row[3] else "≤"

        def _safe_float(val) -> float | None:
            if val is None:
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        limit_value = _safe_float(row[4]) if len(row) > 4 else None
        oot_haf = _safe_float(row[5]) if len(row) > 5 else None
        oot_haa = _safe_float(row[6]) if len(row) > 6 else None

        try:
            await create_product_standard(
                db,
                product_name=product_name,
                item_name=item_name,
                standard_type=standard_type,
                operator=operator,
                limit_value=limit_value,
                oot_haf=oot_haf,
                oot_haa=oot_haa,
            )
            created += 1
        except Exception:
            errors.append(f"第{row_idx}行：{product_name}/{item_name} 创建失败（可能已存在）")
            skipped += 1

    return success_response(data={
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "total": created + skipped,
    })


# ─── 标准文档库 ───

DOCS_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "标准文件库"


@router.get("/docs/categories", summary="列出文档大类")
async def list_categories(
    product_name: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    cats = await list_document_categories(db, product_name=product_name)
    return success_response(data=[
        {"id": str(c.id), "product_name": c.product_name, "category_name": c.category_name}
        for c in cats
    ])


@router.post("/docs/categories", summary="创建文档大类")
async def create_doc_category(
    product_name: str = Body(...),
    category_name: str = Body(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    cat = await create_category(db, product_name, category_name)
    return success_response(data={"id": str(cat.id)})


@router.delete("/docs/categories/{category_id}", summary="删除文档大类")
async def delete_doc_category(
    category_id: uuid.UUID, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    cat = await delete_category(db, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="大类不存在")
    return success_response(message="已删除")


@router.get("/docs/categories/{category_id}/files", summary="列出某大类下的文件")
async def list_docs(
    category_id: uuid.UUID, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    docs = await list_documents(db, category_id)
    return success_response(data=[
        {"id": str(d.id), "original_filename": d.original_filename,
         "file_size": d.file_size, "created_at": d.created_at.isoformat() if d.created_at else None}
        for d in docs
    ])


@router.post("/docs/upload", summary="上传标准文档")
async def upload_document(
    category_id: uuid.UUID = Form(...),
    product_name: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    dest = DOCS_STORAGE_DIR / product_name / str(category_id)
    dest.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4()}{Path(file.filename or 'unknown').suffix}"
    file_path = dest / stored_name
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    file_path.write_bytes(content)

    doc = await create_document(
        db, category_id=category_id, product_name=product_name,
        original_filename=file.filename or "unknown",
        file_path=str(file_path), file_size=len(content),
    )
    return success_response(data={"id": str(doc.id), "original_filename": doc.original_filename})


@router.get("/docs/{doc_id}/download", summary="下载标准文档")
async def download_document(
    doc_id: uuid.UUID, db: AsyncSession = Depends(get_db),
):
    doc = await get_document(db, doc_id)
    if not doc or not doc.file_path:
        raise HTTPException(status_code=404, detail="文件不存在")
    fp = Path(doc.file_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="文件已被清理")
    return FileResponse(str(fp), filename=doc.original_filename)


@router.delete("/docs/{doc_id}", summary="删除标准文档")
async def delete_doc(
    doc_id: uuid.UUID, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    doc = await delete_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文件不存在")
    return success_response(message="已删除")
