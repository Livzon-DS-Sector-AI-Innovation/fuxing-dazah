"""ragplus-x 爬虫域客户端（契约②③）。

契约② POST /api/v1/crawler/candidates/{id}/lifecycle（候选生命周期指令）
契约③ GET  /api/v1/crawler/status（源健康+运行历史，监控聚合用）
鉴权走既有 Bearer token（SAFETY_RAGPLUS_API_TOKEN）；超时/重试模式对齐
knowledge/ragplus_client（连接类错误与 5xx 各重试一次，其余快速失败）。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.modules.safety.app_config.store import store as app_config_store

logger = logging.getLogger(__name__)

_CONNECT_RETRIES = 1
_LIFECYCLE_ACTIONS = ("promote", "reject", "archive_superseded")


class RagplusCrawlerError(RuntimeError):
    """ragplus 爬虫域接口调用失败（含不可达/鉴权失败/非 2xx）。"""


class RagplusCrawlerNotConnectedError(RagplusCrawlerError):
    """ragplus 爬虫模块未部署/路由不存在（404）——监控三态 not_connected 依据。"""


class RagplusCrawlerClient:
    """契约②③ 轻量客户端（只读状态 + 生命周期指令）。"""

    def __init__(self, base_url: str, token: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=self._timeout,
        )

    async def _request_json(
        self, method: str, url: str, json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(_CONNECT_RETRIES + 1):
            try:
                async with self._client() as client:
                    resp = await client.request(method, url, json=json_body)
                if resp.status_code in (401, 403):
                    raise RagplusCrawlerError(
                        f"ragplus 爬虫接口鉴权失败（{resp.status_code}），"
                        "请检查 SAFETY_RAGPLUS_API_TOKEN"
                    )
                if resp.status_code == 404:
                    raise RagplusCrawlerNotConnectedError(
                        f"ragplus 爬虫模块未部署或路由不存在: {url}（404）"
                    )
                if resp.status_code >= 500 and attempt < _CONNECT_RETRIES:
                    last_error = RagplusCrawlerError(f"ragplus 5xx: {resp.status_code}")
                    continue
                if resp.status_code >= 400:
                    raise RagplusCrawlerError(
                        f"ragplus 接口错误 {resp.status_code}: {resp.text[:200]}"
                    )
                data: dict[str, Any] = resp.json()
                return data
            except httpx.TransportError as exc:
                last_error = exc
                if attempt < _CONNECT_RETRIES:
                    continue
        raise RagplusCrawlerError(f"ragplus 不可达: {last_error}")

    async def send_lifecycle(
        self,
        candidate_id: str,
        action: str,
        reason: str = "",
        replace_candidate_id: str | None = None,
    ) -> dict[str, Any]:
        """契约②：候选生命周期指令（promote/reject/archive_superseded）。"""
        if action not in _LIFECYCLE_ACTIONS:
            raise ValueError(f"非法 lifecycle action: {action}")
        body: dict[str, Any] = {"action": action, "reason": reason}
        if replace_candidate_id:
            body["replace_candidate_id"] = replace_candidate_id
        return await self._request_json(
            "POST", f"/api/v1/crawler/candidates/{candidate_id}/lifecycle", body,
        )

    async def get_crawler_status(self) -> dict[str, Any]:
        """契约③：源健康 + 运行历史（监控聚合与对账巡检数据源）。"""
        return await self._request_json("GET", "/api/v1/crawler/status")


# ── 共享单例工厂（配置指纹变化即重建，对齐 knowledge/ragplus_client 模式） ──

_crawler_client_instance: RagplusCrawlerClient | None = None
_crawler_client_fingerprint: tuple[str, str, float] | None = None


def get_ragplus_crawler_client() -> RagplusCrawlerClient:
    global _crawler_client_instance, _crawler_client_fingerprint
    base_url = app_config_store.get_str("SAFETY_RAGPLUS_BASE_URL", "http://localhost:8085")
    token = app_config_store.get_str("SAFETY_RAGPLUS_API_TOKEN", "")
    timeout = float(app_config_store.get_int("SAFETY_RAGPLUS_TIMEOUT_SECONDS", 10))
    fingerprint = (base_url, token, timeout)
    if _crawler_client_instance is None or _crawler_client_fingerprint != fingerprint:
        _crawler_client_instance = RagplusCrawlerClient(base_url, token, timeout)
        _crawler_client_fingerprint = fingerprint
    return _crawler_client_instance
