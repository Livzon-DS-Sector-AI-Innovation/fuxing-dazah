"""仓库模块系统配置管理 API（设计稿 warehouse-system-config-design.md §9）。

全部端点 require_permission（read 查 / update 改），配置中心写路径即时生效
（store invalidate），审计 append-only 且密钥脱敏。
"""

from __future__ import annotations

import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.warehouse.ai_audit.models import AiCallAudit
from app.modules.warehouse.ai_config import registry
from app.modules.warehouse.ai_config.scenario_store import scenario_store
from app.modules.warehouse.ai_config.store import store as ai_store
from app.modules.warehouse.bitable_config.store import bitable_store
from app.modules.warehouse.models import (
    AiConfigAudit,
    AiScenarioConfigAudit,
    BitableConfigAudit,
    RuntimeConfigAudit,
    SchedulerConfigAudit,
    WarehouseConfirmRequest,
    WarehousePushLog,
    WarehousePushTaskAudit,
)
from app.modules.warehouse.ops_config.runtime_store import runtime_store
from app.modules.warehouse.ops_config.scheduler_store import scheduler_store
from app.modules.warehouse.push_center import engine
from app.modules.warehouse.push_center.store import push_store
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

system_config_router = APIRouter()


def _map_store_error(exc: ValueError) -> HTTPException:
    """store 校验错误 → HTTP：未知 x → 404；其余 → 422（对齐 safety 语义）。"""
    message = str(exc)
    if message.startswith(("未知 profile", "未知场景", "未知参数", "未知表", "未知任务")):
        return HTTPException(status_code=404, detail=message)
    return HTTPException(status_code=422, detail=message)


def _serialize_profile(view: Any) -> dict[str, Any]:
    """API 回显视图：config 中真实 api_key 一律置空（脱敏值见 api_key_masked 字段）。"""
    data = asdict(view)
    data["config"]["api_key"] = ""
    return data


# ── AI 模型配置 ──


