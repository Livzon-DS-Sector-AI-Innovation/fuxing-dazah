"""设备模块飞书 DM 通知 — 使用设备交互机器人凭证发送卡片消息。"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)


def _read_file_bytes(path: str) -> bytes:
    """同步读取文件全部字节（供 asyncio.to_thread 使用）。"""
    with open(path, "rb") as f:
        return f.read()


async def send_user_card(
    open_id: str,
    title: str,
    content: str,
    elements: list[dict] | None = None,
    receive_id_type: str = "user_id",
) -> bool:
    """使用设备机器人发送卡片消息给单个用户（DM）。

    Args:
        open_id: 接收者标识（含义由 receive_id_type 决定）
        title: 卡片标题
        content: 卡片正文（支持 markdown）
        elements: 额外的卡片元素
        receive_id_type: 接收者 ID 类型，"user_id" 或 "open_id"

    Returns:
        True 表示发送成功，False 表示失败
    """
    logger.info(
        "设备机器人 send_user_card: %s=%s", receive_id_type, open_id,
    )
    try:
        from app.modules.equipment.feishu.client import (
            get_equipment_feishu_client,
            get_equipment_tenant_token,
        )

        client = await get_equipment_feishu_client()
        token = await get_equipment_tenant_token(client)

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
            .receive_id_type(receive_id_type)
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
                "设备机器人 send_user_card 失败: user_id=%s, code=%s, msg=%s",
                open_id, resp.code, resp.msg,
            )
            return False
        logger.info("设备机器人卡片已发送: user_id=%s, title=%s", open_id, title)
        return True
    except Exception as e:
        logger.error(
            "设备机器人 send_user_card 异常: user_id=%s, %s: %s",
            open_id, type(e).__name__, e,
        )
        return False


async def _upload_image_to_feishu(
    image_data: bytes,
    token: str,
) -> str | None:
    """上传图片到飞书 CDN（multipart 方式），返回 image_key。

    飞书 IM 图片上传 API 必须使用 multipart/form-data 格式，
    SDK builder 风格（JSON body）不支持，需直接用 httpx 发送。
    """
    from io import BytesIO

    import httpx

    try:
        async with httpx.AsyncClient(timeout=30) as http_client:
            resp = await http_client.post(
                "https://open.feishu.cn/open-apis/im/v1/images",
                headers={"Authorization": f"Bearer {token}"},
                files={
                    "image": ("image.jpg", BytesIO(image_data), "image/jpeg"),
                },
                data={"image_type": "message"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    image_key = data.get("data", {}).get("image_key", "")
                    if image_key:
                        logger.info(
                            "图片上传飞书成功: size=%d → %s",
                            len(image_data), image_key,
                        )
                        return image_key
                logger.warning("飞书图片上传失败: %s", data)
            else:
                logger.warning(
                    "飞书图片上传 HTTP 错误: status=%s, body=%s",
                    resp.status_code, resp.text[:200],
                )
    except Exception:
        logger.exception("飞书图片上传异常: size=%d", len(image_data))
    return None


async def send_verification_card(
    feishu_user_id: str,
    work_order_no: str,
    equipment_name: str,
    assignee_name: str,
    priority: str,
    repair_detail: str = "",
    work_order_id: str = "",
    image_paths: list[str] | None = None,
) -> bool:
    """发送验收通知交互卡片（含描述、照片、验收/退回按钮）。

    先上传图片到飞书获取 image_key，再构建卡片发送。
    """
    logger.info("设备机器人 send_verification_card: user=%s, wo=%s",
                feishu_user_id, work_order_no)
    try:
        from app.modules.equipment.feishu.client import (
            get_equipment_feishu_client,
            get_equipment_tenant_token,
        )

        client = await get_equipment_feishu_client()
        token = await get_equipment_tenant_token(client)

        # 构建卡片 elements
        elements: list[dict] = []

        # 基本信息
        info_lines = [
            f"**工单编号：**{work_order_no}",
            f"**关联设备：**{equipment_name}",
            f"**优先级：**{priority}",
        ]
        if assignee_name:
            info_lines.append(f"**维修人员：**{assignee_name}")
        elements.append({
            "tag": "markdown",
            "content": "\n".join(info_lines),
        })

        # 维修描述
        if repair_detail:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "markdown",
                "content": f"**维修描述：**\n{repair_detail}",
            })

        # 现场照片
        image_paths = image_paths or []
        if image_paths:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "markdown",
                "content": f"**现场照片**（共 {len(image_paths)} 张）",
            })

            # 上传图片到飞书（最多3张，避免卡片过大）
            img_elements: list[dict] = []
            for idx, img_path in enumerate(image_paths[:3]):
                try:
                    from app.core.storage import get_object
                    from app.core.storage import is_enabled as minio_enabled

                    if minio_enabled():
                        result = await asyncio.to_thread(
                            get_object, "equipment", img_path,
                        )
                        if result:
                            img_data, _ = result
                        else:
                            continue
                    else:
                        import os

                        if not os.path.exists(img_path):
                            continue
                        img_data = await asyncio.to_thread(
                            _read_file_bytes, img_path,
                        )

                    img_key = await _upload_image_to_feishu(img_data, token)
                    if img_key:
                        img_elements.append({
                            "tag": "img",
                            "img_key": img_key,
                            "mode": "fit_horizontal",
                            "alt": {"tag": "plain_text", "content": "现场照片"},
                        })
                except Exception:
                    logger.exception("处理照片 %d 失败", idx)

            if img_elements:
                elements.extend(img_elements)
            else:
                elements.append({
                    "tag": "markdown",
                    "content": "（照片加载失败，请在系统中查看）",
                })

        # 操作按钮
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "✅ 验收通过"},
                    "type": "primary",
                    "value": json.dumps({
                        "action": "verify",
                        "work_order_id": work_order_id,
                        "result": "合格",
                    }),
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "↩️ 退回"},
                    "type": "danger",
                    "value": json.dumps({
                        "action": "verify",
                        "work_order_id": work_order_id,
                        "result": "不合格",
                    }),
                },
            ],
        })

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"🔧 工单待验收 - {work_order_no}",
                },
                "template": "orange",
            },
            "elements": elements,
        }

        card_json = json.dumps(card, ensure_ascii=False)

        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        req = (
            CreateMessageRequest.builder()
            .receive_id_type("user_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(feishu_user_id)
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
                "send_verification_card 失败: user=%s, code=%s, msg=%s",
                feishu_user_id, resp.code, resp.msg,
            )
            return False
        logger.info("验收卡片已发送: user=%s, wo=%s", feishu_user_id, work_order_no)
        return True
    except Exception as e:
        logger.error(
            "send_verification_card 异常: user=%s, %s: %s",
            feishu_user_id, type(e).__name__, e,
        )
        return False
