import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.logging_config import setup_logging
from app.core.response import error_response
from app.platform.audit import AuditMiddleware

settings = get_settings()

setup_logging(
    is_production=settings.is_production,
    log_level="DEBUG" if settings.DEBUG else settings.LOG_LEVEL,
    log_dir=settings.LOG_DIR,
    enabled_modules=settings.LOG_ENABLED_MODULES,
    disabled_modules=settings.LOG_DISABLED_MODULES,
    third_party_level=settings.LOG_THIRD_PARTY_LEVEL,
    third_party_handler_level=settings.LOG_THIRD_PARTY_HANDLER_LEVEL,
    root_level=settings.LOG_ROOT_LEVEL,
)

logger = logging.getLogger(__name__)

# ── MCP 服务初始化（模块级别，确保 lifespan 可合并）──
from app.modules.equipment import mcp_tools  # noqa: E402, F401 — 触发 @mcp.tool() 注册
from app.platform.mcp.middleware import build_mcp_middleware  # noqa: E402
from app.platform.mcp.server import get_mcp_app  # noqa: E402

mcp_middleware = build_mcp_middleware()
mcp_asgi = get_mcp_app(path="/", middleware=mcp_middleware)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting %s (%s)", settings.APP_NAME, settings.APP_ENV)

    from app.modules.energy.scheduler import (
        energy_collection_loop,
        stop_energy_collection_flag,
    )
    from app.modules.equipment.scheduler import (
        maintenance_plan_loop,
        stop_maintenance_plan_flag,
    )
    from app.platform.integrations.feishu.sync import (
        member_sync_loop,
        stop_member_sync_flag,
        stop_timeout_flag,
        timeout_scan_loop,
    )

    member_task = asyncio.ensure_future(member_sync_loop())
    timeout_task = asyncio.ensure_future(timeout_scan_loop())
    energy_task = asyncio.ensure_future(energy_collection_loop())
    maintenance_plan_task = asyncio.ensure_future(maintenance_plan_loop())

    # ── 平台级飞书 WebSocket 长连接 ──
    if settings.FEISHU_WS_ENABLED:
        from app.platform.integrations.feishu.event_handler import set_main_loop
        from app.platform.integrations.feishu.ws_client import start_ws_client

        set_main_loop(asyncio.get_running_loop())
        start_ws_client()

    # ── 设备模块飞书 WebSocket 长连接（独立交互机器人，原生 WebSocket） ──
    equipment_ws_task: asyncio.Task | None = None
    if settings.EQUIPMENT_FEISHU_APP_ID and settings.EQUIPMENT_FEISHU_APP_SECRET:
        from app.modules.equipment.feishu.ws_client import start_equipment_ws

        equipment_ws_task = asyncio.create_task(start_equipment_ws())

    # ── 安全模块专属飞书事件订阅（WebSocket 长连接，独立应用凭据）──
    from app.modules.safety.feishu.event_client import start_ws, stop_ws

    safety_ws_task = asyncio.create_task(start_ws())

    # ── Phase 1: Bitable 漏单诊断（启动时检查停机期间遗漏的记录）──
    async def _run_safety_catch_up_diagnostic() -> None:
        """启动时比对 Bitable 与本地 DB，检测 WS 断线期间的漏单。

        延迟 5 秒让 WS 完成建连和订阅后再查询 Bitable。
        纯诊断，不修改数据。异常不阻塞服务启动。
        """
        try:
            await asyncio.sleep(5)

            from app.core.database import async_session_factory
            from app.modules.safety.feishu.catch_up import diagnose_missed_records

            async with async_session_factory() as diag_db:
                result = await diagnose_missed_records(diag_db)

            missed = result.get("missed", 0)
            if missed < 0:
                logger.warning("Bitable 漏单诊断: 执行失败，详见上方日志")
            elif missed == 0:
                logger.info("Bitable 漏单诊断: 启动检查完成，无漏单")
            # 有漏单时 catch_up.py 已打印醒目 box 日志，这里不再重复
        except Exception:
            logger.exception("Bitable 漏单诊断: 启动检查异常（非致命）")

    asyncio.create_task(_run_safety_catch_up_diagnostic())

    # ── 安全模块定时任务调度引擎 ──
    from app.modules.safety.scheduler import (
        scheduled_task_loop,
        stop_scheduled_task_flag,
    )

    scheduler_task = asyncio.create_task(scheduled_task_loop())

    # ── 统一调度引擎（平台级，各模块可渐进迁移）──
    from app.platform.scheduler import SchedulerEngine, SchedulerRegistry

    scheduler_registry = SchedulerRegistry()
    scheduler_engine = SchedulerEngine(scheduler_registry)

    from app.modules.equipment.scheduled import (
        InspectionScheduleGenerator,
    )
    scheduler_registry.register_generator(InspectionScheduleGenerator())

    scheduler_engine_task = asyncio.create_task(scheduler_engine.run())

    logger.info("Background tasks started")

    # ── 权限系统启动引导 ──
    from app.core.database import async_session_factory
    from app.platform.permission.bootstrap import bootstrap_permissions

    async with async_session_factory() as perm_db:
        await bootstrap_permissions(perm_db, settings)

    yield

    stop_member_sync_flag.set()
    stop_timeout_flag.set()
    stop_energy_collection_flag.set()
    stop_maintenance_plan_flag.set()

    # 停止安全模块 WebSocket
    await stop_ws()
    safety_ws_task.cancel()

    # 停止定时任务调度引擎
    stop_scheduled_task_flag.set()
    scheduler_task.cancel()

    # ── 停止统一调度引擎 ──
    scheduler_engine.stop()
    try:
        await asyncio.wait_for(scheduler_engine_task, timeout=10)
    except (TimeoutError, asyncio.CancelledError):
        pass

    # 停止设备模块 WebSocket
    if equipment_ws_task:
        from app.modules.equipment.feishu.ws_client import stop_equipment_ws

        await stop_equipment_ws()
        equipment_ws_task.cancel()

    member_task.cancel()
    timeout_task.cancel()
    energy_task.cancel()
    maintenance_plan_task.cancel()

    # 停止平台级飞书 WebSocket
    from app.platform.integrations.feishu.ws_client import stop_ws_client

    stop_ws_client()

    logger.info("Background tasks stopped")


from fastmcp.utilities.lifespan import combine_lifespans  # noqa: E402

app = FastAPI(
    title=settings.APP_NAME,
    description="原料药事业部工厂基座系统",
    version="0.1.0",
    lifespan=combine_lifespans(lifespan, mcp_asgi.lifespan),
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# 挂载静态文件目录（图片上传等）
uploads_dir = os.path.abspath(settings.UPLOAD_DIR)
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

# ── 挂载 MCP 服务（AI Agent 协议入口）──
app.mount("/mcp", mcp_asgi, name="mcp")
logger.info("MCP server mounted at /mcp")


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return error_response(
        message=exc.message,
        detail=exc.detail_msg,
        status_code=exc.status_code,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return error_response(
        message=str(exc.detail),
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    detail = "; ".join(f"{e.get('loc', [''])[-1]}: {e.get('msg', '')}" for e in errors)
    return error_response(
        message="请求参数校验失败",
        detail=detail,
        status_code=422,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
