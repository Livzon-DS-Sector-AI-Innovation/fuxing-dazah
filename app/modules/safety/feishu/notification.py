"""安全模块专属飞书通知服务。

使用安全模块独立的飞书应用发送消息，不影响全局飞书集成。
"""

import asyncio
import json
import logging
import os
from uuid import UUID

import httpx

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
    id_type: str = "open_id",
) -> bool:
    """使用安全模块飞书应用发送卡片消息给单个用户（DM）。

    Args:
        open_id: 飞书用户标识（默认 open_id，也可传 union_id）
        title: 卡片标题
        content: 卡片正文（支持 markdown）
        elements: 额外的卡片元素（按钮、分割线等）
        id_type: 用户标识类型，"open_id"（默认）或 "union_id"（跨应用一致）

    Returns:
        True 表示发送成功，False 表示失败（不抛异常）
    """
    logger.info("安全模块 send_user_card: user_id=%s id_type=%s", open_id, id_type)
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
            .receive_id_type(id_type)
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
    header_template: str = "orange",
) -> str | None:
    """使用安全模块飞书应用发送卡片消息到群聊。

    Args:
        chat_id: 飞书群聊 chat_id（如 "oc_xxx"）
        title: 卡片标题
        content: 卡片正文（支持 markdown）
        elements: 额外的卡片元素
        header_template: 标题颜色模板（orange/blue/green/red/purple）

    Returns:
        成功返回飞书 message_id（如 "om_xxx"），失败返回 None（不抛异常）
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
                "template": header_template,
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
            return None
        message_id = resp.data.message_id if resp.data else None
        logger.info("安全模块群卡片已发送: chat_id=%s, message_id=%s", chat_id, message_id)
        return message_id
    except Exception:
        logger.exception("安全模块 send_group_card 异常")
        return None


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


def _resolve_local_image_path(file_path: str) -> str | None:
    """将图片路径解析为实际存在的本地文件绝对路径。

    尝试多种路径变体（与 HazardService._parse_defect_photo_urls 对齐）：
    1. 原始路径（相对 CWD）
    2. Windows/Unix 分隔符互换
    3. 拼接 uploads/ 前缀（兼容不含前缀的存储路径）
    4. 拼接绝对 uploads 路径

    Returns:
        文件存在时返回绝对路径，否则返回 None
    """
    check_paths = [file_path]
    # 分隔符互换
    if "\\" in file_path:
        check_paths.append(file_path.replace("\\", "/"))
    elif "/" in file_path:
        check_paths.append(file_path.replace("/", "\\"))

    # 拼接 uploads/ 前缀：兼容存储路径不带 uploads/ 前缀的情况
    uploads_base = os.path.abspath("./uploads")
    for orig in list(check_paths):
        candidate = os.path.normpath(os.path.join(uploads_base, orig))
        if candidate not in check_paths:
            check_paths.append(candidate)

    for path_variant in check_paths:
        if path_variant and os.path.exists(path_variant):
            return os.path.abspath(path_variant)
    return None


async def upload_image_to_feishu(file_path: str) -> str | None:
    """上传图片到飞书 CDN，返回 image_key（用于卡片 img 元素）。

    支持 MinIO object_key 和本地文件路径。

    Args:
        file_path: object_key（如 hazard/xxx.jpg）或本地路径（如 uploads/safety/hazard/xxx.jpg）

    Returns:
        飞书 image_key（如 img_v3_xxx），失败返回 None
    """
    from app.core.storage import get_object
    from app.core.storage import is_enabled as minio_enabled

    image_data: bytes | None = None
    image_filename: str = os.path.basename(file_path)

    if minio_enabled():
        # Try MinIO first
        result = get_object("safety", file_path)
        if result is not None:
            image_data, _ = result
        else:
            # Fallback to local with robust path resolution
            abs_path = _resolve_local_image_path(file_path)
            if abs_path:
                with open(abs_path, "rb") as f:
                    image_data = f.read()
    else:
        abs_path = _resolve_local_image_path(file_path)
        if not abs_path:
            logger.warning("图片文件不存在，跳过上传: %s (checked multiple variants)", file_path)
            return None
        with open(abs_path, "rb") as f:
            image_data = f.read()

    if not image_data:
        logger.warning("无法读取图片数据，跳过上传: %s", file_path)
        return None

    try:
        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)

        async with httpx.AsyncClient(timeout=30) as http_client:
            resp = await http_client.post(
                "https://open.feishu.cn/open-apis/im/v1/images",
                headers={"Authorization": f"Bearer {token}"},
                files={"image": (image_filename, image_data, "image/jpeg")},
                data={"image_type": "message"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    image_key = data.get("data", {}).get("image_key", "")
                    if image_key:
                        logger.info("图片上传飞书成功: %s → %s", file_path, image_key)
                        return image_key
                logger.error("上传图片到飞书失败: %s", data)
            else:
                logger.error("上传图片到飞书 HTTP错误: %s", resp.status_code)
    except Exception:
        logger.exception("上传图片到飞书异常: %s", file_path)
    return None


async def upload_images_batch(file_paths: list[str]) -> list[str]:
    """批量并发上传图片到飞书 CDN，返回有效的 image_key 列表。"""
    if not file_paths:
        return []
    results = await asyncio.gather(
        *[upload_image_to_feishu(p) for p in file_paths],
        return_exceptions=True,
    )
    return [r for r in results if isinstance(r, str) and r]
