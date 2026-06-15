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
from app.core.response import error_response
from app.platform.audit import AuditMiddleware

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# 抑制第三方库的 DEBUG 日志噪音
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


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
    import app.modules.safety.bot_handler as _  # noqa: F401 — 注册事件处理器
    from app.modules.safety.feishu.event_client import start_ws, stop_ws

    safety_ws_task = asyncio.create_task(start_ws())

    # ── 安全模块定时任务调度引擎 ──
    from app.modules.safety.scheduler import (
        scheduled_task_loop,
        stop_scheduled_task_flag,
    )

    scheduler_task = asyncio.create_task(scheduled_task_loop())

    logger.info("Background tasks started")

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


app = FastAPI(
    title=settings.APP_NAME,
    description="原料药事业部工厂基座系统",
    version="0.1.0",
    lifespan=lifespan,
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
    detail = "; ".join(
        f"{e.get('loc', [''])[-1]}: {e.get('msg', '')}" for e in errors
    )
    return error_response(
        message="请求参数校验失败",
        detail=detail,
        status_code=422,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
