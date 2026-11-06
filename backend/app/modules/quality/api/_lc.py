"""lc API 路由（api.py 拆分）。"""

import uuid
from typing import Any

from fastapi import (
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.quality.api._common import (
    router,
)
from app.modules.quality.repository import (
    create_lc_template_config,
    delete_inspection_record,
    delete_lc_template_config,
    get_lc_template_by_table_no,
    get_test_task_by_batch,
    list_inspection_records,
    list_lc_template_configs,
    update_lc_template_config,
)
from app.modules.quality.schemas import (
    InspectionRecordListItem,
    LcReportOut,
    LcTemplateConfigCreate,
    LcTemplateConfigUpdate,
    UploadLcResponse,
)
from app.modules.quality.service import (
    lc_report_service,
    test_task_service,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

# ─── 液相解析上传 ───


@router.post("/lc/upload", response_model=UploadLcResponse, summary="上传液相计算表并解析")
async def upload_lc_excel(
    file: UploadFile = File(...),
    password: str | None = Form(default=None, description="文件密码（加密计算表用；仅内存解密，不落库）"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:lc:upload")),
) -> UploadLcResponse:
    filename = file.filename or "unknown.xlsx"
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 或 .xls")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 10MB")
    if password:
        from app.modules.quality.lc_template_parser import decrypt_office_file

        try:
            file_bytes = decrypt_office_file(file_bytes, password)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    try:
        # 优先模板配置驱动的通用解析（表号识别）；无匹配配置回落到旧解析器
        generic = await test_task_service.parse_lc_generic(db, file_bytes, filename, filled_by=_user.id)
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
        # 回落旧解析器前先确认：识别出表号但无配置 → 明确报错，而非旧万古霉素解析器乱读
        from app.modules.quality.lc_template_parser import detect_table_no, open_sheet

        get, max_row, max_col = open_sheet(file_bytes, filename)
        table_no = detect_table_no(get, max_row, max_col)
        if table_no:
            raise HTTPException(
                status_code=422,
                detail=f"表号 {table_no} 未配置计算规则，暂不支持解析（可在「报告模板→计算表取值配置」添加，或使用在线计算表）",
            )
        result = await lc_report_service.parse_and_validate(file_bytes, filename, db=db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"无法解析：{e}") from e
    # 自动关联已建检验任务：按产品+批号定位，按 SOP/项目名映射填入
    if result.record_id:
        task = await get_test_task_by_batch(db, result.report.product_name, result.report.batch_number)
        if task and task.status == "in_progress":
            filled, unmatched = await test_task_service.fill_task_from_report(
                db, task, result.report, result.record_id, filled_by=_user.id
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
    _user: User = Depends(require_permission("quality:lc:read")),
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
    _user: User = Depends(require_permission("quality:lc:read")),
) -> JSONResponse:
    detail = await lc_report_service.get_record_detail(db, record_id)
    if not detail:
        raise HTTPException(status_code=404, detail="检验记录不存在")
    return success_response(data=detail.model_dump(mode="json"))


@router.delete("/lc/records/{record_id}", summary="删除检验记录（软删除）")
async def delete_lc_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:lc:upload")),
) -> JSONResponse:
    result = await delete_inspection_record(db, record_id)
    if not result:
        raise HTTPException(status_code=404, detail="检验记录不存在")
    return success_response(message="已删除")


# ─── 液相计算表模板配置维护（表号 → 取值配置）───


def _shift_col(col: str, delta: int) -> str | None:
    """列字母平移（A+1=B），越界返回 None。"""
    num = 0
    for ch in col.upper():
        if not ch.isalpha():
            return None
        num = num * 26 + (ord(ch) - 64)
    num += delta
    if num < 1 or num > 702:
        return None
    out = ""
    while num:
        num, rem = divmod(num - 1, 26)
        out = chr(65 + rem) + out
    return out


def _shifted_config(cfg: dict[str, Any], dn: int, dv: int, step: int | None = None) -> dict[str, Any]:
    """按列偏移/步长复制配置：blocks 的 name_col 平移 dn、value/fallback 平移 dv、step 可覆盖。"""
    import copy

    c = copy.deepcopy(cfg)
    for b in c.get("blocks", []) or []:
        if b.get("name_col"):
            b["name_col"] = _shift_col(str(b["name_col"]), dn) or str(b["name_col"])
        if b.get("value_col"):
            b["value_col"] = _shift_col(str(b["value_col"]), dv) or str(b["value_col"])
        if b.get("fallback_col"):
            b["fallback_col"] = _shift_col(str(b["fallback_col"]), dv) or str(b["fallback_col"])
        if step is not None:
            b["step"] = step
    limits = c.get("limits")
    if limits:
        if limits.get("name_col"):
            limits["name_col"] = _shift_col(str(limits["name_col"]), dn) or str(limits["name_col"])
        if limits.get("value_col"):
            limits["value_col"] = _shift_col(str(limits["value_col"]), dv) or str(limits["value_col"])
    return c


@router.post("/lc/templates/auto-detect", summary="傻瓜式维护：上传文件自动识别同版式模板（无需会写 JSON）")
async def auto_detect_template_endpoint(
    file: UploadFile = File(...),
    password: str | None = Form(default=None, description="文件密码（加密计算表用）"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    """把上传的计算表和库里全部配置逐一「试版式」：能提取出≥3个有效值的即视为同版式候选。

    返回 table_no 与候选列表（含提取组分样例），供前端傻瓜式确认生成。
    """
    from pathlib import Path as _Path

    from app.modules.quality.lc_template_parser import (
        decrypt_office_file,
        detect_table_no,
        open_sheet_cached,
        parse_with_config,
    )
    from app.modules.quality.repository import list_lc_template_configs

    filename = file.filename or "calc.xlsx"
    if _Path(filename).suffix.lower() not in (".xlsx", ".xls"):
        raise HTTPException(status_code=422, detail="仅支持 .xlsx/.xls")
    data = await file.read()
    if not data or len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="文件为空或超过 10MB")
    if password:
        try:
            data = decrypt_office_file(data, password)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    try:
        get, max_row, max_col = open_sheet_cached(data, filename)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    table_no = detect_table_no(get, max_row, max_col)
    if not table_no:
        raise HTTPException(status_code=422, detail="未识别到表号（EX-xx-xxxx-vvv），请确认文件为计算表")
    cfgs = await list_lc_template_configs(db)
    family = table_no[:5] if len(table_no) >= 5 else ""  # 如 EX-TA / EX-HA
    family_cfgs = [c for c in cfgs if family and (c.table_no or "").startswith(family)]
    trial_cfgs = family_cfgs or cfgs
    # 同家族：全量搜索（列偏移 × 步长）；跨家族：仅原版式直试
    shifts = [(dn, dv, step) for dn in (-8, -6, -4, -2, -1, 0, 1, 2) for dv in (-4, -2, -1, 0, 1, 2, 4) for step in (1, 2, 4)]
    candidates: list[dict[str, Any]] = []
    for cfg in trial_cfgs:
        same_family = bool(family_cfgs) and cfg in family_cfgs
        combos = shifts if same_family else [(0, 0, None)]
        best: tuple[tuple[int, int], int, int, int | None, Any] | None = None
        for dn, dv, step in combos:
            try:
                parsed = parse_with_config(
                    data, filename, _shifted_config(cfg.config or {}, dn, dv, step), table_no,
                    get=get, max_row=max_row, max_col=max_col,
                )
            except Exception:  # noqa: BLE001 — 版式不符直接跳过
                continue
            value_n = len([c for c in parsed.components if c.report_value is not None])
            # 有值候选永远优先（rank=1）；空白模板（公式未填值）按标签行数匹配版式（rank=0）
            if value_n >= 3:
                rank = (1, value_n)
            elif len(parsed.components) >= 10:
                rank = (0, len(parsed.components))
            else:
                continue
            if best is None or rank > best[0]:
                best = (rank, dn, dv, step, parsed)
        if best is None:
            continue
        _rank, dn, dv, step, parsed = best
        values = [c for c in parsed.components if c.report_value is not None]
        candidates.append({
            "template_table_no": cfg.table_no,
            "product_name": cfg.product_name or "",
            "description": cfg.description or "",
            "component_count": len(parsed.components),
            "value_count": len(values),
            "blank": len(values) == 0,
            "name_shift": dn,
            "value_shift": dv,
            "step": step,
            "samples": [
                {"name": c.name, "value": c.report_value}
                for c in (values or parsed.components)[:8]
            ],
        })
    candidates.sort(key=lambda x: (x["blank"], -x["value_count"]))
    return success_response(data={"table_no": table_no, "candidates": candidates})


@router.post("/lc/templates/auto-create", summary="傻瓜式维护：按同版式模板一键生成新表号配置")
async def auto_create_template_endpoint(
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    """复制模板配置生成新表号配置（不改 JSON）；表号已存在时 409。"""
    from app.modules.quality.repository import (
        create_lc_template_config,
        get_lc_template_by_table_no,
    )

    table_no = str(payload.get("table_no") or "").strip()
    template_no = str(payload.get("template_table_no") or "").strip()
    name_shift = int(payload.get("name_shift") or 0)
    value_shift = int(payload.get("value_shift") or 0)
    step = payload.get("step")
    if not table_no or not template_no:
        raise HTTPException(status_code=400, detail="缺少表号/模板表号")
    existing = await get_lc_template_by_table_no(db, table_no)
    if existing:
        raise HTTPException(status_code=409, detail=f"表号 {table_no} 已存在配置（可先删除旧配置或联系管理员）")
    template = await get_lc_template_by_table_no(db, template_no)
    if not template:
        raise HTTPException(status_code=404, detail=f"模板表号 {template_no} 不存在")
    config = _shifted_config(template.config or {}, name_shift, value_shift, int(step) if step else None) if (name_shift or value_shift or step) else (template.config or {})
    shift_note = f"，标签列偏移 {name_shift:+d}/值列偏移 {value_shift:+d}" if (name_shift or value_shift) else ""
    cfg = await create_lc_template_config(
        db, table_no=table_no, product_name=template.product_name,
        sop_no=template.sop_no,
        description=f"自动生成（版式同 {template_no}{shift_note}，请用「测试计算」验证后启用）",
        config=config,
    )
    return success_response(data={"id": str(cfg.id), "table_no": cfg.table_no}, message="配置已生成", status_code=201)


@router.get("/lc/templates", summary="液相计算表模板配置列表")
async def list_lc_template_configs_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    cfgs = await list_lc_template_configs(db)
    return success_response(data=[
        {
            "id": str(c.id),
            "table_no": c.table_no,
            "product_name": c.product_name,
            "sop_no": c.sop_no,
            "description": c.description,
            "config": c.config,
        }
        for c in cfgs
    ])


@router.post("/lc/templates", summary="新增液相计算表模板配置")
async def create_lc_template_config_endpoint(
    payload: LcTemplateConfigCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    existing = await get_lc_template_by_table_no(db, payload.table_no)
    if existing:
        raise HTTPException(status_code=409, detail=f"表号 {payload.table_no} 已存在配置")
    cfg = await create_lc_template_config(
        db, table_no=payload.table_no, product_name=payload.product_name,
        sop_no=payload.sop_no, description=payload.description, config=payload.config,
    )
    return success_response(
        data={"id": str(cfg.id), "table_no": cfg.table_no}, message="模板配置已创建", status_code=201,
    )


@router.put("/lc/templates/{cfg_id}", summary="更新液相计算表模板配置")
async def update_lc_template_config_endpoint(
    cfg_id: uuid.UUID,
    payload: LcTemplateConfigUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    cfg = await update_lc_template_config(db, cfg_id, **payload.model_dump(exclude_unset=True))
    if not cfg:
        raise HTTPException(status_code=404, detail="模板配置不存在")
    return success_response(data={"id": str(cfg.id)}, message="模板配置已更新")


@router.delete("/lc/templates/{cfg_id}", summary="删除液相计算表模板配置（软删除）")
async def delete_lc_template_config_endpoint(
    cfg_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    ok = await delete_lc_template_config(db, cfg_id)
    if not ok:
        raise HTTPException(status_code=404, detail="模板配置不存在")
    return success_response(message="模板配置已删除")
