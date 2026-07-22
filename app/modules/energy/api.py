from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.energy import service
from app.modules.energy.adapters import ADAPTERS
from app.modules.energy.collect_settings import (
    get_auto_collect_enabled,
    get_auto_collect_interval_seconds,
    set_auto_collect_enabled,
    set_auto_collect_interval_seconds,
)
from app.modules.energy.schemas import (
    AlertRecordProcessRequest,
    CollectLogResponse,
    CollectSettingsResponse,
    CollectSettingsUpdate,
    CollectTriggerRequest,
    EnergyAlertRecordResponse,
    EnergyAlertRuleCreate,
    EnergyAlertRuleResponse,
    EnergyAlertRuleUpdate,
    EnergyDataDeleteRequest,
    EnergyDataResponse,
    EnergyDeviceConfigCreate,
    EnergyDeviceConfigResponse,
    EnergyDeviceConfigUpdate,
    EnergyTypeConfigCreate,
    EnergyTypeConfigResponse,
    EnergyTypeConfigUpdate,
    EnergyWorkshopConfigCreate,
    EnergyWorkshopConfigResponse,
    EnergyWorkshopConfigUpdate,
    PersonnelCandidate,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission
from app.shared.module_api import create_module_router
from app.shared.module_registry import MODULES_BY_CODE

import logging

logger = logging.getLogger(__name__)


async def _log_energy_request(request: Request) -> None:
    """记录每个 energy API 请求的方法和路径。"""
    logger.info(
        "[energy] %s %s | client=%s",
        request.method, request.url.path,
        request.client.host if request.client else "unknown",
    )


_log_dep = Depends(_log_energy_request)

router = create_module_router(MODULES_BY_CODE["energy"])
router.dependencies.append(_log_dep)

device_router = APIRouter(dependencies=[_log_dep])
data_router = APIRouter(dependencies=[_log_dep])
collect_router = APIRouter(dependencies=[_log_dep])
alert_router = APIRouter(dependencies=[_log_dep])
alert_record_router = APIRouter(dependencies=[_log_dep])
type_config_router = APIRouter(dependencies=[_log_dep])
workshop_config_router = APIRouter(dependencies=[_log_dep])


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


@router.get("/equipments", summary="获取设备台账列表（供数据源配置关联设备下拉使用）")
async def list_equipments(
    keyword: str | None = Query(default=None, description="设备名称/编号搜索"),
    status: str | None = Query(default=None, description="设备状态筛选"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """获取设备台账中在用的设备列表，供能源数据源配置关联设备使用。"""
    items, total = await service.list_equipments_for_select(
        db, keyword=keyword, status=status, page=page, page_size=page_size
    )
    return paginated_response(items, page, page_size, total)


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
    user: User = Depends(require_permission("energy:collect:trigger")),
) -> JSONResponse:
    """获取当前自动采集的启用状态和间隔设置。"""
    return success_response(
        CollectSettingsResponse(
            auto_collect_enabled=get_auto_collect_enabled(),
            auto_collect_interval_seconds=get_auto_collect_interval_seconds(),
        ).model_dump()
    )


@collect_router.put("/settings", summary="更新自动采集运行时设置")
async def update_collect_settings(
    data: CollectSettingsUpdate,
    user: User = Depends(require_permission("energy:collect:trigger")),
) -> JSONResponse:
    """运行时更新自动采集的启用状态或间隔（无需重启）。"""
    if data.auto_collect_enabled is not None:
        set_auto_collect_enabled(data.auto_collect_enabled)
    if data.auto_collect_interval_seconds is not None:
        set_auto_collect_interval_seconds(data.auto_collect_interval_seconds)
    return success_response(
        CollectSettingsResponse(
            auto_collect_enabled=get_auto_collect_enabled(),
            auto_collect_interval_seconds=get_auto_collect_interval_seconds(),
        ).model_dump(),
        message="设置已更新",
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


router.include_router(device_router, prefix="/devices")
router.include_router(data_router, prefix="/data")
router.include_router(collect_router, prefix="/collect")
router.include_router(alert_router, prefix="/alerts/rules")
router.include_router(alert_record_router, prefix="/alerts/records")
router.include_router(type_config_router, prefix="/type-configs")
router.include_router(workshop_config_router, prefix="/workshop-configs")
