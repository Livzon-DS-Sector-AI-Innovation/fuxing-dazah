import logging
import os
import posixpath
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.logging_config import setup_logging
from app.core.response import error_response
from app.platform.audit import AuditMiddleware
from app.shared.module_registry import PRIVATE_UPLOAD_PREFIXES

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

# ── 模块后台服务清单（模块级别 import，须先于下方 MCP ASGI 构建）──
# 各模块 lifecycle 顺带触发自身 @mcp.tool() 注册（旧 main 的 mcp_tools 触发
# import 已随职责下沉到各模块）。清单不放 shared/module_registry——它被十余
# 个模块的 api 层反向引用，import 模块 lifecycle 会循环导入；新模块带后台
# 服务时在此登记一行即可，模块内部增删服务不再需要动本文件。
from app.modules.energy.lifecycle import ENERGY_EXTENSION  # noqa: E402
from app.modules.equipment.lifecycle import EQUIPMENT_EXTENSION  # noqa: E402
from app.modules.hr.lifecycle import HR_EXTENSION  # noqa: E402
from app.modules.meter.lifecycle import METER_EXTENSION  # noqa: E402
from app.modules.production.lifecycle import PRODUCTION_EXTENSION  # noqa: E402
from app.modules.qa.lifecycle import QA_EXTENSION  # noqa: E402
from app.modules.quality.lifecycle import QUALITY_EXTENSION  # noqa: E402
from app.modules.warehouse.lifecycle import WAREHOUSE_EXTENSION  # noqa: E402
from app.modules.toolbox.registry import TOOL_IMAGE_URL_PREFIX  # noqa: E402
from app.platform.identity import (  # noqa: E402
    mcp_tools as identity_mcp_tools,  # noqa: F401 触发 @mcp.tool() 注册
)
from app.platform.integrations.feishu.lifecycle import (  # noqa: E402
    FEISHU_PLATFORM_EXTENSION,
)
from app.platform.mcp.middleware import build_mcp_middleware  # noqa: E402
from app.platform.mcp.server import get_mcp_app, get_module_mcp  # noqa: E402
from app.platform.module_lifecycle import (  # noqa: E402
    ModuleExtension,
    run_module_lifecycles,
)

# 平台设施（飞书）作为 0 号扩展排在最前：其 WS 启动先于各模块自管资源，
# 且此时全部模块的事件回调已注册完毕。
MODULE_EXTENSIONS: tuple[ModuleExtension, ...] = (
    FEISHU_PLATFORM_EXTENSION,
    PRODUCTION_EXTENSION,
    EQUIPMENT_EXTENSION,
    ENERGY_EXTENSION,
    METER_EXTENSION,
    QUALITY_EXTENSION,
    QA_EXTENSION,
    HR_EXTENSION,
)

mcp_middleware = build_mcp_middleware()
production_mcp_asgi = get_mcp_app(
    get_module_mcp("production"), path="/", middleware=mcp_middleware
)
equipment_mcp_asgi = get_mcp_app(
    get_module_mcp("equipment"), path="/", middleware=mcp_middleware
)
platform_mcp_asgi = get_mcp_app(
    get_module_mcp("platform"), path="/", middleware=mcp_middleware
)
hr_mcp_asgi = get_mcp_app(get_module_mcp("hr"), path="/", middleware=mcp_middleware)
warehouse_mcp_asgi = get_mcp_app(
    get_module_mcp("warehouse"), path="/", middleware=mcp_middleware
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting %s (%s)", settings.APP_NAME, settings.APP_ENV)

    async with run_module_lifecycles(MODULE_EXTENSIONS):
        # ── 权限系统启动引导 ──
        from app.core.database import async_session_factory
        from app.platform.permission.bootstrap import bootstrap_permissions

        async with async_session_factory() as perm_db:
            await bootstrap_permissions(perm_db, settings)

        yield


from fastmcp.utilities.lifespan import combine_lifespans  # noqa: E402

app = FastAPI(
    title=settings.APP_NAME,
    description="原料药事业部工厂基座系统",
    version="0.1.0",
    lifespan=combine_lifespans(
        lifespan,
        production_mcp_asgi.lifespan,
        equipment_mcp_asgi.lifespan,
        platform_mcp_asgi.lifespan,
        hr_mcp_asgi.lifespan,
        warehouse_mcp_asgi.lifespan,
    ),
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

# 私有模块目录只能经带权限的代理接口读取，不能被公共静态挂载绕过。
# 前缀清单登记在 shared/module_registry（qa 质量原件 / feedback 反馈截图）。


# 挂载静态文件目录（图片上传等）。QA 本地回退文件虽然仍兼容落在
# ``UPLOAD_DIR/qa``（开发环境已有文件不能因为本次升级突然不可读），但
# 质量原件必须始终经过带权限的 QA 代理接口，不能被这个公共静态挂载绕过。
class _PublicUploads(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, object]):  # type: ignore[override]
        # StaticFiles 自身会做 realpath 校验；这里也必须先规范化 ``..``，
        # 否则 ``/uploads/public/../qa/...`` 可能绕过简单的前缀判断。
        normalized = (
            posixpath.normpath("/" + path.replace("\\", "/")).lstrip("/").casefold()
        )
        if any(
            normalized == prefix or normalized.startswith(prefix + "/")
            for prefix in PRIVATE_UPLOAD_PREFIXES
        ):
            return PlainTextResponse("Not Found", status_code=404)
        return await super().get_response(path, scope)


uploads_dir = os.path.abspath(settings.UPLOAD_DIR)
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", _PublicUploads(directory=uploads_dir), name="uploads")

# ── 工具箱工具图片（公开静态，<img> 无法携带认证头，目录只放图片）──
toolbox_images_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "modules/toolbox/tools/images")
)
os.makedirs(toolbox_images_dir, exist_ok=True)
app.mount(
    TOOL_IMAGE_URL_PREFIX,
    StaticFiles(directory=toolbox_images_dir),
    name="toolbox-tools",
)

# ── 挂载 MCP 服务（按模块拆分端点，AI Agent 协议入口）──
app.mount("/mcp/production", production_mcp_asgi, name="mcp-production")
app.mount("/mcp/equipment", equipment_mcp_asgi, name="mcp-equipment")
app.mount("/mcp/platform", platform_mcp_asgi, name="mcp-platform")
app.mount("/mcp/hr", hr_mcp_asgi, name="mcp-hr")
app.mount("/mcp/warehouse", warehouse_mcp_asgi, name="mcp-warehouse")
logger.info(
    "MCP servers mounted at /mcp/production, /mcp/equipment, /mcp/platform, "
    "/mcp/hr, /mcp/warehouse"
)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    if exc.status_code >= 500:
        logger.exception(
            "HTTP %d on %s %s: %s",
            exc.status_code,
            request.method,
            request.url.path,
            exc.message,
        )
    return error_response(
        message=exc.message,
        detail=exc.detail_msg,
        status_code=exc.status_code,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    if exc.status_code >= 500:
        logger.exception(
            "HTTP %d on %s %s: %s",
            exc.status_code,
            request.method,
            request.url.path,
            exc.detail,
        )
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled exception on %s %s [request_id=%s]: %s",
        request.method,
        request.url.path,
        request_id,
        exc,
    )
    return error_response(
        message="服务内部错误",
        detail=f"请联系管理员，错误编号: {request_id}" if request_id else None,
        status_code=500,
        request_id=request_id,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
