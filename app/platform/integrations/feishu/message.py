"""Feishu message push service."""

import json
import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def _get_feishu_client():
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
        raise RuntimeError(
            f"Failed to get tenant token: code={resp.code}, msg={resp.msg}",
        )
    if resp.raw and resp.raw.content:
        data = _json.loads(resp.raw.content.decode("utf-8"))
        return data.get("tenant_access_token", "")
    raise RuntimeError("Empty tenant token response")


async def send_group_card(
    chat_id: str,
    title: str,
    content: str,
    elements: list[dict] | None = None,
) -> bool:
    """发送卡片消息到群聊"""
    try:
        client = await _get_feishu_client()
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

        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("interactive")
                .content(card_json)
                .build()
            )
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.im.v1.message.acreate(req)
        if not resp.success():
            logger.error("Failed to send card message: %s", resp.msg)
            return False
        return True
    except Exception:
        logger.exception("send_group_card failed")
        return False


async def send_work_order_card(
    work_order_no: str,
    equipment_name: str,
    fault_description: str,
    priority: str,
    reporter_name: str,
    claim_url: str,
) -> bool:
    """发送工单通知卡片到设备部群聊"""
    chat_id = settings.FEISHU_EQUIPMENT_CHAT_ID
    if not chat_id:
        logger.warning("FEISHU_EQUIPMENT_CHAT_ID not configured, skip push")
        return False

    title = f"🔧 新维修工单 {work_order_no}"
    content = (
        f"**设备：**{equipment_name}\n"
        f"**优先级：**{priority}\n"
        f"**报修人：**{reporter_name}\n"
        f"**描述：**{fault_description or '（无）'}"
    )
    elements = [
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "立即抢单"},
                    "type": "primary",
                    "url": claim_url,
                },
            ],
        },
    ]

    return await send_group_card(chat_id, title, content, elements)


async def send_claim_notification(
    work_order_no: str, claimer_name: str
) -> bool:
    """工单被抢后通知群聊"""
    chat_id = settings.FEISHU_EQUIPMENT_CHAT_ID
    if not chat_id:
        return False

    return await send_group_card(
        chat_id,
        title="✅ 工单已被接单",
        content=f"**{claimer_name}** 已接单 **{work_order_no}**",
    )


async def send_timeout_notification(
    work_order_no: str, equipment_name: str, leader_name: str
) -> bool:
    """超时未接单通知主管"""
    chat_id = settings.FEISHU_EQUIPMENT_CHAT_ID
    if not chat_id:
        return False

    return await send_group_card(
        chat_id,
        title="⏰ 工单超时未接单",
        content=(
            f"**{work_order_no}**（{equipment_name}）超时无人接单\n"
            f"请主管 **{leader_name}** 及时派发"
        ),
    )
