"""Feishu tenant access token management."""

import time

import httpx

from app.core.config import get_settings

_settings = get_settings()


class FeishuAuth:
    _token: str | None = None
    _expire_at: float = 0.0

    @classmethod
    async def get_tenant_access_token(cls) -> str:
        if cls._token and time.time() < cls._expire_at - 60:
            return cls._token

        app_id = _settings.FEISHU_APP_ID
        app_secret = _settings.FEISHU_APP_SECRET
        if not app_id or not app_secret:
            raise RuntimeError("Feishu app_id or app_secret not configured")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"Feishu auth failed: {data}")

        cls._token = data["tenant_access_token"]
        cls._expire_at = time.time() + data.get("expire", 7200)
        return cls._token
