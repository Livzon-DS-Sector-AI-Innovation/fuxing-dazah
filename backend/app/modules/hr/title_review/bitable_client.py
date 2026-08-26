"""职称评审多维表格（Bitable）API 客户端 —— 兼容 shim。

实际实现收敛在 app/platform/integrations/feishu/bitable.py（平台集成层），
本模块保留原有公开符号（TitleReviewBitableError、update_record、list_all_records、
list_tables、list_fields、batch_create_records、subscribe_bitable、create_grid_view），
供 service.py / bitable_handler.py / 测试按原路径引用。
"""

from app.core.config import get_settings
from app.platform.integrations.feishu import bitable as _platform_bitable
from app.platform.integrations.feishu.bitable import (  # noqa: F401
    BitableAPIError,
    batch_create_records,
    create_grid_view,
    list_all_records,
    list_fields,
    list_tables,
    subscribe_bitable,
    update_record,
)

# HR 独立飞书应用（职称评审专用）：已配置时表格读写优先用它，不影响平台全局应用
_settings = get_settings()
if _settings.HR_TITLE_REVIEW_FEISHU_APP_ID and _settings.HR_TITLE_REVIEW_FEISHU_APP_SECRET:
    _platform_bitable.set_default_app(
        _settings.HR_TITLE_REVIEW_FEISHU_APP_ID,
        _settings.HR_TITLE_REVIEW_FEISHU_APP_SECRET,
    )

# 兼容旧异常名（业务代码与测试均 catch 此名字）
TitleReviewBitableError = BitableAPIError

__all__ = [
    "TitleReviewBitableError",
    "subscribe_bitable",
    "batch_create_records",
    "update_record",
    "list_all_records",
    "list_tables",
    "list_fields",
    "create_grid_view",
]
