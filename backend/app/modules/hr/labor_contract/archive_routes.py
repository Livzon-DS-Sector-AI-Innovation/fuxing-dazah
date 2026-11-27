"""合同电子档案库 HTTP 路由（P2）：档案库台账 / 补扫清单 / 扫描件版本与原件调阅 /
批量挂接 / 员工历次合同视图。

路径都在 /labor-contracts 与 /labor-contracts-archive 下，权限沿用 deps._HR_PATH_PERMISSIONS
里 /labor-contracts 的既有通配登记（GET 读 / POST·DELETE 管理），无需另登记。
归档写操作、补扫清单导出与批量挂接额外要求全量数据范围（仅 HR）；原件调阅按三级权限
（见 archive_service.can_access_file）。
"""

import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException, ForbiddenException, NotFoundException
from app.core.response import paginated_response, success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access
from app.modules.hr.labor_contract import archive_batch_import as batch_import
from app.modules.hr.labor_contract import archive_service, service
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract.models import ContractArchiveVersion
from app.modules.hr.labor_contract.routes import (
    _archive_caps,
    _contract_dict,
    _ensure_in_scope,
    _list_scope,
)
from app.modules.hr.xlsx_utils import write_sheet, xlsx_response
from app.platform.audit.service import record_audit_log

logger = logging.getLogger(__name__)

router = APIRouter(tags=["HR-劳动合同档案"])

RESOURCE_TYPE = archive_service.RESOURCE_TYPE


def _ensure_hr(ctx: HrAccessContext, message: str) -> None:
    if not ctx.is_unrestricted:
        raise ForbiddenException(message)


async def _load_version(
    db: AsyncSession, contract_id: UUID, version_id: UUID,
) -> ContractArchiveVersion:
    version = await repo.get_version(db, version_id)
    if version is None or version.contract_id != contract_id:
        raise NotFoundException("合同扫描件", str(version_id))
    return version


async def _version_list(db: AsyncSession, contract_id: UUID) -> list[dict]:
    return [
        archive_service.version_dict(v)
        for v in await repo.list_versions(db, contract_id)
    ]


# ─── 档案库台账 / 概览 / 补扫清单 ───