@system_config_router.get("/system-config/ai-models", summary="AI 模型配置总览（脱敏）")
async def list_ai_models(
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    views = [_serialize_profile(ai_store.get_profile(p)) for p in registry.PROFILE_KEYS]
    return success_response({"profiles": views})


@system_config_router.put("/system-config/ai-models/{profile}", summary="更新 AI 模型配置")
async def update_ai_model(
    profile: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:update")),
) -> JSONResponse:
    try:
        view = await ai_store.set_profile(
            db, profile, payload, operator_name=user.name
        )
    except ValueError as exc:
        raise _map_store_error(exc) from exc
    return success_response(
        _serialize_profile(view), message="配置已保存，实时生效"
    )


@system_config_router.get("/system-config/ai-models/audits", summary="AI 模型配置变更审计")
async def list_ai_model_audits(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(AiConfigAudit)
            .order_by(AiConfigAudit.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return success_response({
        "audits": [
            {
                "id": str(r.id),
                "profile": r.profile,
                "action": r.action,
                "before_json": r.before_json,
                "after_json": r.after_json,
                "operator_name": r.operator_name,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    })


@system_config_router.post("/system-config/ai-models/test", summary="AI 模型连通性探测")
async def test_ai_model(
    payload: dict[str, Any],
    user: User = Depends(require_permission("warehouse:system-config:update")),
) -> JSONResponse:
    """对模型配置做一次真实调用探测（不落库、不写审计）。

    body 仅传 profile 时探测已存合并配置；可另传 base_url/api_key/model
    覆盖（探测配置页尚未保存的草稿值）。
    """
    profile = str(payload.get("profile") or "")
    if not profile:
        raise HTTPException(status_code=422, detail="缺少 profile")
    try:
        config = ai_store.get_profile_config(profile)
    except ValueError as exc:
        raise _map_store_error(exc) from exc
    for key in ("base_url", "api_key", "model"):
        override = str(payload.get(key) or "").strip()
        if override:
            config[key] = override
    if not config.get("api_key") or not config.get("base_url") or not config.get("model"):
        raise HTTPException(
            status_code=422,
            detail="该 profile 的 api_key/base_url/model 尚不完整，请先补全配置",
        )
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                config["base_url"].rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {config['api_key']}"},
                json={
                    "model": config["model"],
                    "messages": [{"role": "user", "content": "连通性测试，回复：正常"}],
                    "max_tokens": 256,
                    "temperature": 0.0,
                },
            )
    except httpx.HTTPError as exc:
        return success_response({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    latency_ms = int((time.perf_counter() - start) * 1000)
    if resp.status_code != 200:
        return success_response({
            "ok": False, "status_code": resp.status_code,
            "error": resp.text[:300], "latency_ms": latency_ms,
        })
    data = resp.json()
    return success_response({
        "ok": True, "model": data.get("model"), "latency_ms": latency_ms,
        "usage": data.get("usage"),
    })


# ── AI 场景配置 ──


@system_config_router.get("/system-config/ai-scenarios", summary="AI 场景配置总览")
async def list_ai_scenarios(
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    views = [asdict(v) for v in scenario_store.iter_scenario_views()]
    return success_response({"scenarios": views})


@system_config_router.put("/system-config/ai-scenarios/{scenario}", summary="更新 AI 场景配置")
async def update_ai_scenario(
    scenario: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:update")),
) -> JSONResponse:
    try:
        view = await scenario_store.set_scenario(
            db, scenario, payload, operator_name=user.name
        )
    except ValueError as exc:
        raise _map_store_error(exc) from exc
    return success_response(asdict(view), message="配置已保存，实时生效")


@system_config_router.get("/system-config/ai-scenarios/audits", summary="AI 场景配置变更审计")
async def list_ai_scenario_audits(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(AiScenarioConfigAudit)
            .order_by(AiScenarioConfigAudit.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return success_response({
        "audits": [
            {
                "id": str(r.id),
                "scenario": r.scenario,
                "action": r.action,
                "before_json": r.before_json,
                "after_json": r.after_json,
                "operator_name": r.operator_name,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    })


# ── Agent 运行参数 ──


@system_config_router.get("/system-config/runtime", summary="运行参数总览")
async def list_runtime_configs(
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    views = [asdict(v) for v in runtime_store.iter_views()]
    return success_response({"configs": views})


@system_config_router.put("/system-config/runtime/{key}", summary="更新运行参数")
async def update_runtime_config(
    key: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:update")),
) -> JSONResponse:
    if "value" not in payload:
        raise HTTPException(status_code=422, detail="缺少 value 字段")
    try:
        view = await runtime_store.set_key(
            db, key, payload["value"], operator_name=user.name
        )
    except ValueError as exc:
        raise _map_store_error(exc) from exc
    return success_response(asdict(view), message="配置已保存，实时生效")


@system_config_router.get("/system-config/runtime/audits", summary="运行参数变更审计")
async def list_runtime_audits(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(RuntimeConfigAudit)
            .order_by(RuntimeConfigAudit.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return success_response({
        "audits": [
            {
                "id": str(r.id),
                "key": r.key,
                "action": r.action,
                "before_json": r.before_json,
                "after_json": r.after_json,
                "operator_name": r.operator_name,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    })


# ── Bitable 连接 ──


@system_config_router.get("/system-config/bitable/connections", summary="Bitable 表级连接总览")
async def list_bitable_connections(
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    views = [asdict(v) for v in bitable_store.iter_connection_views()]
    return success_response({"connections": views})


@system_config_router.put("/system-config/bitable/connections/{table_key}", summary="更新 Bitable 表连接坐标")
async def update_bitable_connection(
    table_key: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:update")),
) -> JSONResponse:
    try:
        view = await bitable_store.set_connection(
            db, table_key, payload, operator_name=user.name
        )
    except ValueError as exc:
        raise _map_store_error(exc) from exc
    _trigger_field_refresh(table_key)
    return success_response(asdict(view), message="配置已保存，实时生效")


@system_config_router.get("/system-config/bitable/audits", summary="Bitable 连接变更审计")
async def list_bitable_audits(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(BitableConfigAudit)
            .order_by(BitableConfigAudit.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return success_response({
        "audits": [
            {
                "id": str(r.id),
                "table_key": r.table_key,
                "action": r.action,
                "before_json": r.before_json,
                "after_json": r.after_json,
                "operator_name": r.operator_name,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    })


@system_config_router.post("/system-config/bitable/test-connection", summary="Bitable 连通性测试")
async def test_bitable_connection(
    payload: dict[str, Any],
    user: User = Depends(require_permission("warehouse:system-config:update")),
) -> JSONResponse:
    """只读拉取表头字段校验坐标（不写库、不改字段缓存）。"""
    table_key = str(payload.get("table_key") or "")
    if not table_key:
        raise HTTPException(status_code=422, detail="缺少 table_key")
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    try:
        fields = await WarehouseBitableAdapter().refresh_table_fields(table_key)
    except Exception as exc:  # noqa: BLE001 — 测试端点返回可读错误而非 500
        return success_response({"ok": False, "error": str(exc)[:300]})
    return success_response({
        "ok": True, "table_key": fields.get("table_key"),
        "table_id": fields.get("table_id"), "field_count": fields.get("field_count"),
    })


@system_config_router.post("/system-config/bitable/refresh-fields/{table_key}", summary="手动刷新字段缓存")
async def refresh_bitable_fields(
    table_key: str,
    user: User = Depends(require_permission("warehouse:system-config:update")),
) -> JSONResponse:
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    try:
        fields = await WarehouseBitableAdapter().refresh_table_fields(table_key)
    except Exception as exc:  # noqa: BLE001 — 返回可读错误而非 500
        return success_response({"ok": False, "error": str(exc)[:300]})
    return success_response({"ok": True, "field_count": fields.get("field_count")})


def _trigger_field_refresh(table_key: str) -> None:
    """连接坐标变更后失效字段缓存（零网络；网络刷新走显式 refresh-fields 端点）。"""
    from app.modules.warehouse.bitable_schema import invalidate_field_cache

    invalidate_field_cache(table_key)


# ── 定时任务/告警目标 ──


@system_config_router.get("/system-config/scheduler-tasks", summary="定时任务/告警目标总览")
async def list_scheduler_tasks(
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    views = [asdict(v) for v in scheduler_store.iter_job_views()]
    return success_response({"tasks": views})


@system_config_router.put("/system-config/scheduler-tasks/{job_name}", summary="更新定时任务/告警目标")
async def update_scheduler_task(
    job_name: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:update")),
) -> JSONResponse:
    try:
        view = await scheduler_store.set_job(
            db, job_name, payload, operator_name=user.name
        )
    except ValueError as exc:
        raise _map_store_error(exc) from exc
    return success_response(asdict(view), message="配置已保存，实时生效")


@system_config_router.get("/system-config/scheduler-tasks/audits", summary="任务配置变更审计")
async def list_scheduler_audits(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(SchedulerConfigAudit)
            .order_by(SchedulerConfigAudit.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return success_response({
        "audits": [
            {
                "id": str(r.id),
                "job_name": r.job_name,
                "action": r.action,
                "before_json": r.before_json,
                "after_json": r.after_json,
                "operator_name": r.operator_name,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    })


# ── 推送任务（V3.0 分期A 推送订阅中心）──


@system_config_router.get("/system-config/push-tasks", summary="推送任务总览")
async def list_push_tasks(
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    views = [asdict(v) for v in push_store.iter_task_views()]
    return success_response({"tasks": views})


@system_config_router.put("/system-config/push-tasks/{task_name}", summary="更新推送任务")
async def update_push_task(
    task_name: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:update")),
) -> JSONResponse:
    try:
        view = await push_store.set_task(
            db, task_name, payload, operator_name=user.name
        )
    except ValueError as exc:
        raise _map_store_error(exc) from exc
    return success_response(asdict(view), message="配置已保存，实时生效")


@system_config_router.get("/system-config/push-tasks/audits", summary="推送任务配置变更审计")
async def list_push_task_audits(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(WarehousePushTaskAudit)
            .order_by(WarehousePushTaskAudit.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return success_response({
        "audits": [
            {
                "id": str(r.id),
                "task_name": r.task_name,
                "action": r.action,
                "before_json": r.before_json,
                "after_json": r.after_json,
                "operator_name": r.operator_name,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    })


@system_config_router.get("/system-config/push-logs", summary="推送日志分页查询")
async def list_push_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    task_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    conditions: list[Any] = [WarehousePushLog.is_deleted.is_(False)]
    if task_name:
        conditions.append(WarehousePushLog.task_name == task_name)
    if status:
        conditions.append(WarehousePushLog.status == status)
    where = conditions[0]
    for cond in conditions[1:]:
        where = where & cond
    total = (
        await db.execute(select(func.count()).select_from(WarehousePushLog).where(where))
    ).scalar_one()
    rows = (
        await db.execute(
            select(WarehousePushLog)
            .where(where)
            .order_by(WarehousePushLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return success_response(
        [
            {
                "id": str(r.id),
                "created_at": r.created_at.isoformat(),
                "task_name": r.task_name,
                "scene": r.scene,
                "trigger": r.trigger,
                "run_at": r.run_at.isoformat(),
                "slot": r.slot.isoformat() if r.slot else None,
                "target": r.target,
                "status": r.status,
                "message_id": r.message_id,
                "error": r.error,
                "duration_ms": r.duration_ms,
            }
            for r in rows
        ],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@system_config_router.post("/system-config/push-tasks/{task_name}/trigger", summary="手动触发一次推送")
async def trigger_push_task(
    task_name: str,
    payload: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:update")),
) -> JSONResponse:
    """立即执行一次该任务（绕过到期判断，仍走互斥/发送/日志全链路）。

    body 可传 ``{"dry_run": true}`` 做发送演练（构建消息体但不真发），
    用于上线前验证推送链路。
    """
    body = payload or {}
    dry_run = bool(body.get("dry_run", False))
    now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))
    try:
        result = await engine.run_task(db, task_name, now_cn, dry_run=dry_run)
    except ValueError as exc:
        raise _map_store_error(exc) from exc
    return success_response(
        {
            "task_name": result.task_name,
            "scene": result.scene,
            "status": result.status,
            "slot": result.slot.isoformat() if result.slot else None,
            "log_count": result.log_count,
        },
        message="推送已触发" if result.status in ("executed", "failed") else "推送未执行",
    )


# ── 确认单（V3.0 分期A 通用确认门；API-only，无管理页）──


def _serialize_confirm_request(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "created_at": row.created_at.isoformat(),
        "request_no": row.request_no,
        "business_type": row.business_type,
        "title": row.title,
        "summary": row.summary,
        "ref_table": row.ref_table,
        "ref_record_ids": row.ref_record_ids,
        "payload": row.payload,
        "target": row.target,
        "writeback": row.writeback,
        "status": row.status,
        "expires_at": row.expires_at.isoformat(),
        "confirmed_by": row.confirmed_by,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "resend_count": row.resend_count,
        "card_message_id": row.card_message_id,
    }


@system_config_router.get("/system-config/confirm-requests", summary="确认单分页查询")
async def list_confirm_requests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    business_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    conditions: list[Any] = [WarehouseConfirmRequest.is_deleted.is_(False)]
    if status:
        conditions.append(WarehouseConfirmRequest.status == status)
    if business_type:
        conditions.append(WarehouseConfirmRequest.business_type == business_type)
    where = conditions[0]
    for cond in conditions[1:]:
        where = where & cond
    total = (
        await db.execute(
            select(func.count()).select_from(WarehouseConfirmRequest).where(where)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(WarehouseConfirmRequest)
            .where(where)
            .order_by(WarehouseConfirmRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return success_response(
        [_serialize_confirm_request(r) for r in rows],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@system_config_router.get("/system-config/confirm-requests/stats", summary="确认单状态统计")
async def confirm_request_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(
                WarehouseConfirmRequest.status,
                WarehouseConfirmRequest.business_type,
                func.count(),
            )
            .where(WarehouseConfirmRequest.is_deleted.is_(False))
            .group_by(WarehouseConfirmRequest.status, WarehouseConfirmRequest.business_type)
        )
    ).all()
    return success_response({
        "by_status_business": [
            {"status": r[0], "business_type": r[1], "count": int(r[2])} for r in rows
        ]
    })


@system_config_router.post(
    "/system-config/confirm-requests/{request_id}/resend", summary="重发确认卡（仅待确认）"
)
async def resend_confirm_request(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:update")),
) -> JSONResponse:
    from app.modules.warehouse import confirm_request as confirm_request_service

    row = (
        await db.execute(
            select(WarehouseConfirmRequest).where(
                WarehouseConfirmRequest.id == request_id,
                WarehouseConfirmRequest.is_deleted.is_(False),
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="确认单不存在")
    try:
        sent = await confirm_request_service.resend_request(db, row)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return success_response(
        _serialize_confirm_request(row),
        message="确认卡已重发" if sent else "重发失败（发送通道异常，请检查目标配置）",
    )


# ── AI 调用审计查询（设计稿 §8：与 warehouse_agent_audit 经 trace_id 串链）──


@system_config_router.get("/ai-audits", summary="AI 调用审计分页查询")
async def list_ai_call_audits(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    scenario: str | None = Query(default=None),
    status: str | None = Query(default=None),
    trace_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    conditions: list[Any] = [AiCallAudit.is_deleted.is_(False)]
    if scenario:
        conditions.append(AiCallAudit.scenario == scenario)
    if status:
        conditions.append(AiCallAudit.status == status)
    if trace_id:
        conditions.append(AiCallAudit.trace_id == trace_id)
    where = conditions[0]
    for cond in conditions[1:]:
        where = where & cond
    total = (
        await db.execute(select(func.count()).select_from(AiCallAudit).where(where))
    ).scalar_one()
    rows = (
        await db.execute(
            select(AiCallAudit)
            .where(where)
            .order_by(AiCallAudit.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return success_response(
        [
            {
                "id": str(r.id),
                "created_at": r.created_at.isoformat(),
                "trace_id": r.trace_id,
                "scenario": r.scenario,
                "resource": r.resource,
                "model": r.model,
                "prompt_version": r.prompt_version,
                "status": r.status,
                "error": r.error,
                "input_tokens": int(r.input_tokens) if r.input_tokens is not None else None,
                "output_tokens": int(r.output_tokens) if r.output_tokens is not None else None,
                "cache_hit_tokens": int(r.cache_hit_tokens) if r.cache_hit_tokens is not None else None,
                "latency_ms": int(r.latency_ms) if r.latency_ms is not None else None,
                "degradation_level": r.degradation_level,
                "chat_id": r.chat_id,
                "user_open_id": r.user_open_id,
                "channel": r.channel,
                "input_json": r.input_json,
                "output_json": r.output_json,
                "tool_names": r.tool_names,
            }
            for r in rows
        ],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@system_config_router.get("/ai-audits/stats", summary="AI 调用审计统计")
async def ai_call_audit_stats(
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                AiCallAudit.scenario,
                AiCallAudit.status,
                func.count().label("cnt"),
            )
            .where(AiCallAudit.is_deleted.is_(False), AiCallAudit.created_at >= since)
            .group_by(AiCallAudit.scenario, AiCallAudit.status)
        )
    ).all()
    by_day = (
        await db.execute(
            select(
                func.date(AiCallAudit.created_at).label("day"),
                func.count().label("cnt"),
                func.sum(case((AiCallAudit.status == "failed", 1), else_=0)).label("failed"),
            )
            .where(AiCallAudit.is_deleted.is_(False), AiCallAudit.created_at >= since)
            .group_by(func.date(AiCallAudit.created_at))
            .order_by(func.date(AiCallAudit.created_at))
        )
    ).all()
    return success_response({
        "days": days,
        "by_scenario_status": [
            {"scenario": r.scenario, "status": r.status, "count": r.cnt} for r in rows
        ],
        "by_day": [
            {"date": str(r.day), "total": r.cnt, "failed": int(r.failed)} for r in by_day
        ],
    })


@system_config_router.get("/ai-audits/{audit_id}", summary="AI 调用审计详情")
async def get_ai_call_audit(
    audit_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:system-config:read")),
) -> JSONResponse:
    row = (
        await db.execute(
            select(AiCallAudit).where(
                AiCallAudit.id == audit_id, AiCallAudit.is_deleted.is_(False)
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="审计记录不存在")
    return success_response({
        "id": str(row.id),
        "created_at": row.created_at.isoformat(),
        "trace_id": row.trace_id,
        "scenario": row.scenario,
        "resource": row.resource,
        "model": row.model,
        "prompt_version": row.prompt_version,
        "status": row.status,
        "error": row.error,
        "input_tokens": int(row.input_tokens) if row.input_tokens is not None else None,
        "output_tokens": int(row.output_tokens) if row.output_tokens is not None else None,
        "cache_hit_tokens": int(row.cache_hit_tokens) if row.cache_hit_tokens is not None else None,
        "cache_miss_tokens": int(row.cache_miss_tokens) if row.cache_miss_tokens is not None else None,
        "latency_ms": int(row.latency_ms) if row.latency_ms is not None else None,
        "degradation_level": row.degradation_level,
        "session_id": str(row.session_id) if row.session_id else None,
        "draft_id": str(row.draft_id) if row.draft_id else None,
        "chat_id": row.chat_id,
        "user_open_id": row.user_open_id,
        "channel": row.channel,
        "input_json": row.input_json,
        "output_json": row.output_json,
        "tool_names": row.tool_names,
    })
