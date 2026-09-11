"""Quality 模块 API 路由。"""

import re
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.quality import storage as quality_storage
from app.modules.quality.models import QualityStandardDocument
from app.modules.quality.report_generator import (
    extract_template_placeholders,
    format_value,
    parse_placeholder,
    resolve_placeholders,
)
from app.modules.quality.repository import (
    create_report_record,
    create_standard_document,
    create_standard_item,
    delete_coa_binding,
    delete_inspection_record,
    delete_standard_document,
    delete_standard_item,
    get_product_names,
    get_report_record,
    get_standard_document,
    get_summary_by_product,
    get_test_task_by_batch,
    list_coa_bindings,
    list_inspection_records,
    list_report_records,
    list_standard_documents,
    list_standard_items,
    list_unqualified_events,
    update_standard_document,
    update_standard_item,
    upsert_coa_binding,
)
from app.modules.quality.schemas import (
    GenerateReportRequest,
    InspectionRecordListItem,
    LcReportOut,
    StandardDocumentCreate,
    StandardDocumentUpdate,
    StandardImportConfirm,
    StandardItemCreate,
    StandardItemUpdate,
    TaskReportGenerateRequest,
    TestResultCreate,
    TestResultsUpdate,
    TestTaskCreate,
    TestTaskReportDateUpdate,
    TestTaskStatusUpdate,
    UploadLcResponse,
)
from app.modules.quality.service import lc_report_service, test_task_service
from app.modules.quality.standard_doc_parser import (
    extract_text_async,
    parse_standard_doc,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission
from app.shared.module_registry import MODULES_BY_CODE

router = APIRouter()
_module = MODULES_BY_CODE["quality"]
REPORT_TEMPLATE_DIR = quality_storage.REPORT_TEMPLATE_DIR
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
        # 优先模板配置驱动的通用解析（表号识别）；无匹配配置回落到旧解析器
        generic = await test_task_service.parse_lc_generic(db, file_bytes, filename)
        if generic is not None:
            parsed = generic["parse"]
            result = UploadLcResponse(
                filename=filename,
                report=LcReportOut(
                    product_name=parsed.product_name,
                    batch_number=parsed.batch_number,
                    form_id=parsed.form_id,
                ),
                record_id=generic["record_id"],
                task_link=generic["task_link"],
                components=[
                    {"name": c.name, "first": c.first, "second": c.second, "report_value": c.report_value}
                    for c in parsed.components
                ],
            )
            return result
        result = await lc_report_service.parse_and_validate(file_bytes, filename, db=db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"无法解析：{e}") from e
    # 自动关联已建检验任务：按产品+批号定位，按 SOP/项目名映射填入
    if result.record_id:
        task = await get_test_task_by_batch(db, result.report.product_name, result.report.batch_number)
        if task and task.status == "in_progress":
            filled, unmatched = await test_task_service.fill_task_from_report(
                db, task, result.report, result.record_id
            )
            result.task_link = {
                "task_id": str(task.id),
                "filled": filled,
                "unmatched": unmatched,
            }
    return result


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


def _scan_templates(root: Path, prefix: str = "") -> list[dict]:
    items = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and p.name == "_generated":
            continue  # 生成输出目录，不参与模板扫描
        rel = f"{prefix}/{p.name}" if prefix else p.name
        if p.is_dir():
            items.append({"type": "folder", "name": p.name, "children": _scan_templates(p, rel)})
        elif p.suffix == ".docx":
            phs = extract_template_placeholders(str(p))
            st = p.stat()
            items.append({
                "type": "template",
                "filename": p.name,
                "path": rel,
                "size_kb": round(st.st_size / 1024, 1),
                "modified": st.st_mtime,
                "placeholder_count": len(phs),
                "placeholders": [
                    {"name": ph.name, "decimals": ph.decimals, "suffix": ph.suffix}
                    for ph in phs
                ],
            })
    return items


# ─── 模板 COA 号 ↔ 标准文档号码匹配 ───

_TEMPLATE_TOKEN_RE = re.compile(r"SOP\.\d{2}\.\d{3,4}(?:\.\d{3})?|EX-[A-Z]+-\d+-\d+", re.IGNORECASE)


def _extract_number_tokens(*texts: str) -> list[str]:
    """提取文本中的号码片段（SOP 号、EX 表号、4-6 位数字）。"""
    tokens: list[str] = []
    for t in texts:
        if not t:
            continue
        for m in _TEMPLATE_TOKEN_RE.findall(t):
            tokens.append(m.upper())
        for m in re.findall(r"\d{4,6}", t):
            tokens.append(m)
    return tokens


def _template_number_tokens(path: Path) -> list[str]:
    """模板号码 token：文件名 + 文档内容（COA 号通常写在表头）。"""
    tokens = _extract_number_tokens(path.stem)
    try:
        doc = Document(str(path))
        texts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    texts.append(cell.text)
        tokens += _extract_number_tokens(*texts)
    except Exception:
        pass
    return tokens


def _score_tokens(a: list[str], b: list[str]) -> int:
    score = 0
    for x in a:
        for y in b:
            if x == y:
                score += 10
            elif len(x) >= 3 and len(y) >= 3 and (x in y or y in x):
                score += 3
    return score


def _match_template_to_doc(
    tp_tokens: list[str],
    docs: list[QualityStandardDocument],
    doc_tokens: dict[uuid.UUID, list[str]],
) -> QualityStandardDocument | None:
    """模板号码与标准文档号码匹配：唯一最高分且 >0 返回文档，平手或零分返回 None。"""
    if not tp_tokens:
        return None
    scored = sorted(
        ((d, _score_tokens(tp_tokens, doc_tokens[d.id])) for d in docs if _score_tokens(tp_tokens, doc_tokens[d.id]) > 0),
        key=lambda x: -x[1],
    )
    if not scored:
        return None
    if len(scored) > 1 and scored[0][1] == scored[1][1]:
        return None  # 平手不自动绑定，留人工判断
    return scored[0][0]


def _doc_match_info(d: QualityStandardDocument | None) -> dict | None:
    if not d:
        return None
    return {"doc_id": str(d.id), "file_no": d.file_no, "product_code": d.product_code or ""}


@router.get("/templates", summary="列出模板（含 SOP 绑定状态）")
async def list_templates(db: AsyncSession = Depends(get_db)):
    quality_storage.sync_templates_from_minio()
    items = _scan_templates(REPORT_TEMPLATE_DIR) if REPORT_TEMPLATE_DIR.exists() else []
    # 一次性加载全部标准文档的号码 token（未绑定模板的匹配建议）
    docs = await list_standard_documents(db)
    doc_tokens = {d.id: _extract_number_tokens(d.file_no or "", d.product_internal_code or "", d.product_code or "", d.version or "") for d in docs}
    bindings = {b.template_path: b for b in await list_coa_bindings(db)}

    def annotate(nodes: list[dict]) -> None:
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


@router.delete("/templates/file", summary="删除单个模板文件")
async def delete_template_file(path: str = Body(..., embed=True)):
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
):
    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx")
    dest = REPORT_TEMPLATE_DIR / folder
    dest.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="超过5MB")
    saved = dest / file.filename
    saved.write_bytes(content)
    quality_storage.upload_template(saved)
    # 自动匹配：模板 COA 号 ↔ 编号相同的标准文档（唯一命中才自动建立 COA 侧绑定）
    rel_path = f"{folder}/{file.filename}" if folder else file.filename
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
        "filename": file.filename,
        "folder": folder,
        "path": rel_path,
        "matched": _doc_match_info(matched),
        "bound": bound,
    }


