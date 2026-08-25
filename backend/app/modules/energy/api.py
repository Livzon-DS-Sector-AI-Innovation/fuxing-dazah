from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.energy import service
from app.modules.energy.adapters import ADAPTERS
from app.modules.energy.schemas import (
    AlertRecordProcessRequest,
    AlertRuleCandidate,
    ClientErrorLogRequest,
    CollectLogResponse,
    CollectSettingsResponse,
    CollectSettingsUpdate,
    CollectTriggerRequest,
    DailyReportSendRequest,
    EnergyAlertRecordResponse,
    EnergyAlertRuleCreate,
    EnergyAlertRuleResponse,
    EnergyAlertRuleUpdate,
    EnergyDailyPushConfigCreate,
    EnergyDailyPushConfigResponse,
    EnergyDailyPushConfigUpdate,
    EnergyDataDeleteRequest,
    EnergyDataResponse,
    EnergyDataUpdateRequest,
    EnergyDeviceConfigCreate,
    EnergyDeviceConfigResponse,
    EnergyDeviceConfigUpdate,
    EnergyNitrogenPushConfigCreate,
    EnergyNitrogenPushConfigResponse,
    EnergyNitrogenPushConfigUpdate,
    EnergyTypeConfigCreate,
    EnergyTypeConfigResponse,
    EnergyTypeConfigUpdate,
    EnergyWorkshopConfigCreate,
    EnergyWorkshopConfigResponse,
    EnergyWorkshopConfigUpdate,
    FillAlertReasonRequest,
    NitrogenReportSendRequest,
    PersonnelCandidate,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission
from app.shared.module_api import create_module_router
from app.shared.module_registry import MODULES_BY_CODE

logger = logging.getLogger(__name__)


async def _log_energy_request(request: Request) -> None:
    """记录每个 energy API 请求的方法和路径。"""
    logger.info(
        "[energy] %s %s | client=%s",
        request.method, request.url.path,
        request.client.host if request.client else "unknown",
    )


async def _capture_unhandled_error(request: Request) -> AsyncGenerator[None, None]:
    """捕获 energy 接口未处理异常并记录日志（仅 500 类，业务/校验异常跳过）。"""
    try:
        yield
    except Exception as exc:
        if isinstance(exc, (HTTPException, RequestValidationError)):
            raise
        logger.exception(
            "energy 接口未处理异常: %s %s | path_params=%s query_params=%s | %s: %s",
            request.method, request.url.path,
            dict(request.path_params), dict(request.query_params),
            type(exc).__name__, exc,
        )
        raise


_log_dep = Depends(_log_energy_request)
_error_dep = Depends(_capture_unhandled_error)

router = create_module_router(MODULES_BY_CODE["energy"])
router.dependencies.append(_log_dep)
router.dependencies.append(_error_dep)

device_router = APIRouter(dependencies=[_log_dep, _error_dep])
data_router = APIRouter(dependencies=[_log_dep, _error_dep])
collect_router = APIRouter(dependencies=[_log_dep, _error_dep])
alert_router = APIRouter(dependencies=[_log_dep, _error_dep])
alert_record_router = APIRouter(dependencies=[_log_dep, _error_dep])
alert_process_router = APIRouter(dependencies=[_log_dep, _error_dep])
type_config_router = APIRouter(dependencies=[_log_dep, _error_dep])
workshop_config_router = APIRouter(dependencies=[_log_dep, _error_dep])
daily_report_router = APIRouter(dependencies=[_log_dep, _error_dep])
nitrogen_report_router = APIRouter(dependencies=[_log_dep, _error_dep])


# ── 平台信息 ──


@router.get("/platforms", summary="获取已登记的平台列表")
async def list_platforms(
    user: User = Depends(require_permission("energy:device:read")),
) -> JSONResponse:
    data = [
        {"code": code, "name": adapter.platform_name}
        for code, adapter in ADAPTERS.items()
    ]
    return success_response(data)


@router.get("/departments", summary="获取部门列表（供数据源配置所属部门下拉使用）")
async def list_departments(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    data = await service.list_departments(db)
    return success_response(data)


@router.get("/equipment-options", summary="获取关联设备候选列表（来自设备台账）")
async def list_equipment_options(
    keyword: str | None = Query(default=None, description="设备名称/编号关键词"),
    ids: str | None = Query(default=None, description="设备ID列表（逗号分隔），用于编辑回显"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:device:read")),
) -> JSONResponse:
    """查询设备台账候选设备，供数据源「关联设备」下拉使用。

    传入 ids 时按 ID 批量回显；否则按 keyword 搜索。
    数据范围沿用设备台账（equipment:asset）权限配置。
    """
    if ids:
        id_list = [UUID(i) for i in ids.split(",") if i.strip()]
        options = await service.get_equipment_options_by_ids(db, id_list)
    else:
        options = await service.list_equipment_options(db, user, keyword=keyword)
    return success_response(options)


# ── 设备配置 ──


@device_router.post("", summary="新增设备配置")
async def create_device_config(
    data: EnergyDeviceConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:device:create")),
) -> JSONResponse:
    obj = await service.create_device_config(db, data)
    return success_response(
        EnergyDeviceConfigResponse.model_validate(obj).model_dump()
    )


@device_router.get("", summary="查询设备配置列表")
async def list_device_configs(
    platform_code: str | None = Query(default=None, description="平台标识"),
    energy_type: str | None = Query(default=None, description="能源类型"),
    workshop: str | None = Query(default=None, description="部门"),
    is_enabled: bool | None = Query(default=None, description="是否启用"),
    keyword: str | None = Query(default=None, description="设备名称关键词搜索"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:device:read")),
) -> JSONResponse:
    items, total = await service.list_device_configs(
        db,
        platform_code=platform_code,
        energy_type=energy_type,
        workshop=workshop,
        is_enabled=is_enabled,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    data = [EnergyDeviceConfigResponse.model_validate(i).model_dump() for i in items]
    return paginated_response(data, page, page_size, total)


@device_router.get("/{config_id}", summary="查询单个设备配置")
async def get_device_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:device:read")),
) -> JSONResponse:
    obj = await service.get_device_config(db, config_id)
    return success_response(
        EnergyDeviceConfigResponse.model_validate(obj).model_dump()
    )


@device_router.put("/{config_id}", summary="修改设备配置")
async def update_device_config(
    config_id: UUID,
    data: EnergyDeviceConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:device:update")),
) -> JSONResponse:
    obj = await service.update_device_config(db, config_id, data)
    return success_response(
        EnergyDeviceConfigResponse.model_validate(obj).model_dump()
    )


@device_router.delete("/{config_id}", summary="删除设备配置")
async def delete_device_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:device:delete")),
) -> JSONResponse:
    await service.delete_device_config(db, config_id)
    return success_response(None, message="删除成功")


# ── 能耗数据 ──


@data_router.get("", summary="查询能耗数据")
async def list_energy_data(
    device_config_id: UUID | None = Query(default=None, description="设备配置ID"),
    energy_type: str | None = Query(default=None, description="能源类型"),
    workshop: str | None = Query(default=None, description="部门"),
    start_time: str = Query(..., description="开始时间(ISO格式)"),
    end_time: str = Query(..., description="结束时间(ISO格式)"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:read")),
) -> JSONResponse:
    items, total = await service.list_energy_data(
        db,
        device_config_id=device_config_id,
        energy_type=energy_type,
        workshop=workshop,
        start_time=datetime.fromisoformat(start_time),
        end_time=datetime.fromisoformat(end_time),
        page=page,
        page_size=page_size,
    )
    data = [EnergyDataResponse.model_validate(i).model_dump() for i in items]
    return paginated_response(data, page, page_size, total)


@data_router.get("/history", summary="查询能耗数据历史明细（含设备信息）")
async def list_energy_data_history(
    device_config_id: UUID | None = Query(default=None, description="设备配置ID"),
    energy_type: str | None = Query(default=None, description="能源类型"),
    workshop: str | None = Query(default=None, description="部门"),
    keyword: str | None = Query(default=None, description="设备名称/编码搜索"),
    granularity: str | None = Query(default=None, pattern="^(daily|hourly)$", description="数据类型: daily=按天, hourly=按小时"),
    start_time: str | None = Query(default=None, description="开始时间(ISO格式)"),
    end_time: str | None = Query(default=None, description="结束时间(ISO格式)"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:read")),
) -> JSONResponse:
    """查询能耗数据历史明细，含设备名称、能源类型、所属部门等信息。"""
    items, total = await service.list_energy_data_history(
        db,
        device_config_id=device_config_id,
        energy_type=energy_type,
        workshop=workshop,
        keyword=keyword,
        granularity=granularity,
        start_time=datetime.fromisoformat(start_time) if start_time else None,
        end_time=datetime.fromisoformat(end_time) if end_time else None,
        page=page,
        page_size=page_size,
    )
    return paginated_response(items, page, page_size, total)


@data_router.delete("/{data_id}", summary="删除单条能耗数据")
async def delete_energy_data(
    data_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:delete")),
) -> JSONResponse:
    await service.delete_energy_data(db, data_id)
    return success_response(None, message="删除成功")


@data_router.put("/{data_id}", summary="修改能耗数据值")
async def update_energy_data(
    data_id: UUID,
    request: EnergyDataUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:delete")),
) -> JSONResponse:
    obj = await service.update_energy_data(db, data_id, request.value)
    return success_response(
        EnergyDataResponse.model_validate(obj).model_dump(),
        message="修改成功",
    )


@data_router.delete("", summary="批量删除能耗数据")
async def batch_delete_energy_data(
    request: EnergyDataDeleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:delete")),
) -> JSONResponse:
    count = await service.batch_delete_energy_data(db, [UUID(i) for i in request.ids])
    return success_response({"deleted_count": count}, message=f"已删除 {count} 条")


@data_router.get("/statistics", summary="能耗统计")
async def get_energy_statistics(
    group_by: str = Query(
        default="workshop", description="分组维度: workshop/production_line/device"
    ),
    energy_type: str | None = Query(default=None, description="能源类型"),
    start_time: str = Query(..., description="开始时间(ISO格式)"),
    end_time: str = Query(..., description="结束时间(ISO格式)"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:read")),
) -> JSONResponse:
    result = await service.get_energy_statistics(
        db,
        group_by=group_by,
        energy_type=energy_type,
        start_time=datetime.fromisoformat(start_time),
        end_time=datetime.fromisoformat(end_time),
    )
    return success_response(result)


# ── 采集管理 ──


@collect_router.post("/trigger", summary="手动触发采集")
async def trigger_collection(
    request: CollectTriggerRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:collect:trigger")),
) -> JSONResponse:
    result = await service.trigger_collection(db, request)
    return success_response(result, message="采集任务已执行")


@collect_router.get("/settings", summary="获取自动采集运行时设置")
async def get_collect_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:collect:trigger")),
) -> JSONResponse:
    """获取当前自动采集的启用状态和每日统一采集时间。"""
    result = await service.get_collect_settings(db)
    return success_response(CollectSettingsResponse(**result).model_dump())


@collect_router.put("/settings", summary="更新自动采集运行时设置")
async def update_collect_settings(
    data: CollectSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:collect:trigger")),
) -> JSONResponse:
    """更新自动采集的启用状态（内存）和每日统一采集时间（持久化 DB，重启保留）。"""
    result = await service.update_collect_settings(
        db,
        auto_collect_enabled=data.auto_collect_enabled,
        daily_collect_time=data.daily_collect_time,
    )
    return success_response(
        CollectSettingsResponse(**result).model_dump(), message="设置已更新"
    )


@collect_router.get("/logs", summary="查询采集日志")
async def list_collect_logs(
    platform_code: str | None = Query(default=None, description="平台标识"),
    status: str | None = Query(default=None, description="状态"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:collect_log:read")),
) -> JSONResponse:
    items, total = await service.list_collect_logs(
        db,
        platform_code=platform_code,
        status=status,
        page=page,
        page_size=page_size,
    )
    data = [CollectLogResponse.model_validate(i).model_dump() for i in items]
    return paginated_response(data, page, page_size, total)


@collect_router.delete("/logs", summary="清空采集日志历史")
async def clear_collect_logs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:collect_log:delete")),
) -> JSONResponse:
    count = await service.clear_collect_logs(db)
    return success_response({"deleted_count": count}, message=f"已清除 {count} 条采集日志")


@collect_router.get("/logs/{log_id}/detail", summary="查询采集日志详情")
async def get_collect_log_detail(
    log_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:collect_log:read")),
) -> JSONResponse:
    result = await service.get_collect_log_detail(db, log_id)
    return success_response(result)


# ── 能源总览 ──


@router.get("/overview", summary="能源总览数据")
async def get_energy_overview(
    energy_type: str | None = Query(default=None, description="能源类型筛选"),
    start_time: str = Query(..., description="开始时间(ISO格式)"),
    end_time: str = Query(..., description="结束时间(ISO格式)"),
    granularity: str = Query(default="hourly", pattern="^(hourly|daily)$", description="数据粒度: hourly/daily"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:read")),
) -> JSONResponse:
    result = await service.get_overview(
        db,
        start_time=datetime.fromisoformat(start_time),
        end_time=datetime.fromisoformat(end_time),
        energy_type=energy_type,
        granularity=granularity,
    )
    return success_response(result)


@router.get("/overview/price-category", summary="峰谷用电分布")
async def get_price_category_distribution(
    start_time: str = Query(..., description="开始时间(ISO格式)"),
    end_time: str = Query(..., description="结束时间(ISO格式)"),
    energy_type: str | None = Query(default=None, description="能源类型筛选"),
    workshop: str | None = Query(default=None, description="部门筛选"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:read")),
) -> JSONResponse:
    result = await service.get_price_category_distribution(
        db,
        start_time=datetime.fromisoformat(start_time),
        end_time=datetime.fromisoformat(end_time),
        energy_type=energy_type,
        workshop=workshop,
    )
    return success_response(result)


# ── 峰谷时段规则配置 ──


@router.get("/price-periods", summary="查询峰谷时段规则")
async def list_price_periods(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:read")),
) -> JSONResponse:
    items = await service.list_price_periods(db)
    return success_response(items)


@router.post("/price-periods", summary="新增峰谷时段规则")
async def create_price_period(
    data: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:read")),
) -> JSONResponse:
    result = await service.create_price_period(
        db,
        category=data["category"],
        start_hour=data["start_hour"],
        end_hour=data["end_hour"],
        months=data["months"],
    )
    return success_response(result)


@router.delete("/price-periods/{period_id}", summary="删除峰谷时段规则")
async def delete_price_period(
    period_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:read")),
) -> JSONResponse:
    ok = await service.delete_price_period(db, period_id)
    if not ok:
        return JSONResponse({"code": 404, "message": "规则不存在"}, status_code=404)
    return success_response({"deleted": True})


@router.post("/price-periods/reset", summary="重置为默认峰谷规则")
async def reset_price_periods(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:read")),
) -> JSONResponse:
    items = await service.reset_price_periods(db)
    return success_response(items)


# ── 预警规则 ──


@alert_router.post("", summary="新增预警规则")
async def create_alert_rule(
    data: EnergyAlertRuleCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:create")),
) -> JSONResponse:
    obj = await service.create_alert_rule(db, data)
    return success_response(
        EnergyAlertRuleResponse.model_validate(obj).model_dump()
    )


@alert_router.get("", summary="查询预警规则列表")
async def list_alert_rules(
    energy_type: str | None = Query(default=None, description="能源类型"),
    alert_level: str | None = Query(default=None, description="预警等级"),
    is_enabled: bool | None = Query(default=None, description="是否启用"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:read")),
) -> JSONResponse:
    items, total = await service.list_alert_rules(
        db,
        energy_type=energy_type,
        alert_level=alert_level,
        is_enabled=is_enabled,
        page=page,
        page_size=page_size,
    )
    data = [EnergyAlertRuleResponse.model_validate(i).model_dump() for i in items]
    return paginated_response(data, page, page_size, total)


@alert_router.get("/{rule_id}", summary="查询单个预警规则")
async def get_alert_rule(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:read")),
) -> JSONResponse:
    obj = await service.get_alert_rule(db, rule_id)
    return success_response(
        EnergyAlertRuleResponse.model_validate(obj).model_dump()
    )


@alert_router.put("/{rule_id}", summary="修改预警规则")
async def update_alert_rule(
    rule_id: UUID,
    data: EnergyAlertRuleUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:update")),
) -> JSONResponse:
    obj = await service.update_alert_rule(db, rule_id, data)
    return success_response(
        EnergyAlertRuleResponse.model_validate(obj).model_dump()
    )


@alert_router.delete("/{rule_id}", summary="删除预警规则")
async def delete_alert_rule(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:delete")),
) -> JSONResponse:
    await service.delete_alert_rule(db, rule_id)
    return success_response(None, message="删除成功")


# ── 预警记录 ──


@alert_record_router.get("", summary="查询预警记录列表")
async def list_alert_records(
    energy_type: str | None = Query(default=None, description="能源类型"),
    alert_level: str | None = Query(default=None, description="预警等级"),
    status: str | None = Query(default=None, description="处理状态"),
    start_time: str | None = Query(default=None, description="开始时间(ISO格式)"),
    end_time: str | None = Query(default=None, description="结束时间(ISO格式)"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:read")),
) -> JSONResponse:
    items, total = await service.list_alert_records(
        db,
        energy_type=energy_type,
        alert_level=alert_level,
        status=status,
        start_time=datetime.fromisoformat(start_time) if start_time else None,
        end_time=datetime.fromisoformat(end_time) if end_time else None,
        page=page,
        page_size=page_size,
    )
    data = [EnergyAlertRecordResponse.model_validate(i).model_dump() for i in items]
    return paginated_response(data, page, page_size, total)


@alert_record_router.put("/{record_id}/process", summary="处理预警记录")
async def process_alert_record(
    record_id: UUID,
    request: AlertRecordProcessRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:update")),
) -> JSONResponse:
    obj = await service.process_alert_record(db, record_id, request)
    return success_response(
        EnergyAlertRecordResponse.model_validate(obj).model_dump(),
        message="处理完成",
    )


# ── 预警处理（车间预警审核流程） ──


@alert_process_router.get("", summary="查询待处理车间预警列表")
async def list_alert_process(
    status: str | None = Query(default=None, description="状态筛选: pending / rejected"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:read")),
) -> JSONResponse:
    """查询车间预警记录（workshop IS NOT NULL），用于预警处理页面。"""
    items, total = await service.list_alert_records(
        db,
        status=status,
        workshop_not_null=True,
        page=page,
        page_size=page_size,
    )
    # 批量查询车间配置，获取负责人信息
    workshops = list({i.workshop for i in items if i.workshop})
    heads_map: dict[str, list[dict[str, str]]] = {}
    if workshops:
        from app.modules.energy.repository import get_workshop_config_by_workshop
        for ws in workshops:
            cfg = await get_workshop_config_by_workshop(db, ws)
            if cfg and cfg.heads:
                heads_map[ws] = cfg.heads

    data = []
    for i in items:
        d = EnergyAlertRecordResponse.model_validate(i).model_dump()
        d["heads"] = heads_map.get(i.workshop or "", [])
        data.append(d)
    return paginated_response(data, page, page_size, total)


@alert_process_router.put("/{record_id}/reason", summary="填写预警原因")
async def fill_alert_reason(
    record_id: UUID,
    request: FillAlertReasonRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:read")),
) -> JSONResponse:
    """任意用户填写车间预警异常原因。"""
    obj = await service.fill_alert_reason(db, record_id, request.reason)
    return success_response(
        EnergyAlertRecordResponse.model_validate(obj).model_dump(),
        message="原因已填写",
    )


@alert_process_router.put("/{record_id}/approve", summary="管理员通过预警")
async def approve_alert_record(
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:process:approve")),
) -> JSONResponse:
    """管理员审核通过 → 软删除。"""
    await service.approve_alert_record(db, record_id)
    return success_response(None, message="已通过")


@alert_process_router.put("/{record_id}/reject", summary="管理员驳回预警")
async def reject_alert_record(
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:process:reject")),
) -> JSONResponse:
    """管理员驳回 → status=rejected + 重新飞书通知。"""
    obj = await service.reject_alert_record(db, record_id)
    return success_response(
        EnergyAlertRecordResponse.model_validate(obj).model_dump(),
        message="已驳回并重新通知",
    )


# ── 能源类型可视化配置 ──


@type_config_router.get("", summary="获取能源类型配置列表")
async def list_type_configs(
    is_enabled: bool | None = Query(default=None, description="筛选启用状态"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:type_config:read")),
) -> JSONResponse:
    items, total = await service.list_type_configs(
        db, is_enabled=is_enabled, page=page, page_size=page_size
    )
    data = [EnergyTypeConfigResponse.model_validate(i).model_dump() for i in items]
    return paginated_response(data, page, page_size, total)


@type_config_router.get("/enabled", summary="获取所有启用的能源类型（供前端下拉/可视化使用）")
async def list_enabled_type_configs(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """无需权限检查，供可视化页面公开使用。"""
    items = await service.list_enabled_type_configs(db)
    data = [EnergyTypeConfigResponse.model_validate(i).model_dump() for i in items]
    return success_response(data)


@type_config_router.post("", summary="新增能源类型配置")
async def create_type_config(
    data: EnergyTypeConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:type_config:create")),
) -> JSONResponse:
    obj = await service.create_type_config(db, data)
    return success_response(
        EnergyTypeConfigResponse.model_validate(obj).model_dump()
    )


@type_config_router.get("/{config_id}", summary="查询单个能源类型配置")
async def get_type_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:type_config:read")),
) -> JSONResponse:
    obj = await service.get_type_config(db, config_id)
    return success_response(
        EnergyTypeConfigResponse.model_validate(obj).model_dump()
    )


@type_config_router.put("/{config_id}", summary="修改能源类型配置")
async def update_type_config(
    config_id: UUID,
    data: EnergyTypeConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:type_config:update")),
) -> JSONResponse:
    obj = await service.update_type_config(db, config_id, data)
    return success_response(
        EnergyTypeConfigResponse.model_validate(obj).model_dump()
    )


@type_config_router.delete("/{config_id}", summary="删除能源类型配置")
async def delete_type_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:type_config:delete")),
) -> JSONResponse:
    await service.delete_type_config(db, config_id)
    return success_response(None, message="删除成功")


# ── 车间预警配置 ──


@workshop_config_router.post("", summary="新增车间预警配置")
async def create_workshop_config(
    data: EnergyWorkshopConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:workshop_config:create")),
) -> JSONResponse:
    obj = await service.create_workshop_config(db, data)
    return success_response(
        EnergyWorkshopConfigResponse.model_validate(obj).model_dump()
    )


@workshop_config_router.get("", summary="查询车间预警配置列表")
async def list_workshop_configs(
    is_enabled: bool | None = Query(default=None, description="是否启用"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:workshop_config:read")),
) -> JSONResponse:
    items, total = await service.list_workshop_configs(
        db, is_enabled=is_enabled, page=page, page_size=page_size
    )
    data = [EnergyWorkshopConfigResponse.model_validate(i).model_dump() for i in items]
    return paginated_response(data, page, page_size, total)


@workshop_config_router.get("/personnel-candidates", summary="获取可选负责人列表（从 identity.users 查询）")
async def get_personnel_candidates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:workshop_config:read")),
) -> JSONResponse:
    """从平台 identity.users 查询所有用户，作为车间预警负责人候选人列表。"""
    candidates = await service.get_personnel_candidates(db)
    return success_response(
        [PersonnelCandidate(**c).model_dump(mode="json") for c in candidates]
    )


@workshop_config_router.get("/available-rules", summary="获取可选预警规则列表（供车间配置下拉框）")
async def get_available_alert_rules(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:workshop_config:read")),
) -> JSONResponse:
    """返回用户手动创建的、已启用的预警规则列表，供车间配置关联使用。"""
    rules = await service.list_available_alert_rules(db)
    return success_response(
        [AlertRuleCandidate.model_validate(r).model_dump() for r in rules]
    )


@workshop_config_router.get("/workshop-options", summary="获取可选设备配置列表（供车间配置下拉框，可按能源类型过滤）")
async def get_workshop_options(
    energy_type: str | None = Query(default=None, description="按能源类型过滤（可选）"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:workshop_config:read")),
) -> JSONResponse:
    """返回已启用设备配置列表，每项包含 device_name（展示用）和 workshop（存储用）。
    可选按能源类型过滤，未选择时返回全部。"""
    options = await service.list_workshop_options(db, energy_type)
    return success_response(options)


@workshop_config_router.get("/{config_id}", summary="查询单个车间预警配置")
async def get_workshop_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:workshop_config:read")),
) -> JSONResponse:
    obj = await service.get_workshop_config(db, config_id)
    return success_response(
        EnergyWorkshopConfigResponse.model_validate(obj).model_dump()
    )


@workshop_config_router.put("/{config_id}", summary="修改车间预警配置")
async def update_workshop_config(
    config_id: UUID,
    data: EnergyWorkshopConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:workshop_config:update")),
) -> JSONResponse:
    obj = await service.update_workshop_config(db, config_id, data)
    return success_response(
        EnergyWorkshopConfigResponse.model_validate(obj).model_dump()
    )


@workshop_config_router.delete("/{config_id}", summary="删除车间预警配置")
async def delete_workshop_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:workshop_config:delete")),
) -> JSONResponse:
    await service.delete_workshop_config(db, config_id)
    return success_response(None, message="删除成功")


# ── 能源总耗推送配置 ──


@daily_report_router.post("/configs", summary="新增能源总耗推送配置")
async def create_daily_push_config(
    data: EnergyDailyPushConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:daily_report:create")),
) -> JSONResponse:
    obj = await service.create_daily_push_config(db, data)
    return success_response(
        EnergyDailyPushConfigResponse.model_validate(obj).model_dump()
    )


@daily_report_router.get("/configs", summary="查询能源总耗推送配置列表")
async def list_daily_push_configs(
    is_enabled: bool | None = Query(default=None, description="是否启用"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:daily_report:read")),
) -> JSONResponse:
    items, total = await service.list_daily_push_configs(
        db, is_enabled=is_enabled, page=page, page_size=page_size
    )
    data = [EnergyDailyPushConfigResponse.model_validate(i).model_dump() for i in items]
    return paginated_response(data, page, page_size, total)


@daily_report_router.get("/configs/{config_id}", summary="查询单个能源总耗推送配置")
async def get_daily_push_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:daily_report:read")),
) -> JSONResponse:
    obj = await service.get_daily_push_config(db, config_id)
    return success_response(
        EnergyDailyPushConfigResponse.model_validate(obj).model_dump()
    )


@daily_report_router.put("/configs/{config_id}", summary="修改能源总耗推送配置")
async def update_daily_push_config(
    config_id: UUID,
    data: EnergyDailyPushConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:daily_report:update")),
) -> JSONResponse:
    obj = await service.update_daily_push_config(db, config_id, data)
    return success_response(
        EnergyDailyPushConfigResponse.model_validate(obj).model_dump()
    )


@daily_report_router.delete("/configs/{config_id}", summary="删除能源总耗推送配置")
async def delete_daily_push_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:daily_report:delete")),
) -> JSONResponse:
    await service.delete_daily_push_config(db, config_id)
    return success_response(None, message="删除成功")


@daily_report_router.post("/send", summary="手动触发能源日耗推送")
async def send_daily_report(
    request: DailyReportSendRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:daily_report:send")),
) -> JSONResponse:
    from datetime import datetime as dt
    target_date = dt.fromisoformat(request.target_date)
    result = await service.send_daily_energy_report(
        db, UUID(request.config_id), target_date
    )
    return success_response(result, message=result.get("message", ""))


@daily_report_router.get("/personnel-candidates", summary="获取可选接收人列表")
async def get_daily_push_personnel_candidates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:daily_report:read")),
) -> JSONResponse:
    """从平台 identity.users 查询所有用户，作为推送接收人候选人列表。"""
    candidates = await service.get_personnel_candidates(db)
    return success_response(
        [PersonnelCandidate(**c).model_dump(mode="json") for c in candidates]
    )


# ── 氮气月度推送配置 ──


@nitrogen_report_router.post("/configs", summary="新增氮气月度推送配置")
async def create_nitrogen_push_config(
    data: EnergyNitrogenPushConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:nitrogen_report:create")),
) -> JSONResponse:
    obj = await service.create_nitrogen_push_config(db, data)
    return success_response(
        EnergyNitrogenPushConfigResponse.model_validate(obj).model_dump()
    )


@nitrogen_report_router.get("/configs", summary="查询氮气月度推送配置列表")
async def list_nitrogen_push_configs(
    is_enabled: bool | None = Query(default=None, description="是否启用"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:nitrogen_report:read")),
) -> JSONResponse:
    items, total = await service.list_nitrogen_push_configs(
        db, is_enabled=is_enabled, page=page, page_size=page_size
    )
    data = [EnergyNitrogenPushConfigResponse.model_validate(i).model_dump() for i in items]
    return paginated_response(data, page, page_size, total)


@nitrogen_report_router.get("/configs/{config_id}", summary="查询单个氮气月度推送配置")
async def get_nitrogen_push_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:nitrogen_report:read")),
) -> JSONResponse:
    obj = await service.get_nitrogen_push_config(db, config_id)
    return success_response(
        EnergyNitrogenPushConfigResponse.model_validate(obj).model_dump()
    )


@nitrogen_report_router.put("/configs/{config_id}", summary="修改氮气月度推送配置")
async def update_nitrogen_push_config(
    config_id: UUID,
    data: EnergyNitrogenPushConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:nitrogen_report:update")),
) -> JSONResponse:
    obj = await service.update_nitrogen_push_config(db, config_id, data)
    return success_response(
        EnergyNitrogenPushConfigResponse.model_validate(obj).model_dump()
    )


@nitrogen_report_router.delete("/configs/{config_id}", summary="删除氮气月度推送配置")
async def delete_nitrogen_push_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:nitrogen_report:delete")),
) -> JSONResponse:
    await service.delete_nitrogen_push_config(db, config_id)
    return success_response(None, message="删除成功")


@nitrogen_report_router.post("/send", summary="手动触发氮气月度推送")
async def send_nitrogen_report(
    request: NitrogenReportSendRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:nitrogen_report:send")),
) -> JSONResponse:
    from datetime import datetime as dt
    target_date = dt.fromisoformat(request.target_date)
    result = await service.send_nitrogen_monthly_report(
        db, UUID(request.config_id), target_date
    )
    return success_response(result, message=result.get("message", ""))


@nitrogen_report_router.get("/personnel-candidates", summary="获取可选接收人列表")
async def get_nitrogen_push_personnel_candidates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:nitrogen_report:read")),
) -> JSONResponse:
    """从平台 identity.users 查询所有用户，作为推送接收人候选人列表。"""
    candidates = await service.get_personnel_candidates(db)
    return success_response(
        [PersonnelCandidate(**c).model_dump(mode="json") for c in candidates]
    )


@router.post("/client-error-logs", summary="上报前端错误日志")
async def report_client_error(data: ClientErrorLogRequest) -> JSONResponse:
    """接收 energy 前端上报的错误，记录到日志文件（不落库）。

    无需登录校验：错误上报本身应在鉴权异常时也能正常工作。
    请求来源 IP 由 _log_energy_request 统一记录。
    """
    logger.error(
        "energy 前端报错: page=%s | api=%s status=%s | component=%s | %s%s",
        data.page_url or "-",
        data.api_url or "-",
        data.status if data.status is not None else "-",
        data.component or "-",
        data.message,
        f"\n{data.stack}" if data.stack else "",
    )
    return success_response(None, message="已记录")


router.include_router(device_router, prefix="/devices")
router.include_router(data_router, prefix="/data")
router.include_router(collect_router, prefix="/collect")
router.include_router(alert_router, prefix="/alerts/rules")
router.include_router(alert_record_router, prefix="/alerts/records")
router.include_router(alert_process_router, prefix="/alerts/process")
router.include_router(type_config_router, prefix="/type-configs")
router.include_router(workshop_config_router, prefix="/workshop-configs")
router.include_router(daily_report_router, prefix="/daily-report")
router.include_router(nitrogen_report_router, prefix="/nitrogen-report")
