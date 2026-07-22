import json
import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.logging_config import request_id_var

logger = logging.getLogger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    """Attach request IDs and emit request audit records.

    Phase 1 writes structured logs. The persistent audit table is already part of
    the schema so service-level operations can store business audit records.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = str(uuid.uuid4())
        start_time = time.monotonic()
        request.state.request_id = request_id
        request_id_var.set(request_id)  # 注入 ContextVar，所有日志自动携带

        response = await call_next(request)
        duration_ms = round((time.monotonic() - start_time) * 1000)

        audit_entry = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": str(request.query_params),
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        }
        logger.info("audit_request: %s", json.dumps(audit_entry, ensure_ascii=False))
        response.headers["X-Request-ID"] = request_id
        return response
