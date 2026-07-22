"""Equipment 模块暴露给 AI Agent 的 MCP Tools。

工具函数通过 @mcp.tool() 装饰器注册到全局 FastMCP 实例。
按业务域拆分为 work_order / inspection 两个子模块。
"""

from app.modules.equipment.mcp_tools._helpers import (  # noqa: F401
    _get_template_item_map,
    _it_to_dict,
    _resolve_equipment,
    _resolve_template,
    _resolve_work_order,
    _wo_to_dict,
)
from app.modules.equipment.mcp_tools.equipment import (  # noqa: F401
    search_equipments,
    update_equipment_running_status,
)
from app.modules.equipment.mcp_tools.inspection import (  # noqa: F401
    get_inspection_check_items,
    get_inspection_task_progress,
    list_inspection_tasks,
    submit_inspection,
    submit_inspection_photos,
    update_inspection_task,
)
from app.modules.equipment.mcp_tools.spare_part import (  # noqa: F401
    search_spare_parts,
)
from app.modules.equipment.mcp_tools.work_order import (  # noqa: F401
    create_work_order,
    list_work_orders,
    operate_work_order,
    submit_work_order_photos,
)
