"""office_client 核心类与统一 HTTP helper。

FeishuOfficeClient 通过 mixin 组合 docx / sheet / bitable / slides / drive /
permission 六类资源方法；本文件只保留核心身份、链接生成、失败处理、统一
_get / _post / _put / _delete helper 与测试接缝工厂。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.modules.safety.feishu.client import get_safety_tenant_token
from app.modules.safety.feishu.office_client._base import (
    OPEN_API_BASE,
    OfficeResult,
)
from app.modules.safety.feishu.office_client._bitable import (
    _BitableOfficeMixin,
)
from app.modules.safety.feishu.office_client._docx import _DocxOfficeMixin
from app.modules.safety.feishu.office_client._drive import _DriveOfficeMixin
from app.modules.safety.feishu.office_client._permission import (
    _PermissionOfficeMixin,
)
from app.modules.safety.feishu.office_client._sheet import _SheetOfficeMixin
from app.modules.safety.feishu.office_client._slides import _SlidesOfficeMixin

logger = logging.getLogger(__name__)


class FeishuOfficeClient(
    _DocxOfficeMixin,
    _SheetOfficeMixin,
    _BitableOfficeMixin,
    _SlidesOfficeMixin,
    _DriveOfficeMixin,
    _PermissionOfficeMixin,
):
    """飞书办公能力统一入口（应用机器人身份）。

    只读/写入均已实现：docx / sheets / bitable / slides / drive / 权限与
    上传删除等办公能力统一走本客户端，失败返回 OfficeResult(kind="error")。
    """

    def __init__(self, base_url: str = OPEN_API_BASE) -> None:
        self._base_url = base_url.rstrip("/")

    async def _tenant_token(self) -> str:
        return await get_safety_tenant_token()

    @staticmethod
    def _failure(action: str, exc: Exception | None = None) -> OfficeResult:
        """统一失败返回：读方法失败不抛异常，返回 OfficeResult(kind="error")。"""
        detail = f"{type(exc).__name__}: {exc}" if exc else "未知错误"
        logger.warning("FeishuOfficeClient %s 失败: %s", action, detail)
        return OfficeResult.failure(f"{action}失败：{detail}")

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        timeout: float = 30,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        """统一飞书 HTTP 请求：带 tenant token，可选 JSON/multipart/超时。"""
        token = await self._tenant_token()
        headers = {"Authorization": f"Bearer {token}"}
        if json is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"

        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=follow_redirects,
        ) as http:
            resp = await http.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                data=data,
                files=files,
            )
        return resp

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float = 30,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return await self._request(
            "GET",
            url,
            params=params,
            timeout=timeout,
            follow_redirects=follow_redirects,
        )

    async def _post(
        self,
        url: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        timeout: float = 30,
    ) -> httpx.Response:
        return await self._request(
            "POST",
            url,
            json=json,
            params=params,
            data=data,
            files=files,
            timeout=timeout,
        )

    async def _put(
        self,
        url: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float = 30,
    ) -> httpx.Response:
        return await self._request(
            "PUT", url, json=json, params=params, timeout=timeout,
        )

    async def _delete(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float = 30,
    ) -> httpx.Response:
        return await self._request(
            "DELETE", url, params=params, timeout=timeout,
        )

    @staticmethod
    def _drive_type_for_token(token: str) -> str:
        """根据飞书 token 前缀推断 Drive permission/delete 需要的 type 参数。"""
        value = (token or "").lower()
        if value.startswith(("doxcn", "dox", "docx")):
            return "docx"
        if value.startswith(("sht", "shtt")):
            return "sheet"
        if value.startswith(("bascn", "bas", "app")):
            return "bitable"
        if value.startswith(("fals", "slide")):
            return "slides"
        if value.startswith("mind"):
            return "mindnote"
        if value.startswith("wiki"):
            return "wiki"
        return "file"

    @staticmethod
    def _file_url(token: str, kind: str) -> str:
        """生成飞书端可访问链接（与既有 docx_service 一致的域名风格）。"""
        if kind == "sheet":
            return f"https://bytedance.feishu.cn/sheets/{token}"
        if kind == "bitable":
            return f"https://bytedance.feishu.cn/base/{token}"
        if kind == "slides":
            return f"https://bytedance.feishu.cn/slides/{token}"
        if kind == "docx":
            return f"https://bytedance.feishu.cn/docx/{token}"
        return f"https://bytedance.feishu.cn/file/{token}"

    def file_url(self, token: str) -> str:
        """生成 token 对应的飞书可访问链接（工具层公开辅助）。"""
        return self._file_url(token, self._drive_type_for_token(token))


_DEFAULT_OFFICE_CLIENT: FeishuOfficeClient | None = None


def build_office_client() -> FeishuOfficeClient:
    """构建/返回默认真实 FeishuOfficeClient（模块级单例）。"""
    global _DEFAULT_OFFICE_CLIENT
    if _DEFAULT_OFFICE_CLIENT is None:
        _DEFAULT_OFFICE_CLIENT = FeishuOfficeClient()
    return _DEFAULT_OFFICE_CLIENT


def get_office_client(ctx: Any) -> FeishuOfficeClient:
    """优先返回 ctx.deps.office_client，否则返回默认真实实现。

    测试接缝：单测注入 fake FeishuOfficeClient，此处不会新建真实实例。
    """
    deps = getattr(ctx, "deps", None)
    client = getattr(deps, "office_client", None)
    if client is not None:
        return client
    return build_office_client()
