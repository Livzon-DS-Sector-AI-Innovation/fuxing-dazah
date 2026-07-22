"""
集中式日志配置。

使用 logging.config.dictConfig 替代 basicConfig，实现：
- 按业务模块拆分日志输出（开发：控制台过滤；部署：独立文件）
- 模块级别的日志开关（通过 Settings 对象传入，不再裸读 os.getenv）
- 生产环境 JSON Lines 结构化输出
- request_id 贯穿（通过 ContextVar + Filter）
- 三方库日志集中静默管理

使用方式（在 main.py 中调用一次）：
    from app.core.logging_config import setup_logging
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

注意：生产环境多 worker 部署时，RotatingFileHandler 在多进程下不安全。
推荐使用 QueueHandler + QueueListener 或外部日志采集（filebeat/vector）。
"""

from __future__ import annotations

import json
import logging
import logging.config
import os
from contextvars import ContextVar
from datetime import datetime
from typing import Any

from app.core.time import APP_TZ

# ── request_id 上下文（由 app.platform.audit.middleware.AuditMiddleware 设置）──
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# ── 业务模块 logger 前缀 → 短名称映射（用于文件命名和终端列显示）──
_MODULE_PREFIX_MAP: dict[str, str] = {
    "app.modules.safety": "safety",
    "app.modules.equipment": "equipment",
    "app.modules.energy": "energy",
    "app.modules.hr": "hr",
    "app.modules.meter": "meter",
    "app.platform.audit": "audit",
    "app.platform": "platform",
    "app.core": "core",
}

# ── 三方库默认日志级别 ──
_THIRD_PARTY_LOGGERS: dict[str, str] = {
    "sqlalchemy": "WARNING",
    "sqlalchemy.engine": "WARNING",
    "httpx": "WARNING",
    "httpcore": "WARNING",
    "websockets": "WARNING",
    "uvicorn": "INFO",
    "uvicorn.access": "WARNING",
    "uvicorn.error": "INFO",
    "lark_oapi": "WARNING",
    "asyncpg": "WARNING",
    "redis": "WARNING",
    "fastmcp": "WARNING",
    "openai": "WARNING",
    "asyncio": "WARNING",
    "watchfiles": "WARNING",
}


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════


def _short_module_name(logger_name: str) -> str:
    """将完整 logger 名映射为短模块标识（供 ConsoleFormatter / JsonFormatter 共用）。"""
    if not logger_name:
        return "_3rd/root"
    for prefix, short in _MODULE_PREFIX_MAP.items():
        if logger_name.startswith(prefix):
            return short
    return "_3rd/" + logger_name.split(".")[0]


def _resolve_log_level(level_str: str, fallback: str = "WARNING") -> int:
    """安全解析日志级别字符串。

    无效输入回退到 fallback，避免 getattr(logging, "INVALID") 导致启动崩溃。
    """
    try:
        return int(getattr(logging, level_str.upper()))
    except AttributeError:
        return int(getattr(logging, fallback.upper()))


# ═══════════════════════════════════════════════════════════════
# Filters
# ═══════════════════════════════════════════════════════════════


