"""离职合同台账 HTTP 路由（P3）：台账列表 / 筛选字典 / 合同情况说明导出 / 人工项维护 /
扫描件归档。

入口是离职台账页的「合同台账」页签。离职人员合同属敏感资料：读写均限 HR（全量数据范围）。
权限沿用既有登记：/departure-records/* 走离职台账读写权限；/departure-contracts 在
deps._HR_PATH_PERMISSIONS 单独登记（读 = 离职台账读权限）。
"""

import logging
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException, ForbiddenException, NotFoundException
from app.core.response import paginated_response, success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access
from app.modules.hr.labor_contract import archive_service, departure_service, service
from app.modules.hr.labor_contract import departure_ledger as ledger
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract.routes import _contract_dict
from app.modules.hr.models import DepartureRecord
from app.modules.hr.xlsx_utils import xlsx_response
from app.platform.audit.service import record_audit_log

logger = logging.getLogger(__name__)

router = APIRouter(tags=["HR-离职合同台账"])

PROCEDURE_RESOURCE = "hr_departure_contract"
# 合同终止方式的查询参数校验（列表与导出共用；取值见 departure_service.TERMINATION_LABELS）
_TERMINATION_TYPE_PATTERN = "^(expiry|resign|negotiated|employer|retire|transfer|other|none)$"
# 情况说明各列宽度（与 STATEMENT_HEADERS 对齐）
_STATEMENT_WIDTHS = (6, 10, 12, 20, 16, 12, 12, 12, 34, 12, 16, 12, 28, 20, 10, 10, 10)


class ContractProcedureInput(BaseModel):
    termination_type: str | None = Field(
        None, max_length=24, description="合同终止方式人工更正值；传空串 = 恢复自动判定",
    )
    approval_ref: str | None = Field(None, max_length=128, description="审批依据")
    separation_process_no: str | None = Field(None, max_length=64, description="离职流程单号")
    contract_original_status: str = Field(..., max_length=16, description="合同原件回收状态")


def _ensure_hr(ctx: HrAccessContext) -> None:
    if not ctx.is_unrestricted:
        raise ForbiddenException("数据范围限制：离职合同台账仅限 HR（全量数据范围）")


