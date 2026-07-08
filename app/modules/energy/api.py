from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import error_response, paginated_response, success_response
from app.modules.energy import service
from app.modules.energy.adapters import ADAPTERS
from app.modules.energy.schemas import (
    AlertRecordProcessRequest,
    CollectLogResponse,
    CollectTriggerRequest,
    EnergyAlertRecordResponse,
    EnergyAlertRuleCreate,
    EnergyAlertRuleResponse,
    EnergyAlertRuleUpdate,
    EnergyDataResponse,
    EnergyDeviceConfigCreate,
    EnergyDeviceConfigResponse,
    EnergyDeviceConfigUpdate,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission
from app.shared.module_api import create_module_router
from app.shared.module_registry import MODULES_BY_CODE

router = create_module_router(MODULES_BY_CODE["energy"])
device_router = APIRouter()
data_router = APIRouter()
collect_router = APIRouter()
alert_router = APIRouter()
alert_record_router = APIRouter()


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


@router.get("/departments", summary="获取部门列表（供数据源配置所属车间下拉使用）")
async def list_departments(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    data = await service.list_departments(db)
    return success_response(data)


@router.get("/visualization/data", summary="获取能耗可视化数据（飞书多维表格，Redis 缓存 5min）")
async def get_visualization_data(
    energy_type: str | None = Query(default=None, description="能源类型，不传返回全部"),
) -> JSONResponse:
    import json

    from app.core.redis import cache_get, cache_set
    from app.modules.energy.feishu.bitable_client import EnergyBitableClient, TABLE_MAP

    if energy_type and energy_type not in TABLE_MAP:
        return error_response(f"未知能源类型: {energy_type}", status_code=400)

    cache_key = f"viz:{energy_type or 'all'}"

    # ── Redis 缓存 ──
    cached = await cache_get(cache_key)
    if cached is not None:
        return success_response(json.loads(cached))

    # ── 缓存未命中，从飞书拉取 ──
    tables = {energy_type: TABLE_MAP[energy_type]} if energy_type else TABLE_MAP

    import asyncio
    async def _fetch(et: str, tid: str) -> tuple[str, dict[str, Any]]:
        client = EnergyBitableClient(tid)
        return et, {
            "fields": await client.list_fields(),
            "records": await client.fetch_all_records(),
        }

    result: dict[str, Any] = {}
    tasks = [_fetch(et, tid) for et, tid in tables.items()]
    for coro in asyncio.as_completed(tasks):
        et, data = await coro
        result[et] = data

    await cache_set(cache_key, json.dumps(result, ensure_ascii=False), ex=300)

    return success_response(result)


# ── 设备配置 ──


@device_router.post("", summary="新增设备配置")
async def create_device_config(
    data: EnergyDeviceConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:device:manage")),
) -> JSONResponse:
    obj = await service.create_device_config(db, data)
    return success_response(
        EnergyDeviceConfigResponse.model_validate(obj).model_dump()
    )


@device_router.get("", summary="查询设备配置列表")
async def list_device_configs(
    platform_code: str | None = Query(default=None, description="平台标识"),
    energy_type: str | None = Query(default=None, description="能源类型"),
    workshop: str | None = Query(default=None, description="车间"),
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
    user: User = Depends(require_permission("energy:device:manage")),
) -> JSONResponse:
    obj = await service.update_device_config(db, config_id, data)
    return success_response(
        EnergyDeviceConfigResponse.model_validate(obj).model_dump()
    )


@device_router.delete("/{config_id}", summary="删除设备配置")
async def delete_device_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:device:manage")),
) -> JSONResponse:
    await service.delete_device_config(db, config_id)
    return success_response(None, message="删除成功")


# ── 能耗数据 ──


@data_router.get("", summary="查询能耗数据")
async def list_energy_data(
    device_config_id: UUID | None = Query(default=None, description="设备配置ID"),
    energy_type: str | None = Query(default=None, description="能源类型"),
    workshop: str | None = Query(default=None, description="车间"),
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
    user: User = Depends(require_permission("energy:device:manage")),
) -> JSONResponse:
    result = await service.trigger_collection(db, request)
    return success_response(result, message="采集任务已执行")


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


@collect_router.get("/logs/{log_id}/detail", summary="查询采集日志详情")
async def get_collect_log_detail(
    log_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:collect_log:read")),
) -> JSONResponse:
    result = await service.get_collect_log_detail(db, log_id)
    return success_response(result)


@collect_router.get("/history", summary="查询采集历史")
async def list_collect_history(
    platform_code: str = Query(default="zhiheng", description="平台标识"),
    energy_type: str | None = Query(default=None, description="能源类型，不传则不过滤"),
    device_config_id: UUID | None = Query(default=None, description="数据源ID"),
    start_date: str = Query(..., description="开始日期(YYYY-MM-DD)"),
    end_date: str = Query(..., description="结束日期(YYYY-MM-DD)"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await service.get_collect_history(
        db,
        platform_code=platform_code,
        energy_type=energy_type,
        device_config_id=device_config_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )
    return paginated_response(items, page, page_size, total)


# ── 能源总览 ──


@router.get("/overview", summary="能源总览数据")
async def get_energy_overview(
    energy_type: str | None = Query(default=None, description="能源类型筛选"),
    start_time: str = Query(..., description="开始时间(ISO格式)"),
    end_time: str = Query(..., description="结束时间(ISO格式)"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:overview:read")),
) -> JSONResponse:
    result = await service.get_overview(
        db,
        start_time=datetime.fromisoformat(start_time),
        end_time=datetime.fromisoformat(end_time),
        energy_type=energy_type,
    )
    return success_response(result)


# ── 预警规则 ──


@alert_router.post("", summary="新增预警规则")
async def create_alert_rule(
    data: EnergyAlertRuleCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:manage")),
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
    user: User = Depends(require_permission("energy:alert:manage")),
) -> JSONResponse:
    obj = await service.update_alert_rule(db, rule_id, data)
    return success_response(
        EnergyAlertRuleResponse.model_validate(obj).model_dump()
    )


@alert_router.delete("/{rule_id}", summary="删除预警规则")
async def delete_alert_rule(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("energy:alert:manage")),
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
    user: User = Depends(require_permission("energy:alert:manage")),
) -> JSONResponse:
    obj = await service.process_alert_record(db, record_id, request)
    return success_response(
        EnergyAlertRecordResponse.model_validate(obj).model_dump(),
        message="处理完成",
    )


router.include_router(device_router, prefix="/devices")
router.include_router(data_router, prefix="/data")
router.include_router(collect_router, prefix="/collect")
router.include_router(alert_router, prefix="/alerts/rules")
router.include_router(alert_record_router, prefix="/alerts/records")