@router.get("/templates/{path:path}/download", summary="下载模板")
async def download_template(path: str):
    full = quality_storage.ensure_template_local(path)
    if not full.is_file():
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
    quality_storage.delete_template_object(path)
    return {"message": "已删除"}


# ─── 产品代码管理 ───

PRODUCTS_FILE = REPORT_TEMPLATE_DIR.parent / "products.json"


def _load_products() -> list[dict]:
    import json

    # MinIO 兜底：本地丢失时从对象恢复
    if not PRODUCTS_FILE.exists():
        data = quality_storage.read_products_from_minio()
        if data:
            PRODUCTS_FILE.write_bytes(data)
    if PRODUCTS_FILE.exists():
        try:
            return json.loads(PRODUCTS_FILE.read_text())
        except Exception:
            pass
    return []


def _save_products(data: list[dict]):
    import json

    PRODUCTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    quality_storage.upload_products(PRODUCTS_FILE.read_bytes())


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
        spec = parse_placeholder(raw)
        val = data.get(spec.name)
        text = format_value(val, spec) if val not in (None, "") else "-"
        new_text = new_text[: m.start()] + text + new_text[m.end() :]
    if para.runs:
        para.runs[0].text = new_text
        for r in para.runs[1:]:
            r.text = ""


def _render_cao_file(
    tp: Path, fill_data: dict, product_name: str, batch_number: str, suffix: str = ""
) -> tuple[Path, str, bytes]:
    """填充模板并落盘到 _generated 目录，返回 (输出路径, 文件名, 文件内容)。

    suffix 用于逐份生成时区分标准文件（文件名追加文件编号）。
    """
    tp = quality_storage.ensure_template_local(tp.relative_to(REPORT_TEMPLATE_DIR).as_posix())
    doc = Document(str(tp))
    # 收集模板全部占位符名，做双向解析（简写/编号变体兜底命中数据键）
    names: set[str] = set()
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for m in PLACEHOLDER_RE.finditer(para.text):
                        names.add(parse_placeholder(m.group(1).strip()).name)
    for para in doc.paragraphs:
        for m in PLACEHOLDER_RE.finditer(para.text):
            names.add(parse_placeholder(m.group(1).strip()).name)
    fill_data = resolve_placeholders(fill_data, list(names))
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    _replace_placeholders(para, fill_data)
    for para in doc.paragraphs:
        _replace_placeholders(para, fill_data)

    output_dir = REPORT_TEMPLATE_DIR / "_generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_batch = batch_number.replace("/", "_").replace("\\", "_")
    safe_suffix = suffix.replace("/", "_").replace("\\", "_")
    output_filename = f"COA-{product_name}-{safe_batch}" + (f"-{safe_suffix}" if safe_suffix else "") + ".docx"
    output_path = output_dir / output_filename
    doc.save(str(output_path))
    quality_storage.upload_report(output_path)
    return output_path, output_filename, output_path.read_bytes()


