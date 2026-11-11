"""员工档案多维表格同步 API（绑定配置 / 手动全量同步 / 培训脱敏名单）。

路由层只做参数清洗与 HTTP 语义转换；连通性校验/订阅/同步逻辑在 service。
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import (
    HrAccessContext,
    get_hr_scope,
    require_hr_access,
    require_hr_basic,
)
from app.modules.hr.employee_sync.bitable_client import clean_app_token, clean_table_id
from app.modules.hr.employee_sync.config import load_config
from app.modules.hr.employee_sync.service import (
    EmployeeSyncService,
    SyncInProgressError,
    config_payload,
)

logger = logging.getLogger(__name__)

# 管理动作统一权限；读取状态仅要求 HR 访问（员工档案页要给普通用户显示同步条）
router = APIRouter(prefix="/employee-sync", tags=["HR-员工档案同步"])
_MANAGE = Depends(require_hr_access("hr:settings:manage"))

# 名单分页上限：选人/通知等场景按部门取全员且无翻页 UI，放宽到 500
# （当前全员 1300+，按部门筛选远小于该值；前端取全量另有翻页循环兜底）
_ROSTER_PAGE_SIZE_CAP = 500


class EmployeeSyncConfigInput(BaseModel):
    enabled: bool = Field(False, description="启用同步（员工档案转为只读展示）")
    app_token: str = Field("", description="飞书多维表格 Base 的 app_token")
    source_table_id: str = Field("", description="员工档案源数据表 table_id")


@router.get("/config", summary="读取员工档案同步配置")
async def get_sync_config(
    session: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = Depends(require_hr_basic),
) -> JSONResponse:
    cfg = await load_config(session)
    return success_response(data=config_payload(cfg))


@router.put("/config", summary="保存同步配置（校验连通 + 列匹配报告）")
async def save_sync_config(
    payload: EmployeeSyncConfigInput,
    session: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = _MANAGE,
) -> JSONResponse:
    # 容忍粘贴完整链接/带查询串，清洗后再校验与入库
    try:
        data = await EmployeeSyncService(session).save_binding_config(
            enabled=payload.enabled,
            app_token=clean_app_token(payload.app_token),
            source_table_id=clean_table_id(payload.source_table_id),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return success_response(data=data, message="同步配置已保存")


@router.post("/sync", summary="立即全量同步（源表 → 员工档案）")
async def sync_now(
    session: AsyncSession = Depends(get_db), _ctx: HrAccessContext = _MANAGE,
) -> JSONResponse:
    cfg = await load_config(session)
    if not cfg.is_ready:
        raise HTTPException(400, "同步未启用或绑定不完整，请先在设置中完成绑定")
    service = EmployeeSyncService(session)
    try:
        stats = await service.reconcile(cfg)
    except SyncInProgressError as exc:
        raise HTTPException(409, str(exc)) from exc
    await session.commit()
    return success_response(data=stats, message="同步完成")


@router.get("/training-roster", summary="培训专用脱敏名单（仅白名单字段，敏感信息不出库）")
async def get_training_roster(
    department: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
    _ctx: HrAccessContext = Depends(require_hr_basic),
) -> JSONResponse:
    """培训管理专用的人员名单：独立数据集（人员随员工档案增减，字段独立维护）。

    身份证/学校/专业/出生/联系方式等个人敏感字段在这里根本不存在。
    按用户数据范围过滤（与员工档案共用「用户多部门访问授权」）；meta 带
    scoped_departments 供前端收敛部门页签（null=不受限）。
    """
    service = EmployeeSyncService(session)
    scoped = None if hr_scope.is_unrestricted else set(hr_scope.scoped_departments)
    rows, total = await service.training_roster(
        department=department, keyword=keyword,
        page=max(page, 1), page_size=min(max(page_size, 1), _ROSTER_PAGE_SIZE_CAP),
        scoped_departments=scoped,
    )
    return success_response(data=rows, meta={
        "total": total, "page": page, "page_size": page_size,
        "scoped_departments": sorted(scoped) if scoped is not None else None,
    })


@router.get("/training-roster/export", summary="培训人员名单导出（xlsx，含报表用职级）")
async def export_training_roster(
    department: str | None = None,
    keyword: str | None = None,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
    _ctx: HrAccessContext = Depends(require_hr_basic),
) -> StreamingResponse:
    """导出当前筛选范围的全量名单（数据范围与列表接口一致）。"""
    from io import BytesIO
    from urllib.parse import quote

    from openpyxl import Workbook

    from app.modules.hr.employee_sync.config import TRAINING_ROSTER_FIELDS
    from app.modules.hr.employee_sync.report_level import (
        REPORT_LEVEL_FIELD,
        REPORT_LEVEL_LABEL,
    )

    service = EmployeeSyncService(session)
    scoped = None if hr_scope.is_unrestricted else set(hr_scope.scoped_departments)
    rows, _total = await service.training_roster(
        department=department, keyword=keyword,
        page=1, page_size=1_000_000,  # 导出全量，不受列表分页上限约束
        scoped_departments=scoped,
    )

    # 列 = 白名单列 + 「报表用职级」（紧跟「职务」列，与前端列序一致）
    columns: list[tuple[str, str]] = []
    for label, attr in TRAINING_ROSTER_FIELDS.items():
        columns.append((label, attr))
        if attr == "duty":
            columns.append((REPORT_LEVEL_LABEL, REPORT_LEVEL_FIELD))

    def _cell(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return "、".join(str(v) for v in value if v is not None)
        return str(value)

    wb = Workbook()
    ws = wb.active
    ws.title = "培训人员名单"
    ws.append([label for label, _attr in columns])
    for row in rows:
        ws.append([_cell(row.get(attr)) for _label, attr in columns])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    from datetime import date as _date

    filename = f"培训人员名单_{_date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"},
    )


class TrainingRosterUpdateInput(BaseModel):
    """名单编辑入参（仅白名单字段；工号不可改）。"""

    name: str | None = None
    department: str | None = None
    actual_department: str | None = None
    team: str | None = None
    position: str | None = None
    duty: str | None = None
    job_category: str | None = None
    level: str | None = None
    variety: str | None = None
    concurrent_departments: str | None = None
    concurrent_variety: str | None = None
    education: str | None = None
    graduation_date: date | None = None
    status_category: str | None = None
    work_start_date: date | None = None
    factory_entry_date: date | None = None
    livo_entry_date: date | None = None
    hire_date: date | None = None
    departure_date: date | None = None
    certificates: str | None = None
    qualifications: list[str] | None = None
    training_id: str | None = None
    dept_head_trainer: str | None = None
    safety_training_date: date | None = None
    safety_training_score: str | None = None
    culture_training_date: date | None = None
    gmp_training_date: date | None = None


@router.put("/training-roster/{employee_number}", summary="编辑培训人员名单条目")
async def update_training_roster(
    employee_number: str,
    payload: TrainingRosterUpdateInput,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
    _ctx: HrAccessContext = Depends(require_hr_access("hr:training:manage")),
) -> JSONResponse:
    """编辑名单条目（编辑结果不被员工档案同步覆盖；受限用户仅可编辑授权部门）。"""
    service = EmployeeSyncService(session)
    scoped = None if hr_scope.is_unrestricted else set(hr_scope.scoped_departments)
    try:
        await service.update_roster_entry(
            employee_number, payload.model_dump(exclude_unset=True),
            scoped_departments=scoped, updated_by=hr_scope.user.id,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    await session.commit()
    return success_response(message="已保存")
