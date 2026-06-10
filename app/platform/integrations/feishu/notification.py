"""通用飞书通知服务。

提供可被任何业务模块调用的飞书消息发送能力：
- send_user_card: 发送卡片消息给单个用户（DM）
- 自动管理 tenant access token 生命周期

群聊消息发送请使用同目录下 message.py 中的 send_group_card。
"""

import json
import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def _get_client():
    """获取 lark-oapi 客户端实例"""
    import lark_oapi as lark

    return (
        lark.Client.builder()
        .app_id(settings.FEISHU_APP_ID)
        .app_secret(settings.FEISHU_APP_SECRET)
        .domain(lark.FEISHU_DOMAIN)
        .app_type(lark.AppType.SELF)
        .build()
    )


async def _get_tenant_token(client) -> str:
    """获取 tenant_access_token"""
    import json as _json

    from lark_oapi.api.auth.v3 import (
        InternalTenantAccessTokenRequest,
        InternalTenantAccessTokenRequestBody,
    )

    req = (
        InternalTenantAccessTokenRequest.builder()
        .request_body(
            InternalTenantAccessTokenRequestBody.builder()
            .app_id(settings.FEISHU_APP_ID)
            .app_secret(settings.FEISHU_APP_SECRET)
            .build()
        )
        .build()
    )
    resp = await client.auth.v3.tenant_access_token.ainternal(req)
    if not resp.success():
        logger.error(
            "Failed to get tenant token: code=%s, msg=%s",
            resp.code, resp.msg,
        )
        raise RuntimeError(
            f"Failed to get tenant token: code={resp.code}, msg={resp.msg}"
        )
    if resp.raw and resp.raw.content:
        data = _json.loads(resp.raw.content.decode("utf-8"))
        token = data.get("tenant_access_token", "")
        logger.info("Tenant token obtained successfully")
        return token
    logger.error("Empty tenant token response")
    raise RuntimeError("Empty tenant token response")


async def send_user_card(
    open_id: str,
    title: str,
    content: str,
    elements: list[dict] | None = None,
) -> bool:
    """发送卡片消息给单个用户（DM）。

    Args:
        open_id: 飞书 open_id（应用维度的用户标识，如 "ou_xxx"）
        title: 卡片标题
        content: 卡片正文（支持 markdown）
        elements: 额外的卡片元素（按钮、分割线等）

    Returns:
        True 表示发送成功，False 表示失败（不抛异常）
    """
    logger.info("send_user_card: attempting to send to open_id=%s", open_id)
    try:
        client = await _get_client()
        token = await _get_tenant_token(client)

        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "orange",
            },
            "elements": [
                {"tag": "markdown", "content": content},
            ],
        }
        if elements:
            card["elements"].extend(elements)

        card_json = json.dumps(card, ensure_ascii=False)
        logger.info("send_user_card: card JSON length=%d", len(card_json))

        req = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(open_id)
                .msg_type("interactive")
                .content(card_json)
                .build()
            )
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.im.v1.message.acreate(req)
        if not resp.success():
            logger.error(
                "❌ send_user_card FAILED: open_id=%s, code=%s, msg=%s, "
                "status_code=%s",
                open_id, resp.code, resp.msg,
                resp.status_code if hasattr(resp, "status_code") else "N/A",
            )
            return False
        logger.info("✅ Card sent to open_id=%s: %s", open_id, title)
        return True
    except Exception as e:
        logger.error(
            "❌ send_user_card EXCEPTION for open_id=%s: %s: %s",
            open_id, type(e).__name__, e,
        )
        return False


async def build_card(
    title: str,
    content: str,
    header_template: str = "orange",
    elements: list[dict] | None = None,
) -> str:
    """构建飞书卡片 JSON 字符串。

    业务模块可用此函数构建卡片，然后自行调用发送。

    Args:
        title: 卡片标题
        content: markdown 正文
        header_template: 标题颜色模板（orange/blue/green/red/purple）
        elements: 额外元素列表

    Returns:
        飞书卡片 JSON 字符串
    """
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": header_template,
        },
        "elements": [
            {"tag": "markdown", "content": content},
        ],
    }
    if elements:
        card["elements"].extend(elements)
    return json.dumps(card, ensure_ascii=False)
