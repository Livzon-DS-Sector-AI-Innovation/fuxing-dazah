"""飞书文件发送原语（叶子模块）。

把「上传 im.v1.file → 发送 file 消息」从 ``business_agent_bot_handler`` 抽离，
供 bot handler 与 Agent 工具层（如 generate_guardian_subsidy）共同复用，
避免 tools → bot_handler → executor → tools 的循环 import。

本模块只依赖 ``feishu.client`` 与 lark_oapi，不 import 任何业务模块。
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from app.modules.safety.feishu.client import (
    get_safety_feishu_client,
    get_safety_tenant_token,
)

logger = logging.getLogger(__name__)


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=lambda o: str(o) if isinstance(o, uuid.UUID) else o)


def _file_type_for_name(file_name: str) -> str:
    """按扩展名映射飞书 IM 上传 file_type，兼容既有 Excel 与 office 生成文件。"""
    ext = os.path.splitext(file_name or "")[1].lower()
    return {
        ".docx": "doc",
        ".doc": "doc",
        ".pdf": "pdf",
        ".xlsx": "xlsx",
        ".xls": "xls",
        ".csv": "csv",
        ".json": "stream",
    }.get(ext, "stream")


async def send_file_to_chat(chat_id: str, file_bytes: bytes, file_name: str) -> bool:
    """上传文件到飞书并发送到会话（发送原语，供 bot handler / 工具层复用）。

    Args:
        chat_id: 飞书 chat_id
        file_bytes: 文件二进制内容
        file_name: 文件名（含扩展名）

    Returns:
        True 表示发送成功
    """
    try:
        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)

        # ── ① 上传文件 → 获取 file_key ──
        import io as _io

        from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody

        create_req = (
            CreateFileRequest.builder()
            .request_body(
                CreateFileRequestBody.builder()
                .file_type(_file_type_for_name(file_name))
                .file_name(file_name)
                .file(_io.BytesIO(file_bytes))
                .build()
            )
            .build()
        )
        create_req.headers["Authorization"] = f"Bearer {token}"
        create_resp = await client.im.v1.file.acreate(create_req)
        if not create_resp.success():
            logger.error("上传文件失败: code=%s msg=%s", create_resp.code, create_resp.msg)
            return False

        file_key = create_resp.data.file_key
        logger.info("文件上传成功: file_key=%s name=%s", file_key, file_name)

        # ── ② 发送文件消息 ──
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        send_req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("file")
                .content(_json_dumps({"file_key": file_key}))
                .build()
            )
            .build()
        )
        send_req.headers["Authorization"] = f"Bearer {token}"
        send_resp = await client.im.v1.message.acreate(send_req)
        if not send_resp.success():
            logger.error("发送文件消息失败: code=%s msg=%s", send_resp.code, send_resp.msg)
            return False

        logger.info("文件消息已发送: file_key=%s chat_id=%s", file_key, chat_id)
        return True

    except Exception:
        logger.exception("发送飞书文件异常")
        return False
