"""职称评审多维表格（Bitable）API 客户端 —— 兼容 shim。

实际实现收敛在 app/platform/integrations/feishu/bitable.py（平台集成层），
本模块保留原有公开符号（TitleReviewBitableError、update_record、list_all_records、
list_tables、list_fields、batch_create_records、subscribe_bitable、create_grid_view），
供 service.py / bitable_handler.py / 测试按原路径引用。
"""

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
