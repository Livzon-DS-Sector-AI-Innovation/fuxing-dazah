"""办公工具公共序列化辅助。"""

from __future__ import annotations

import base64
from typing import Any

from app.modules.safety.feishu.office_client import OfficeResult


def _result_to_dict(result: OfficeResult, action: str) -> dict[str, Any]:
    """把 OfficeResult 转成 Pydantic AI 可序列化的 dict。

    - kind=error 时统一包装为人类可读错误。
    - kind=file 时二进制 bytes 转 base64（content_base64），不直接把 bytes
      塞进工具返回（避免 Pydantic AI 序列化失败）。
    """
    if result.kind == "error":
        return {
            "kind": "error",
            "error": f"{action}失败：{result.error}",
        }

    out: dict[str, Any] = {
        "kind": result.kind,
        "truncated": bool(result.truncated),
    }
    if result.content is not None:
        out["content"] = result.content
    if result.url is not None:
        out["url"] = result.url
    if result.file_token is not None:
        out["file_token"] = result.file_token
    if result.file_name is not None:
        out["file_name"] = result.file_name
    if result.size is not None:
        out["size"] = result.size
    if result.message is not None:
        out["message"] = result.message

    if result.bytes is not None:
        out["content_base64"] = base64.b64encode(result.bytes).decode()
        out.setdefault(
            "message",
            "文件二进制内容以 base64 返回（content_base64），可通过 file_token 在飞书云空间访问",
        )

    if result.meta:
        for key, value in result.meta.items():
            out.setdefault(key, value)
    return out
