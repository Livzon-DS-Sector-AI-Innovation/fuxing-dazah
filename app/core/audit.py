import functools
import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    """自动审计中间件，记录所有 API 请求。"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = str(uuid.uuid4())
        start_time = time.monotonic()

        request.state.request_id = request_id

        response = await call_next(request)

        duration_ms = (time.monotonic() - start_time) * 1000

        audit_entry = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": str(request.query_params),
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        }

        logger.info("audit_request: %s", json.dumps(audit_entry, ensure_ascii=False))

        response.headers["X-Request-ID"] = request_id
        return response


def audit_log(
    resource: str,
    action: str,
) -> Callable:
    """业务审计装饰器，记录关键业务操作。"""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await func(*args, **kwargs)

            audit_entry = {
                "resource_type": resource,
                "action": action,
                "function": func.__qualname__,
                "timestamp": datetime.now().isoformat(),
            }

            logger.info(
                "audit_business: %s", json.dumps(audit_entry, ensure_ascii=False)
            )

            return result

        return wrapper

    return decorator
