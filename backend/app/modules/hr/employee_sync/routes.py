"""员工档案多维表格同步 API（绑定配置 / 手动全量同步 / 培训脱敏名单）。"""

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import (
    HrAccessContext,
    get_hr_scope,
    require_hr_access,
    require_hr_basic,
)
from app.modules.hr.employee_sync import bitable_client as bitable
from app.modules.hr.employee_sync.bitable_client import clean_app_token, clean_table_id
from app.modules.hr.employee_sync.config import (
    KEY_APP_TOKEN,
    KEY_ENABLED,
    KEY_SOURCE_TABLE_ID,
    KEY_SOURCE_TABLE_NAME,
    EmployeeSyncConfig,
    load_config,
    save_config_values,
)
from app.modules.hr.employee_sync.mapping import COLUMN_MAP
from app.modules.hr.employee_sync.service import (
    EmployeeSyncService,
    SyncInProgressError,
)

logger = logging.getLogger(__name__)

# 管理动作统一权限；读取状态仅要求 HR 访问（员工档案页要给普通用户显示同步条）
router = APIRouter(prefix="/employee-sync", tags=["HR-员工档案同步"])
_MANAGE = Depends(require_hr_access("hr:settings:manage"))


class EmployeeSyncConfigInput(BaseModel):
    enabled: bool = Field(False, description="启用同步（员工档案转为只读展示）")
    app_token: str = Field("", description="飞书多维表格 Base 的 app_token")
    source_table_id: str = Field("", description="员工档案源数据表 table_id")


def _config_payload(cfg: EmployeeSyncConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "app_token": cfg.app_token,
        "source_table_id": cfg.source_table_id,
        "source_table_name": cfg.source_table_name,
        "is_ready": cfg.is_ready,
        "last_sync_at": cfg.last_sync_at or None,
        "last_stats": cfg.last_stats or None,
    }


def _column_report(field_names: list[str]) -> dict[str, Any]:
    """源表列 ↔ 系统字段的匹配结果（保存配置时反馈给前端）。"""
    mapped = [c for c in field_names if c in COLUMN_MAP]
    ignored = [c for c in field_names if c not in COLUMN_MAP]
    return {
        "mapped": mapped,
        "ignored": ignored,
        "has_employee_number": "工号" in mapped,
        "mapped_count": len(mapped),
    }


@router.get("/config", summary="读取员工档案同步配置")
async def get_sync_config(
    session: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = Depends(require_hr_basic),
) -> JSONResponse:
    cfg = await load_config(session)
    return success_response(data=_config_payload(cfg))


@router.put("/config", summary="保存同步配置（校验连通 + 订阅事件 + 列匹配报告）")
async def save_sync_config(
    payload: EmployeeSyncConfigInput,
    session: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = _MANAGE,
) -> JSONResponse:
    # 容忍粘贴完整链接/带查询串，清洗后再校验与入库
    app_token = clean_app_token(payload.app_token)
    source_table_id = clean_table_id(payload.source_table_id)

    if payload.enabled and (not app_token or not source_table_id):
        raise HTTPException(400, "启用同步前必须填写 app_token 和源数据表 table_id")

    table_name = ""
    column_report: dict[str, Any] = {"mapped": [], "ignored": [], "has_employee_number": False, "mapped_count": 0}
    subscribe_warning = ""
    if app_token and source_table_id:
        try:
            tables = await bitable.list_tables(app_token)
            if not tables:
                raise HTTPException(
                    400,
                    "应用已是该 Base 协作者，但读不到任何数据表（RolePermNotAllow）。"
                    "多半是 Base 开启了「高级权限」：请在 右上角「···」→ 高级权限 → "
                    f"协作者管理中，为应用 {bitable.active_app_id()} 授予数据表权限"
                    "（可编辑或可管理）；否则请把应用的文档权限改为「可编辑」。",
                )
            matched = next(
                (t for t in tables if str(t.get("table_id")) == source_table_id), None,
            )
            if matched is None:
                available = "、".join(
                    f"{t.get('name')}({t.get('table_id')})" for t in tables[:10]
                )
                raise HTTPException(
                    400,
                    f"Base 中不存在数据表 {source_table_id}。Base 内可用的数据表：{available}",
                )
            table_name = str(matched.get("name") or "")
            fields = await bitable.list_fields(app_token, source_table_id)
            column_report = _column_report(
                [str(f.get("field_name") or "") for f in fields],
            )
        except HTTPException:
            raise
        except bitable.BitableAPIError as exc:
            raise HTTPException(
                400,
                f"连接飞书多维表格失败：{exc}。"
                f"请确认该 Base 已共享给应用「{bitable.active_app_id()}」"
                f"（多维表格右上角「···」→ 添加文档应用，权限选可编辑）。",
            ) from exc

        # 事件订阅（增强能力）：走当前环境全局应用；无授权时降级 5 分钟对账，不阻断保存
        try:
            await bitable.subscribe_bitable(app_token)
        except bitable.BitableAPIError as exc:
            global_app = get_settings().FEISHU_APP_ID or "未配置"
            text = str(exc)
            if "scopes is required" in text or "99991672" in text:
                hint = (
                    f"当前环境全局应用「{global_app}」尚未开通订阅权限（scope），"
                    "按错误信息中的链接申请开通，并把 Base 共享给它后重新保存即可。"
                )
            else:
                hint = f"如需实时同步，请把 Base 也共享给当前环境的全局应用「{global_app}」。"
            subscribe_warning = f"实时事件订阅失败（已降级为 5 分钟对账模式）：{exc}。{hint}"
            logger.warning("员工档案同步事件订阅失败: %s", exc)

    values = {
        KEY_ENABLED: "true" if payload.enabled else "false",
        KEY_APP_TOKEN: app_token,
        KEY_SOURCE_TABLE_ID: source_table_id,
        KEY_SOURCE_TABLE_NAME: table_name,
    }
    await save_config_values(session, values)
    await session.commit()

    cfg = await load_config(session)
    data = _config_payload(cfg)
    data["column_report"] = column_report
    data["subscribe_warning"] = subscribe_warning or None
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
        page=max(page, 1), page_size=min(max(page_size, 1), 100),
        scoped_departments=scoped,
    )
    return success_response(data=rows, meta={
        "total": total, "page": page, "page_size": page_size,
        "scoped_departments": sorted(scoped) if scoped is not None else None,
    })


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
    concurrent_departments: str | None = None
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
