"""底座附件能力：高级权限多维表格的附件下载鉴权参数。

迁移自 legacy ``feishu.bitable_handler._build_attachment_extra``（票据 08），
语义逐字保持不变，只是搬到公共底座，避免域包 import 旧处理器的内部函数。
"""

from __future__ import annotations

import json
import urllib.parse


def build_attachment_extra(
    table_id: str,
    record_id: str,
    field_id: str,
    file_token: str,
) -> str:
    """构建高级权限多维表格的附件下载 extra 鉴权参数（URL-encoded JSON）。

    飞书要求格式：
    {"bitablePerm": {"tableId": "...", "attachments": {"fldXXX": {"recXXX": ["file_token"]}}}}
    """
    payload = {
        "bitablePerm": {
            "tableId": table_id,
            "attachments": {
                field_id: {record_id: [file_token]},
            },
        },
    }
    return urllib.parse.quote(json.dumps(payload, separators=(",", ":")))
