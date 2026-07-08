"""Energy 模块 — 飞书多维表格客户端。

读取环境变量（不依赖 app/core/config，保持在 energy 模块边界内）：
  - FEISHU_APP_ID / FEISHU_APP_SECRET   （飞书应用凭据）
  - ENERGY_BITABLE_APP_TOKEN            （多维表格 base token）
  - ENERGY_BITABLE_TABLES               （逗号分隔 key:table_id，如 electricity:tblXXX,water:tblYYY）
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BITABLE_API = "https://open.feishu.cn/open-apis/bitable/v1"

# ── 从 env 读取配置 ──

_APP_ID = os.getenv("FEISHU_APP_ID", "")
_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
_BITABLE_APP_TOKEN = os.getenv("ENERGY_BITABLE_APP_TOKEN", "")

# ENERGY_BITABLE_TABLES 格式: "electricity:tblXXX,water:tblYYY,..."
def _parse_table_map() -> dict[str, str]:
    raw = os.getenv("ENERGY_BITABLE_TABLES", "")
    result: dict[str, str] = {}
    if not raw:
        return result
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        parts = pair.split(":", 1)
        if len(parts) == 2:
            result[parts[0].strip()] = parts[1].strip()
    return result

TABLE_MAP = _parse_table_map()


class EnergyBitableClient:
    """飞书多维表格 API 客户端。"""

    def __init__(self, table_id: str):
        self.table_id = table_id

    @property
    def app_token(self) -> str:
        return _BITABLE_APP_TOKEN

    @property
    def app_id(self) -> str:
        return _APP_ID

    @property
    def app_secret(self) -> str:
        return _APP_SECRET

    async def _token(self) -> str:
        """获取 tenant_access_token。"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            resp.raise_for_status()
            return resp.json()["tenant_access_token"]

    # ── 记录 ──

    async def list_records(
        self, page_size: int = 100, page_token: str | None = None,
    ) -> dict[str, Any]:
        token = await self._token()
        url = f"{BITABLE_API}/apps/{self.app_token}/tables/{self.table_id}/records"
        params: dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def fetch_all_records(self) -> list[dict[str, Any]]:
        all_items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            body = await self.list_records(page_token=page_token)
            data = body.get("data", {})
            all_items.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")
        return all_items

    # ── 字段 ──

    async def list_fields(self) -> list[dict[str, Any]]:
        token = await self._token()
        url = f"{BITABLE_API}/apps/{self.app_token}/tables/{self.table_id}/fields"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json().get("data", {}).get("items", [])