async def _load_departure(db: AsyncSession, record_id: UUID) -> DepartureRecord:
    departure = (await db.execute(
        select(DepartureRecord).where(
            DepartureRecord.id == record_id, DepartureRecord.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if departure is None:
        raise NotFoundException("离职记录", str(record_id))
    return departure


def _filters(
    *, department: str | None, date_from: date | None, date_to: date | None,
    termination_type: str | None, keyword: str | None,
) -> dict:
    return {
        "department": department, "date_from": date_from, "date_to": date_to,
        "termination_type": termination_type, "keyword": keyword,
    }


# ─── 台账列表 / 筛选字典 ───


@router.get("/departure-contracts/filter-options", summary="离职合同台账筛选字典")
async def filter_options(
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> Response:
    _ensure_hr(ctx)
    return success_response(data={
        "termination_types": [
            {"value": value, "label": label}
            for value, label in departure_service.TERMINATION_LABELS.items()
        ],
        "certificate_statuses": [
            {"value": value, "label": label}
            for value, label in departure_service.CERT_LABELS.items()
        ],
        "original_statuses": [
            {"value": value, "label": label}
            for value, label in DepartureRecord.ORIGINAL_STATUS_LABELS.items()
        ],
    })


@router.get(
    "/departure-contracts",
    summary="离职合同台账（人员 / 合同 / 离职信息 / 手续状态；按部门、离职时间、终止方式筛选）",
)
async def list_departure_contracts(
    department: str | None = Query(None, max_length=64),
    date_from: date | None = Query(None, description="离职日期起"),
    date_to: date | None = Query(None, description="离职日期止"),
    termination_type: str | None = Query(
        None, pattern=_TERMINATION_TYPE_PATTERN,
        description="合同终止方式",
    ),
    keyword: str | None = Query(None, max_length=64, description="姓名/工号模糊"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> Response:
    _ensure_hr(ctx)
    total, rows = await ledger.page_rows(
        db,
        **_filters(
            department=department, date_from=date_from, date_to=date_to,
            termination_type=termination_type, keyword=keyword,
        ),
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return paginated_response(data=rows, total=total, page=page, page_size=page_size)


@router.get(
    "/departure-contracts/export",
    summary="导出离职人员合同情况说明（Excel，与列表同筛选口径）",
)
async def export_departure_contracts(
    department: str | None = Query(None, max_length=64),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    termination_type: str | None = Query(None, pattern=_TERMINATION_TYPE_PATTERN),
    keyword: str | None = Query(None, max_length=64),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> Response:
    _ensure_hr(ctx)
    filters = _filters(
        department=department, date_from=date_from, date_to=date_to,
        termination_type=termination_type, keyword=keyword,
    )
    lines = await ledger.export_rows(db, **filters)

    type_label = departure_service.TERMINATION_LABELS.get(termination_type or "", "")
    conditions = [
        f"部门：{department}" if department else "",
        f"离职时间：{date_from} 至 {date_to}" if date_from or date_to else "",
        f"终止方式：{type_label}" if termination_type else "",
        f"关键字：{keyword}" if keyword else "",
    ]
    wb = Workbook()
    ws = wb.active
    ws.title = "离职人员合同情况说明"
    headers = ledger.STATEMENT_HEADERS
    width = len(headers)

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    title = ws.cell(row=1, column=1, value="离职人员合同情况说明")
    title.font = Font(bold=True, size=16)
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=width)
    exported_at = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    meta = ws.cell(
        row=2, column=1,
        value=f"导出时间：{exported_at}　　筛选条件：{'；'.join(c for c in conditions if c) or '全部'}"
              f"　　共 {len(lines)} 人",
    )
    meta.alignment = Alignment(horizontal="left", vertical="center")

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row_idx, line in enumerate(lines, 5):
        for col, value in enumerate(line, 1):
            ws.cell(row=row_idx, column=col, value=value)
    for idx, column_width in enumerate(_STATEMENT_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(idx)].width = column_width
    ws.freeze_panes = "A5"
    return xlsx_response(wb, f"离职人员合同情况说明_{date.today().isoformat()}.xlsx")


# ─── 人工项维护 / 扫描件归档 ───


@router.put(
    "/departure-records/{record_id}/contract-procedure",
    summary="维护离职合同台账人工项（终止方式更正 / 审批依据 / 流程单号 / 原件回收状态）",
)
async def update_contract_procedure(
    record_id: UUID,
    payload: ContractProcedureInput,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> Response:
    _ensure_hr(ctx)
    departure = await _load_departure(db, record_id)
    await departure_service.update_procedure(
        db, departure,
        termination_type=payload.termination_type,
        approval_ref=payload.approval_ref,
        separation_process_no=payload.separation_process_no,
        original_status=payload.contract_original_status,
        user=ctx.user,
    )
    await record_audit_log(
        db, action="hr.departure.contract_procedure", user=ctx.user,
        resource_type=PROCEDURE_RESOURCE, resource_id=departure.id,
        new_value={
            "name": departure.name, "employee_number": departure.employee_number,
            "termination_type": payload.termination_type,
            "approval_ref": payload.approval_ref,
            "separation_process_no": payload.separation_process_no,
            "contract_original_status": payload.contract_original_status,
        },
    )
    return success_response(message="已保存")


@router.post(
    "/departure-records/{record_id}/contract-archive",
    summary="离职人员合同扫描件归档（无合同行时按离职记录合同信息建档）",
)
async def archive_departure_contract(
    record_id: UUID,
    file: UploadFile = File(..., description="合同扫描件（图片/PDF，≤20MB）"),
    remark: str | None = Form(None, max_length=512),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> Response:
    _ensure_hr(ctx)
    departure = await _load_departure(db, record_id)
    data = await file.read()
    if not data:
        raise AppException(message="扫描件不能为空", status_code=422)
    contract = await departure_service.ensure_departure_contract(db, departure, user=ctx.user)
    version = await archive_service.create_archive_version(
        db, contract=contract, file_bytes=data, filename=file.filename,
        remark=remark, user=ctx.user,
    )
    await record_audit_log(
        db, action="hr.contract.archive_upload", user=ctx.user,
        resource_type=archive_service.RESOURCE_TYPE, resource_id=contract.id,
        new_value={"version_no": version.version_no, "filename": version.file_name,
                   "departure_record_id": str(departure.id)},
    )
    # UPDATE 后重查再序列化
    contract = await service.get_or_404(db, contract.id)
    return success_response(
        data={
            "contract": _contract_dict(contract),
            "versions": [
                archive_service.version_dict(v)
                for v in await repo.list_versions(db, contract.id)
            ],
        },
        message=f"已归档（版本 v{version.version_no}）",
    )
