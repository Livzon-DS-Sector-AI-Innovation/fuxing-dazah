"""设备模块飞书通知 — 使用平台 FEISHU_APP_ID 发送验收交互卡片。"""

import asyncio
import json
import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def _get_client():
    """获取飞书客户端（使用平台级 FEISHU_APP_ID 凭据）。"""
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
    """获取 tenant_access_token（使用平台级凭据）。"""
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
            f"平台 token 获取失败: code={resp.code}, msg={resp.msg}"
        )
    if resp.raw and resp.raw.content:
        data = json.loads(resp.raw.content.decode("utf-8"))
        token = data.get("tenant_access_token", "")
        if token:
            return token
    raise RuntimeError("平台 token 响应为空")


def _read_file_bytes(path: str) -> bytes:
    """同步读取文件全部字节（供 asyncio.to_thread 使用）。"""
    with open(path, "rb") as f:
        return f.read()


async def _upload_image_to_feishu(
    image_data: bytes,
    client,
) -> str | None:
    """上传图片到飞书 CDN，返回 image_key。使用 SDK 原生接口。"""
    from io import BytesIO

    from lark_oapi.api.im.v1 import (
        CreateImageRequest,
        CreateImageRequestBody,
        CreateImageResponse,
    )

    try:
        request: CreateImageRequest = (
            CreateImageRequest.builder()
            .request_body(
                CreateImageRequestBody.builder()
                .image_type("message")
                .image(BytesIO(image_data))
                .build()
            )
            .build()
        )
        response: CreateImageResponse = await client.im.v1.image.acreate(request)
        if response.success() and response.data:
            image_key = getattr(response.data, "image_key", "") or ""
            if image_key:
                logger.info(
                    "图片上传飞书成功: size=%d → %s",
                    len(image_data), image_key,
                )
                return image_key
        else:
            logger.warning(
                "飞书图片上传失败: code=%s, msg=%s", response.code, response.msg,
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
    """发送验收通知 — 使用飞书模板卡片 AAqWOoLCSj8fh。

    使用平台 FEISHU_APP_ID 凭据发送。
    """
    logger.info("send_verification_card: user=%s, wo=%s",
                feishu_user_id, work_order_no)
    try:
        client = await _get_client()
        token = await _get_tenant_token(client)

        # ── 上传现场照片到飞书 CDN（最多 3 张）──
        uploaded_img_keys: list[dict] = []
        for img_path in (image_paths or [])[-3:]:
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

                img_key = await _upload_image_to_feishu(img_data, client)
                if img_key:
                    uploaded_img_keys.append({"img_key": img_key})
            except Exception:
                logger.exception("处理照片失败: %s", img_path)

        # ── 构建模板变量 ──
        template_variable: dict = {
            "wo_no": work_order_no,
            "wo_equipment": equipment_name,
            "wo_content": repair_detail or "（无维修描述）",
            "wo_repair_man": assignee_name or "未知",
            "wo_id": work_order_id,
            "wo_images": uploaded_img_keys,
        }

        card_content = {
            "type": "template",
            "data": {
                "template_id": "AAqWOoLCSj8fh",
                "template_variable": template_variable,
            },
        }

        content_json = json.dumps(card_content, ensure_ascii=False)

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
                .content(content_json)
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