def _coa_response(output_filename: str, content: bytes) -> StreamingResponse:
    """中文文件名用 RFC 5987 filename* 编码（latin-1 头编不了中文）。"""
    encoded = quote(output_filename)
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"coa.docx\"; filename*=UTF-8''{encoded}"
        },
    )


@router.post("/report/generate", summary="生成报告单")
async def generate_report(
    payload: GenerateReportRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:report:generate")),
):
    tp = REPORT_TEMPLATE_DIR / payload.template
    if not quality_storage.ensure_template_local(payload.template).is_file():
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

    output_path, output_filename, content = _render_cao_file(
        tp, fill_data, product_name, batch_number
    )

    # 保存报告单记录到数据库
    if record_id:
        await create_report_record(
            db=db,
            inspection_record_id=record_id,
            template_path=payload.template,
            product_name=product_name,
            batch_number=batch_number,
            file_path=str(output_path),
            file_size=output_path.stat().st_size,
        )

    return _coa_response(output_filename, content)


@router.post("/tasks/{task_id}/report", summary="从已完成任务按标准文件逐份生成 COA 报告单")
async def generate_task_report(
    task_id: uuid.UUID,
    payload: TaskReportGenerateRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:report:generate")),
):
    # 逐份生成：每个标准文件各出一份 COA（行归属其标准文件；模板按该文件 COA 绑定取）
    splits = await test_task_service.build_task_report_splits(db, task_id)
    generated = []
    for split in splits:
        template = split["template"]
        tp = REPORT_TEMPLATE_DIR / template
        if not quality_storage.ensure_template_local(template).is_file():
            raise HTTPException(status_code=404, detail=f"模板不存在：{template}")
        output_path, output_filename, _content = _render_cao_file(
            tp, split["fill_data"], split["product_name"], split["batch_number"],
            suffix=split["doc"].file_no,
        )
        record = await create_report_record(
            db=db,
            test_task_id=task_id,
            template_path=template,
            product_name=split["product_name"],
            batch_number=split["batch_number"],
            file_path=str(output_path),
            file_size=output_path.stat().st_size,
        )
        generated.append({
            "report_id": str(record.id),
            "filename": output_filename,
            "file_no": split["doc"].file_no,
            "template_path": template,
        })
    return success_response(
        data=generated,
        message=f"已按标准文件逐份生成 {len(generated)} 份 COA",
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
    # MinIO 优先（容器重建后本地文件丢失时仍可下载），本地副本兜底
    minio_data = quality_storage.read_report_from_minio(fp.name)
    if minio_data:
        return StreamingResponse(
            BytesIO(minio_data),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{fp.name}"'},
        )
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
    # 临时调试：保留提取文本用于解析器调优（修完解析器后移除）
    debug_dump_dir = Path("/tmp/std_doc_debug")
    debug_dump_dir.mkdir(parents=True, exist_ok=True)
    (debug_dump_dir / f"{filename}.txt").write_text(text, encoding="utf-8")

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
        for it in await list_standard_items(db, existing.id):
            it.is_deleted = True
        await db.flush()
        doc = existing
        overwritten = True
    else:
        doc = await create_standard_document(db, doc_data.model_dump())
    created = 0
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
        try:
            # 每条独立保存点：单条失败不污染整个事务
            async with db.begin_nested():
                await create_standard_item(db, doc.id, data)
            created += 1
        except Exception:
            skipped += 1
    verb = "覆盖更新完成" if overwritten else "确认导入完成"
    msg = f"{verb}：{created}/{len(payload.items)} 条标准行"
    if skipped:
        msg += f"，{skipped} 条重复或异常跳过"
    return success_response(
        data={
            "id": str(doc.id),
            "file_no": doc.file_no,
            "created_items": created,
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
    # 临时调试：保留提取文本用于解析器调优（修完解析器后移除）
    debug_dump_dir = Path("/tmp/std_doc_debug")
    debug_dump_dir.mkdir(parents=True, exist_ok=True)
    (debug_dump_dir / f"{filename}.txt").write_text(text, encoding="utf-8")

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
) -> JSONResponse:
    doc = await create_standard_document(db, payload.model_dump())
    return success_response(data={"id": str(doc.id)}, message="标准文档创建成功", status_code=201)


@router.put("/standards/documents/{doc_id}", summary="更新质量标准文档")
async def update_standard_doc(
    doc_id: uuid.UUID,
    payload: StandardDocumentUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    doc = await update_standard_document(db, doc_id, **updates)
    if not doc:
        raise HTTPException(status_code=404, detail="标准文档不存在")
    return success_response(message="已更新")


@router.delete("/standards/documents/{doc_id}", summary="删除质量标准文档")
async def delete_standard_doc(
    doc_id: uuid.UUID, db: AsyncSession = Depends(get_db),
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
) -> JSONResponse:
    it = await create_standard_item(db, doc_id, payload.model_dump())
    return success_response(data={"id": str(it.id)}, message="已添加", status_code=201)


@router.put("/standards/items/{item_id}", summary="更新标准项目行")
async def update_standard_doc_item(
    item_id: uuid.UUID,
    payload: StandardItemUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    it = await update_standard_item(db, item_id, **updates)
    if not it:
        raise HTTPException(status_code=404, detail="标准行不存在")
    return success_response(message="已更新")


@router.delete("/standards/items/{item_id}", summary="删除标准项目行")
async def delete_standard_doc_item(
    item_id: uuid.UUID, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    it = await delete_standard_item(db, item_id)
    if not it:
        raise HTTPException(status_code=404, detail="标准行不存在")
    return success_response(message="已删除")


# ─── 检验任务（检阅+填报）───


@router.post("/tasks", summary="创建检验任务（从标准库快照项目行）")
async def create_test_task_endpoint(
    payload: TestTaskCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:create")),
) -> JSONResponse:
    detail = await test_task_service.create_task(db, payload)
    return success_response(data=detail.model_dump(mode="json"), message="任务创建成功", status_code=201)


@router.get("/tasks", summary="检验任务分页列表")
async def list_test_task_endpoint(
    product_name: str | None = Query(default=None, description="产品名称（模糊搜索）"),
    status: str | None = Query(default=None, description="状态筛选：in_progress/completed/void"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await test_task_service.list_tasks(db, product_name, status, page, page_size)
    return paginated_response(
        data=[it.model_dump(mode="json") for it in items],
        page=page, page_size=page_size, total=total,
    )


@router.get("/unqualified-events", summary="不合格事件台账")
async def list_unqualified_events_endpoint(
    handled: bool | None = Query(default=None, description="按处理状态过滤"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items = await list_unqualified_events(db, handled=handled)
    return success_response(data=[
        {
            "id": str(e.id),
            "task_id": str(e.task_id) if e.task_id else None,
            "product_name": e.product_name,
            "batch_number": e.batch_number,
            "item_name": e.item_name,
            "sop_no": e.sop_no,
            "result_value": e.result_value,
            "standard_text": e.standard_text,
            "limit_text": e.limit_text,
            "source": e.source,
            "handled": e.handled,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in items
    ])


@router.get("/tasks/summary", summary="按 SOP 汇总各批次检验结果（以 SOP 为索引）")
async def task_summary_by_sop_endpoint(
    product_name: str | None = Query(default=None, description="产品名称（模糊搜索）"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    data = await test_task_service.summary_by_sop(db, product_name)
    return success_response(data=data)


@router.get("/tasks/{task_id}", summary="检验任务详情（含结果行）")
async def get_test_task_endpoint(
    task_id: uuid.UUID, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await test_task_service.get_task_detail(db, task_id)
    if not detail:
        raise HTTPException(status_code=404, detail="检验任务不存在")
    return success_response(data=detail.model_dump(mode="json"))


@router.put("/tasks/{task_id}/results", summary="批量填报检验结果")
async def update_test_task_results_endpoint(
    task_id: uuid.UUID,
    payload: TestResultsUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:fill")),
) -> JSONResponse:
    detail = await test_task_service.update_results(db, task_id, payload)
    return success_response(data=detail.model_dump(mode="json"), message="已保存")


@router.post("/tasks/{task_id}/results", summary="追加临时结果行")
async def add_test_task_result_endpoint(
    task_id: uuid.UUID,
    payload: TestResultCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:fill")),
) -> JSONResponse:
    row = await test_task_service.add_result(db, task_id, payload)
    return success_response(data=row.model_dump(mode="json"), message="已添加", status_code=201)


@router.post("/tasks/{task_id}/parse-lc", summary="上传液相计算表解析并填入任务（P1）")
async def parse_lc_into_task_endpoint(
    task_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:fill")),
) -> JSONResponse:
    """解析液相计算表：结果按项目名映射填入任务结果行（判定以标准库快照为准）。"""
    filename = file.filename or "unknown.xlsx"
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 或 .xls")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 10MB")
    detail, filled, unmatched = await test_task_service.parse_lc_into_task(
        db, task_id, content, filename
    )
    msg = f"解析映射完成：已填入 {len(filled)} 项"
    if filled:
        msg += f"（{'、'.join(filled)}）"
    if unmatched:
        msg += f"；未匹配 {len(unmatched)} 项：{'、'.join(unmatched)}"
    return success_response(data=detail.model_dump(mode="json"), message=msg)


@router.put("/tasks/{task_id}/status", summary="任务状态流转（审核通过/驳回/重开/作废）")
async def update_test_task_status_endpoint(
    task_id: uuid.UUID,
    payload: TestTaskStatusUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:review")),
) -> JSONResponse:
    detail = await test_task_service.update_status(db, task_id, payload)
    return success_response(data=detail.model_dump(mode="json"), message="状态已更新")


@router.put("/tasks/{task_id}/report-date", summary="补录/修改出报日期（关联当日机器人任务推送）")
async def update_test_task_report_date_endpoint(
    task_id: uuid.UUID,
    payload: TestTaskReportDateUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:fill")),
) -> JSONResponse:
    detail = await test_task_service.update_report_date(db, task_id, payload)
    return success_response(
        data=detail.model_dump(mode="json"),
        message="出报日期已更新" if payload.report_date else "出报日期已清空",
    )


@router.delete("/tasks/{task_id}/results/{result_id}", summary="删除单行结果（软删除）")
async def delete_test_task_result_endpoint(
    task_id: uuid.UUID, result_id: uuid.UUID, db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:review")),
) -> JSONResponse:
    row = await test_task_service.delete_result(db, task_id, result_id)
    if not row:
        raise HTTPException(status_code=404, detail="结果行不存在")
    return success_response(message="已删除")


@router.delete("/tasks/{task_id}", summary="删除检验任务（软删级联结果行）")
async def delete_test_task_endpoint(
    task_id: uuid.UUID, db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:review")),
) -> JSONResponse:
    task = await test_task_service.delete_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="检验任务不存在")
    return success_response(message="已删除")
