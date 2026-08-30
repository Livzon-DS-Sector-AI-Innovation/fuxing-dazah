"""Meter API 路由装配与请求日志。"""

from __future__ import annotations

import logging

from fastapi import Depends, Request

from app.shared.module_api import create_module_router
from app.shared.module_registry import MODULES_BY_CODE

logger = logging.getLogger(__name__)

# ── 为所有 meter API 添加请求日志 ──


async def _log_meter_request(request: Request) -> None:
    """记录每个 meter API 请求的方法和路径，便于排查问题。"""
    logger.info(
        "[meter] %s %s | client=%s",
        request.method, request.url.path,
        request.client.host if request.client else "unknown",
    )


router = create_module_router(MODULES_BY_CODE["meter"])
# 注入请求日志依赖：所有 meter 路由执行前会自动调用 _log_meter_request
router.dependencies.append(Depends(_log_meter_request))
