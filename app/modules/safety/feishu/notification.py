"""安全模块专属飞书通知服务。

使用安全模块独立的飞书应用发送消息，不影响全局飞书集成。
"""

import json
import logging
from uuid import UUID

from app.modules.safety.feishu.client import (
    get_safety_feishu_client,
    get_safety_tenant_token,
)

logger = logging.getLogger(__name__)


def _json_dumps(obj) -> str:
    """JSON 序列化，自动将 UUID 转为字符串。"""
    return json.dumps(obj, ensure_ascii=False, default=lambda o: str(o) if isinstance(o, UUID) else o)


async def send_user_card(
    open_id: str,
    title: str,
    content: str,
    elements: list[dict] | None = None,
) -> bool:
    """使用安全模块飞书应用发送卡片消息给单个用户（DM）。

    Args:
        open_id: 飞书 open_id（应用维度的用户标识，如 "ou_xxx"）
        title: 卡片标题
        content: 卡片正文（支持 markdown）
        elements: 额外的卡片元素（按钮、分割线等）

    Returns:
        True 表示发送成功，False 表示失败（不抛异常）
    """
    logger.info("安全模块 send_user_card: open_id=%s", open_id)
    try:
        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)

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

        card_json = _json_dumps(card)

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
                "安全模块 send_user_card 失败: open_id=%s, code=%s, msg=%s",
                open_id, resp.code, resp.msg,
            )
            return False
        logger.info("安全模块卡片已发送: open_id=%s, title=%s", open_id, title)
        return True
    except Exception:
        logger.exception("安全模块 send_user_card 异常: open_id=%s", open_id)
        return False


async def update_card(message_id: str, card: dict) -> bool:
    """更新已发送的卡片消息（PATCH）。

    Args:
        message_id: 飞书消息 ID（如 "om_xxx"）
        card: 完整的卡片 JSON dict

    Returns:
        True 表示更新成功，False 表示失败（不抛异常）
    """
    logger.info("安全模块 update_card: message_id=%s", message_id)
    try:
        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)

        from lark_oapi.api.im.v1 import (
            PatchMessageRequest,
            PatchMessageRequestBody,
        )

        card_json = _json_dumps(card)

        req = (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                PatchMessageRequestBody.builder()
                .content(card_json)
                .build()
            )
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.im.v1.message.apatch(req)
        if not resp.success():
            logger.error(
                "安全模块 update_card 失败: message_id=%s, code=%s, msg=%s",
                message_id, resp.code, resp.msg,
            )
            return False
        logger.info("安全模块卡片已更新: message_id=%s", message_id)
        return True
    except Exception:
        logger.exception("安全模块 update_card 异常: message_id=%s", message_id)
        return False


async def send_group_card(
    chat_id: str,
    title: str,
    content: str,
    elements: list[dict] | None = None,
) -> bool:
    """使用安全模块飞书应用发送卡片消息到群聊。

    Args:
        chat_id: 飞书群聊 chat_id（如 "oc_xxx"）
        title: 卡片标题
        content: 卡片正文（支持 markdown）
        elements: 额外的卡片元素

    Returns:
        True 表示发送成功，False 表示失败（不抛异常）
    """
    try:
        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)

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

        card_json = _json_dumps(card)

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
            logger.error(
                "安全模块 send_group_card 失败: chat_id=%s, code=%s, msg=%s",
                chat_id, resp.code, resp.msg,
            )
            return False
        return True
    except Exception:
        logger.exception("安全模块 send_group_card 异常")
        return False


async def build_card(
    title: str,
    content: str,
    header_template: str = "orange",
    elements: list[dict] | None = None,
) -> str:
    """构建飞书卡片 JSON 字符串。

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
    return _json_dumps(card)
