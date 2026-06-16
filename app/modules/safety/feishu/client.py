"""安全模块专属飞书客户端。

使用独立凭证 SAFETY_FEISHU_APP_ID / SAFETY_FEISHU_APP_SECRET，
与全局飞书集成完全隔离。
"""

import json as _json
import logging
import os
from pathlib import Path

import lark_oapi as lark
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 加载对应的 .env 文件（安全模块独立读取，不依赖全局 Settings）
_env_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
_app_env = os.getenv("APP_ENV", "development")
_env_path = _env_dir / f".env.{_app_env}"
if _env_path.exists():
    load_dotenv(_env_path)

# 安全模块独立的应用凭证（从环境变量读取，不经过全局 config）
SAFETY_FEISHU_APP_ID = os.getenv("SAFETY_FEISHU_APP_ID", "")
SAFETY_FEISHU_APP_SECRET = os.getenv("SAFETY_FEISHU_APP_SECRET", "")


async def get_safety_feishu_client() -> lark.Client:
    """获取安全模块专属的飞书客户端。"""
    if not SAFETY_FEISHU_APP_ID or not SAFETY_FEISHU_APP_SECRET:
        raise RuntimeError(
            "安全模块飞书配置缺失：请设置 SAFETY_FEISHU_APP_ID 和 SAFETY_FEISHU_APP_SECRET 环境变量"
        )
    return (
        lark.Client.builder()
        .app_id(SAFETY_FEISHU_APP_ID)
        .app_secret(SAFETY_FEISHU_APP_SECRET)
        .domain(lark.FEISHU_DOMAIN)
        .app_type(lark.AppType.SELF)
        .build()
    )


async def get_safety_tenant_token(client: lark.Client | None = None) -> str:
    """获取安全模块飞书应用的 tenant_access_token。"""
    from lark_oapi.api.auth.v3 import (
        InternalTenantAccessTokenRequest,
        InternalTenantAccessTokenRequestBody,
    )

    if client is None:
        client = await get_safety_feishu_client()

    req = (
        InternalTenantAccessTokenRequest.builder()
        .request_body(
            InternalTenantAccessTokenRequestBody.builder()
            .app_id(SAFETY_FEISHU_APP_ID)
            .app_secret(SAFETY_FEISHU_APP_SECRET)
            .build()
        )
        .build()
    )
    resp = await client.auth.v3.tenant_access_token.ainternal(req)
    if not resp.success():
        raise RuntimeError(
            f"获取安全模块飞书 tenant token 失败: code={resp.code}, msg={resp.msg}"
        )
    if resp.raw and resp.raw.content:
        data = _json.loads(resp.raw.content.decode("utf-8"))
        token = data.get("tenant_access_token", "")
        logger.debug("安全模块飞书 tenant token 获取成功")
        return token
    raise RuntimeError("安全模块飞书 tenant token 响应为空")
