"""Feishu SSO client wrapper around lark-oapi."""

import lark_oapi as lark
from lark_oapi.api.authen.v1 import (
    CreateAccessTokenRequest,
    CreateAccessTokenRequestBody,
    CreateAccessTokenResponse,
)

from app.core.config import Settings


class FeishuClient:
    """Encapsulates lark-oapi Client for SSO operations."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = (
            lark.Client.builder()
            .app_id(settings.FEISHU_APP_ID)
            .app_secret(settings.FEISHU_APP_SECRET)
            .domain(lark.FEISHU_DOMAIN)
            .app_type(lark.AppType.SELF)
            .build()
        )

    def build_authorize_url(self, state: str) -> str:
        host = "https://open.feishu.cn"
        return (
            f"{host}/open-apis/authen/v1/authorize"
            f"?app_id={self._settings.FEISHU_APP_ID}"
            f"&redirect_uri={self._settings.FEISHU_REDIRECT_URI}"
            f"&state={state}"
        )

    async def exchange_code(
        self, code: str
    ) -> CreateAccessTokenResponse:
        request = (
            CreateAccessTokenRequest.builder()
            .request_body(
                CreateAccessTokenRequestBody.builder()
                .grant_type("authorization_code")
                .code(code)
                .build()
            )
            .build()
        )
        return await self._client.authen.v1.access_token.acreate(request)