@router.get("/labor-contracts-archive", summary="电子档案库台账（归档状态 / 在职离职 / 部门筛选）")
async def list_archive(
    archive_status: str | None = Query(None, pattern="^(unarchived|archived)$"),
    population: str = Query(
        "in_service", pattern="^(in_service|departed|all)$",
        description="in_service 在职 / departed 离职 / all 全部（后两者仅 HR 可用）",
    ),
    keyword: str | None = Query(None, max_length=64, description="姓名/工号模糊"),
    department: str | None = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> Response:
    # 在职台账只放在职人员合同：非全量范围一律按在职 + 授权部门收敛
    employee_number, departments = _list_scope(ctx, department)
    total, rows = await repo.list_page(
        db,
        departments=departments,
        keyword=keyword,
        employee_number=employee_number,
        population=population if ctx.is_unrestricted else repo.POPULATION_IN_SERVICE,
        archive_status=archive_status,
        order_by="department",
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    departed = await archive_service.resolve_departed(db, rows)
    data = [
        {
            **_contract_dict(c),
            "is_departed": c.employee_number in departed,
            **_archive_caps(ctx, c),
        }
        for c in rows
    ]
    return paginated_response(data=data, total=total, page=page, page_size=page_size)


@router.get("/labor-contracts-archive/stats", summary="档案库概览（在职/离职 × 未归档/已归档）")
async def archive_stats(
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> Response:
    _ensure_hr(ctx, "数据范围限制：档案库概览仅限 HR（全量数据范围）")
    return success_response(data={
        **await archive_service.archive_stats(db),
        # 归档写操作仅 HR：随概览下发，前端据此控制批量挂接等入口显隐
        "can_archive": ctx.is_unrestricted,
    })


@router.get(
    "/labor-contracts-archive/departments",
    summary="未归档份数按部门（档案库部门下拉；非全量范围只返回授权部门）",
)
async def archive_departments(
    department: str | None = Query(None, max_length=64),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> Response:
    _, departments = _list_scope(ctx, department)
    return success_response(
        data=await archive_service.unarchived_by_department(db, departments=departments)
    )


@router.get(
    "/labor-contracts-archive/export-unarchived",
    summary="导出补扫清单（未归档合同，按部门分组；含在职与离职）",
)
async def export_unarchived(
    department: str | None = Query(None, max_length=64, description="不传=全部部门"),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> Response:
    _ensure_hr(ctx, "数据范围限制：补扫清单导出仅限 HR（全量数据范围）")
    contracts = await repo.list_unarchived(db, department=department)
    departed = await archive_service.resolve_departed(db, contracts)
    wb = Workbook()
    ws = wb.active
    ws.title = "合同补扫清单"
    write_sheet(
        ws, archive_service.UNARCHIVED_EXPORT_HEADERS,
        archive_service.unarchived_export_rows(contracts, departed),
    )
    return xlsx_response(wb, f"合同补扫清单_{date.today().isoformat()}.xlsx")


# ─── 员工历次合同（员工档案「合同」页签：一人一事一档）───


@router.get(
    "/labor-contracts/by-employee/{employee_number}",
    summary="员工历次合同（含归档状态；员工档案合同页签）",
)
async def list_by_employee(
    employee_number: str,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> Response:
    contracts = await repo.list_by_employee(db, employee_number)
    if not ctx.is_unrestricted:
        if ctx.data_scope == "self_only":
            # 员工本人：仅本人合同
            if employee_number != ctx.employee_number:
                raise ForbiddenException("数据范围限制：仅可访问本人合同")
        elif contracts:
            # 部门范围：授权部门内在职人员的合同（离职人员合同仅 HR 可见）
            await _ensure_in_scope(db, ctx, contracts[-1])
        else:
            employee = await repo.get_employee(db, employee_number)
            if employee is None:
                raise NotFoundException("员工档案", f"工号 {employee_number}")
            ctx.ensure_can_access_employee(employee)
    return success_response(data={
        "contracts": [_contract_dict(c) for c in contracts],
        # 原件调阅权限随人：HR 与员工本人可看，部门范围只有基本信息
        "can_access_file": bool(contracts) and archive_service.can_access_file(ctx, contracts[-1]),
        "can_archive": ctx.is_unrestricted,
    })


# ─── 扫描件版本 / 上传 / 删除 ───


@router.get("/labor-contracts/{contract_id}/archive/versions", summary="合同扫描件版本（新→旧）")
async def list_archive_versions(
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> Response:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    return success_response(data=await _version_list(db, contract.id))


@router.post(
    "/labor-contracts/{contract_id}/archive",
    summary="上传合同扫描件（逐页合并一份；已有扫描件则升为新版本，旧版保留）",
)
async def upload_archive(
    contract_id: UUID,
    file: UploadFile = File(..., description="合同扫描件（图片/PDF，≤20MB）"),
    remark: str | None = Form(None, max_length=512),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> Response:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    archive_service.ensure_can_archive(ctx)
    data = await file.read()
    if not data:
        raise AppException(message="扫描件不能为空", status_code=422)
    version = await archive_service.create_archive_version(
        db, contract=contract, file_bytes=data, filename=file.filename,
        remark=remark, user=ctx.user,
    )
    await record_audit_log(
        db, action="hr.contract.archive_upload", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
        new_value={"version_no": version.version_no, "filename": version.file_name},
    )
    # UPDATE 后重查再序列化（updated_at 等 server 端值不回填内存对象）
    contract = await service.get_or_404(db, contract.id)
    return success_response(
        data={
            "contract": _contract_dict(contract),
            "versions": await _version_list(db, contract.id),
        },
        message=f"已归档（版本 v{version.version_no}）",
    )


@router.delete(
    "/labor-contracts/{contract_id}/archive/{version_id}",
    summary="删除扫描件版本（软删；删当前版时最新历史版本顶替）",
)
async def delete_archive_version(
    contract_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> Response:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    version = await _load_version(db, contract.id, version_id)
    await archive_service.delete_version(db, ctx, contract, version)
    await record_audit_log(
        db, action="hr.contract.archive_delete", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
        old_value={"version_no": version.version_no, "file_name": version.file_name},
    )
    contract = await service.get_or_404(db, contract.id)
    return success_response(
        data={"contract": _contract_dict(contract), "versions": await _version_list(db, contract.id)},
        message=f"已删除版本 v{version.version_no}",
    )


@router.get(
    "/labor-contracts/{contract_id}/archive/{version_id}/file",
    summary="合同扫描件原件（预览/下载；三级调阅权限 + 留痕）",
)
async def get_archive_file(
    contract_id: UUID,
    version_id: UUID,
    download: bool = Query(False, description="true=下载附件模式"),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> Response:
    contract = await service.get_or_404(db, contract_id)
    version = await _load_version(db, contract.id, version_id)
    data, headers = await archive_service.get_archive_file(
        db, ctx, contract, version, download=download,
    )
    return Response(content=data, headers=headers)


@router.get("/labor-contracts/{contract_id}/access-logs", summary="合同扫描件调阅/下载记录")
async def list_access_logs(
    contract_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> Response:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    total, items = await archive_service.list_access_logs(
        db, contract.id, page=page, page_size=page_size,
    )
    return paginated_response(data=items, total=total, page=page, page_size=page_size)


# ─── 批量挂接（存量电子档：ZIP + 可选 Excel 清单，两步预检式）───


@router.get(
    "/labor-contracts-archive/batch-import/template",
    summary="批量挂接 Excel 清单模板",
)
async def batch_import_template(
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> Response:
    wb = Workbook()
    ws = wb.active
    ws.title = "合同扫描件清单"
    write_sheet(ws, batch_import.MANIFEST_HEADERS, batch_import.MANIFEST_EXAMPLES)
    for col, width in zip("ABCD", (16, 18, 48, 32), strict=True):
        ws.column_dimensions[col].width = width
    return xlsx_response(wb, "合同扫描件导入清单模板.xlsx")


@router.get(
    "/labor-contracts-archive/batch-import/options",
    summary="批量挂接补选（按姓名/工号搜员工与离职人员，返回其合同清单）",
)
async def batch_import_options(
    keyword: str | None = Query(None, max_length=64),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> Response:
    archive_service.ensure_can_archive(ctx)
    return success_response(data=await batch_import.search_options(db, keyword))


@router.post(
    "/labor-contracts-archive/batch-import/precheck",
    summary="扫描件批量挂接预检（ZIP：扫描件 + 可选 Excel 清单；附件入暂存）",
)
async def batch_import_precheck(
    file: UploadFile = File(..., description="ZIP 包（≤200MB、≤200 个扫描件，支持子文件夹）"),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> Response:
    archive_service.ensure_can_archive(ctx)
    zip_bytes = await file.read()
    if not zip_bytes:
        raise AppException(message="ZIP 包不能为空", status_code=422)
    try:
        return success_response(data=await batch_import.precheck_import(db, zip_bytes=zip_bytes))
    except ValueError as e:
        raise AppException(message=str(e))


@router.post(
    "/labor-contracts-archive/batch-import/commit",
    summary="扫描件批量挂接提交（按确认行归档，版本化同单个上传）",
)
async def batch_import_commit(
    payload: batch_import.ArchiveImportCommitPayload,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> Response:
    archive_service.ensure_can_archive(ctx)
    try:
        data = await batch_import.commit_import(db, ctx, payload.rows)
    except ValueError as e:
        raise AppException(message=str(e))
    summary = data["summary"]
    return success_response(
        data=data,
        message=f"已挂接 {summary['imported']} 份，失败 {summary['failed']} 份",
    )
