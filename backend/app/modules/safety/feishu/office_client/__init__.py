"""飞书办公聚合客户端（包）。

从原单文件 office_client.py 拆分而来，对外契约保持不变：
FeishuOfficeClient / OfficeResult / build_office_client / get_office_client。
"""

from app.modules.safety.feishu.office_client._base import OfficeResult
from app.modules.safety.feishu.office_client._client import (
    FeishuOfficeClient,
    build_office_client,
    get_office_client,
)
from app.modules.safety.feishu.office_client._slides import (
    _build_slide_xml as _build_slide_xml,
)
from app.modules.safety.feishu.office_client._slides import (
    _normalize_slide_content as _normalize_slide_content,
)

__all__ = [
    "OfficeResult",
    "FeishuOfficeClient",
    "build_office_client",
    "get_office_client",
]