class _RequestIdFilter(logging.Filter):  # pyright: ignore[reportUnusedClass]
    """将 ContextVar 中的 request_id 注入 LogRecord。

    通过 dictConfig 的 ``"()": "app.core.logging_config._RequestIdFilter"`` 实例化，
    Pyright 无法检测字符串引用，忽略 unused class 告警。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        setattr(record, "request_id", request_id_var.get())
        return True


class _ModuleFilter(logging.Filter):  # pyright: ignore[reportUnusedClass]
    """只放行 logger 名称匹配已启用模块前缀的日志。

    只过滤业务模块（app.modules.* / app.platform.* / app.core.*），
    三方库和系统 logger（uvicorn、sqlalchemy 等）始终放行。
    """

    def __init__(self, enabled_modules: list[str] | None = None):
        super().__init__()
        self._prefixes: set[str] = set(enabled_modules) if enabled_modules else set()

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._prefixes:
            return True
        name: str = record.name
        for prefix in self._prefixes:
            if name.startswith(prefix):
                return True
        # 非业务模块（三方库、uvicorn 等）始终放行
        if not name.startswith("app."):
            return True
        # 业务模块但不在启用列表 → 拦截
        return False


# ═══════════════════════════════════════════════════════════════
# Formatters
# ═══════════════════════════════════════════════════════════════


class ConsoleFormatter(logging.Formatter):
    """开发环境控制台格式：彩色级别 + 模块标记 + request_id 尾部。"""

    _COLORS: dict[str, str] = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    _RESET = "\033[0m"
    _DIM = "\033[2m"
    _TZ = APP_TZ

    def formatTime(  # noqa: N802
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        ct = datetime.fromtimestamp(record.created, tz=self._TZ)
        if datefmt:
            return ct.strftime(datefmt)
        return ct.isoformat()

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        module = _short_module_name(record.name)
        rid: str = getattr(record, "request_id", "-")[:8]  # 截断前 8 位

        return (
            f"{self._DIM}{self.formatTime(record, datefmt='%H:%M:%S')}{self._RESET} "
            f"{color}{record.levelname:<7}{self._RESET} "
            f"[{module:<10}] "
            f"{self._DIM}{record.name}:{record.lineno}{self._RESET}  "
            f"{record.getMessage()}"
            f"{self._DIM}  | {rid}{self._RESET}"
        )


class JsonFormatter(logging.Formatter):
    """生产环境 JSON Lines 格式，便于日志聚合系统（ELK / Loki / SLS）采集。

    输出示例：
        {"timestamp":"2026-06-24T18:30:15.123456+08:00","level":"INFO","logger":"...",
         "module":"safety","message":"...","request_id":"3f8a2b1c"}
    """

    _TZ = APP_TZ

    def formatTime(  # noqa: N802 — 覆盖 logging.Formatter.formatTime
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        """跨平台时间格式化。

        使用 datetime.strftime 替代 time.strftime，确保 %f（微秒）在 Windows
        上也能正常工作（Windows CRT 的 strftime 不支持 %f，Python 3.12 也未做
        兼容处理，直到 3.13 才在 logging.Formatter.formatTime 中内置 %f 支持）。
        """
        ct = datetime.fromtimestamp(record.created, tz=self._TZ)
        if datefmt:
            return ct.strftime(datefmt)
        return ct.isoformat()

    def format(self, record: logging.LogRecord) -> str:
        rid: str = getattr(record, "request_id", "-")
        log_entry: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S.%f+08:00"),
            "level": record.levelname,
            "logger": record.name,
            "module": _short_module_name(record.name),
            "msg": record.getMessage(),
            "rid": rid,
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# 环境变量解析
# ═══════════════════════════════════════════════════════════════


def _resolve_module_set(raw: str) -> set[str]:
    """将逗号分隔的模块短名解析为 logger 前缀集合。

    支持短名称（safety → app.modules.safety）和完整前缀。
    """
    if not raw.strip():
        return set()
    result: set[str] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        matched = False
        for prefix, short in _MODULE_PREFIX_MAP.items():
            if token == short:
                result.add(prefix)
                matched = True
                break
        if not matched:
            result.add(token)
    return result


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════


def get_logging_config(
    *,
    is_production: bool = False,
    log_level: str = "INFO",
    log_dir: str = "logs",
    enabled_modules: str = "",
    disabled_modules: str = "",
    third_party_level: str = "",
    third_party_handler_level: str = "WARNING",
    root_level: str = "WARNING",
) -> dict[str, Any]:
    """构建 logging.config.dictConfig 用的配置字典。

    所有配置均通过参数显式传入，不依赖 os.getenv()。
    调用方（main.py / setup_logging）负责从 Settings 对象提供值。
    """

    enabled = _resolve_module_set(enabled_modules)
    disabled = _resolve_module_set(disabled_modules)

    # 决定生效模块：enabled 优先；否则 disabled 排除
    effective_enabled: set[str] | None = None
    if enabled:
        effective_enabled = enabled
    elif disabled:
        effective_enabled = set(_MODULE_PREFIX_MAP.keys()) - disabled
        # 空集合 ≠ None：空集合表示"不禁用任何模块"，不应安装 module_enabled filter
        if not effective_enabled:
            effective_enabled = None

    # ── Formatters ──
    formatters: dict[str, Any] = {
        "console": {"()": "app.core.logging_config.ConsoleFormatter"},
        "json": {"()": "app.core.logging_config.JsonFormatter"},
    }

    # ── Filters ──
    filters: dict[str, Any] = {
        "request_id": {"()": "app.core.logging_config._RequestIdFilter"},
    }
    if effective_enabled is not None:
        filters["module_enabled"] = {
            "()": "app.core.logging_config._ModuleFilter",
            "enabled_modules": sorted(effective_enabled),
        }

    # ── Handlers ──
    handlers: dict[str, Any] = {}

    # ── 控制台 handler（业务模块用，含 module_enabled filter）──
    console_filters: list[str] = ["request_id"]
    if effective_enabled is not None:
        console_filters.insert(0, "module_enabled")
    handlers["console"] = {
        "class": "logging.StreamHandler",
        "stream": "ext://sys.stdout",
        "formatter": "console",
        "filters": console_filters,
    }

    # ── 控制台 handler（app 根 logger 专用，不含 module_enabled filter）──
    # app 根 logger 覆盖 app.main / app.api.router 等非模块代码，
    # 若共用 console handler 则会在模块过滤启用时被 _ModuleFilter 拦截，
    # 导致启动/关闭日志静默丢失。
    handlers["console_app"] = {
        "class": "logging.StreamHandler",
        "stream": "ext://sys.stdout",
        "formatter": "console",
        "filters": ["request_id"],
    }

    # ── 三方库专用控制台 handler（handler 级别拦截，防止库内部 setLevel 绕过）──
    # SQLAlchemy 等库会在运行时动态创建子 logger 并调用 setLevel(INFO)，
    # 仅靠 dictConfig 的 logger 级别无法阻止。handler 级别过滤是最可靠的手段。
    handlers["console_3rd"] = {
        "class": "logging.StreamHandler",
        "stream": "ext://sys.stdout",
        "formatter": "console",
        "level": third_party_handler_level,
        "filters": ["request_id"],
    }

    # 生产文件输出
    if is_production:
        os.makedirs(log_dir, exist_ok=True)
        file_filters: list[str] = ["request_id"]
        # 业务模块文件（每个模块一个文件）
        for prefix, short in _MODULE_PREFIX_MAP.items():
            handlers[f"file_{short}"] = {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": os.path.join(log_dir, f"{short}.log"),
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "formatter": "json",
                "filters": file_filters,
            }
        # 三方库 / 未分类
        handlers["file_other"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(log_dir, "other.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 3,
            "formatter": "json",
            "filters": file_filters,
        }

    # ── Loggers ──
    loggers: dict[str, Any] = {}

    # 业务模块
    for prefix, short in _MODULE_PREFIX_MAP.items():
        module_handlers: list[str] = ["console"]
        if is_production:
            module_handlers.append(f"file_{short}")
        loggers[prefix] = {
            "handlers": module_handlers,
            "level": log_level,
            "propagate": False,
        }

    # 三方库（优先级：细粒度 env > 全局参数 > 硬编码默认值）
    # uvicorn / uvicorn.error 使用 console handler（需要 INFO 级别），
    # 其余三方库使用 console_3rd handler（handler 级 WARNING 防库内 setLevel 绕过）
    _info_level_loggers = {"uvicorn", "uvicorn.error"}
    for name, default_level in _THIRD_PARTY_LOGGERS.items():
        level = (
            os.getenv(f"LOG_{name.upper().replace('.', '_')}_LEVEL", "")
            or third_party_level
            or default_level
        )
        tp_handlers: list[str] = (
            ["console"] if name in _info_level_loggers else ["console_3rd"]
        )
        if is_production:
            tp_handlers.append("file_other")
        loggers[name] = {
            "handlers": tp_handlers,
            "level": level,
            "propagate": False,
        }

    # app 根 logger（app.main 等未被子 logger 覆盖的应用代码）
    # 使用独立的 console_app handler（无 module_enabled filter），
    # 避免模块过滤启用时启动/关闭日志被静默吞掉。
    app_handlers: list[str] = ["console_app"]
    if is_production:
        app_handlers.append("file_other")
    loggers["app"] = {
        "handlers": app_handlers,
        "level": log_level,
        "propagate": False,
    }

    # ── Root logger（兜底，业务日志靠 propagate=False 不会到达这里）──
    root_handlers: list[str] = ["console_3rd"]
    if is_production:
        root_handlers.append("file_other")
    root_config: dict[str, Any] = {
        "handlers": root_handlers,
        "level": root_level,
    }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters,
        "filters": filters,
        "handlers": handlers,
        "loggers": loggers,
        "root": root_config,
    }


def setup_logging(
    *,
    is_production: bool = False,
    log_level: str = "INFO",
    log_dir: str = "logs",
    enabled_modules: str = "",
    disabled_modules: str = "",
    third_party_level: str = "",
    third_party_handler_level: str = "WARNING",
    root_level: str = "WARNING",
) -> None:
    """应用日志配置（在 main.py 启动时调用一次）。

    调用后所有 logger = logging.getLogger(__name__) 自动纳入统一体系。
    """
    config = get_logging_config(
        is_production=is_production,
        log_level=log_level,
        log_dir=log_dir,
        enabled_modules=enabled_modules,
        disabled_modules=disabled_modules,
        third_party_level=third_party_level,
        third_party_handler_level=third_party_handler_level,
        root_level=root_level,
    )
    logging.config.dictConfig(config)

    # ── 兜底：对已存在的三方库子 logger 强制覆盖级别 ──
    # dictConfig 只影响精确匹配的 logger 名称。SQLAlchemy 等库的二级子 logger
    # （如 sqlalchemy.engine.Engine）可能在 import 阶段已被库自身设为 INFO，
    # 仅靠父 logger 级别无法拦截。这里遍历所有已有 logger，按前缀匹配重置级别。
    for existing_name, existing_obj in logging.root.manager.loggerDict.items():
        if not isinstance(existing_obj, logging.Logger):
            continue
        for prefix, default_level in _THIRD_PARTY_LOGGERS.items():
            if existing_name == prefix or existing_name.startswith(prefix + "."):
                level_str = (
                    os.getenv(
                        f"LOG_{prefix.upper().replace('.', '_')}_LEVEL", ""
                    )
                    or third_party_level
                    or default_level
                )
                existing_obj.setLevel(_resolve_log_level(level_str))
                break
