"""核心安全中间件。"""

import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_UNSAFE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


class CrossSiteGuardMiddleware(BaseHTTPMiddleware):
    """拒绝浏览器发起的跨站写请求（CSRF 第二道防线）。

    现代浏览器对跨站请求会带 `Sec-Fetch-Site: cross-site` 头，
    非浏览器客户端（curl/服务端调用）与老浏览器不带该头，一律放行，
    因此无需维护来源白名单、不会误伤运维脚本。
    第一道防线是 SameSite=Lax cookie + 收敛后的 CORS。
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.method in _UNSAFE_METHODS:
            site = request.headers.get("sec-fetch-site", "")
            if site == "cross-site":
                logger.warning(
                    "Blocked cross-site %s %s", request.method, request.url.path,
                )
                return JSONResponse(
                    status_code=403,
                    content={"code": 403, "message": "跨站请求已被拒绝"},
                )
        return await call_next(request)
