"""仓储模块专属飞书客户端。

使用独立凭证 WAREHOUSE_FEISHU_APP_ID / WAREHOUSE_FEISHU_APP_SECRET
（仓库管理机器人 cli_aaa0eaf293fa5be0），与全局飞书集成、安全模块应用完全隔离。

与 safety/feishu/client.py 的差异：凭证经 `app.core.config.get_settings()`
运行时读取（模块级函数，非 import 时冻结）——与 warehouse 模块 S0 的
llm_client.py 配置读取方式保持一致，也便于测试注入。
"""

import json as _json
import logging

import lark_oapi as lark

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def get_warehouse_feishu_app_id() -> str:
    """运行时读取仓储飞书应用 AppID（get_settings() 每次取，不 import 冻结）。"""
    return get_settings().WAREHOUSE_FEISHU_APP_ID


def get_warehouse_feishu_app_secret() -> str:
    """运行时读取仓储飞书应用 AppSecret。"""
    return get_settings().WAREHOUSE_FEISHU_APP_SECRET


async def get_warehouse_feishu_client() -> lark.Client:
    """获取仓储模块专属的飞书客户端（每次新建，凭证实时读取）。"""
    app_id = get_warehouse_feishu_app_id()
    app_secret = get_warehouse_feishu_app_secret()
    if not app_id or not app_secret:
        raise RuntimeError(
            "仓储模块飞书配置缺失：请设置 WAREHOUSE_FEISHU_APP_ID 和"
            " WAREHOUSE_FEISHU_APP_SECRET 环境变量"
        )
    return (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .domain(lark.FEISHU_DOMAIN)
        .app_type(lark.AppType.SELF)
        .build()
    )


async def get_warehouse_tenant_token(client: lark.Client | None = None) -> str:
    """获取仓储模块飞书应用的 tenant_access_token。"""
    from lark_oapi.api.auth.v3 import (
        InternalTenantAccessTokenRequest,
        InternalTenantAccessTokenRequestBody,
    )

    app_id = get_warehouse_feishu_app_id()
    app_secret = get_warehouse_feishu_app_secret()
    if client is None:
        client = await get_warehouse_feishu_client()

    req = (
        InternalTenantAccessTokenRequest.builder()
        .request_body(
            InternalTenantAccessTokenRequestBody.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .build()
        )
        .build()
    )
    resp = await client.auth.v3.tenant_access_token.ainternal(req)
    if not resp.success():
        raise RuntimeError(
            f"获取仓储模块飞书 tenant token 失败: code={resp.code}, msg={resp.msg}"
        )
    if resp.raw and resp.raw.content:
        data = _json.loads(resp.raw.content.decode("utf-8"))
        token: str = data.get("tenant_access_token", "")
        logger.debug("仓储模块飞书 tenant token 获取成功")
        return token
    raise RuntimeError("仓储模块飞书 tenant token 响应为空")
