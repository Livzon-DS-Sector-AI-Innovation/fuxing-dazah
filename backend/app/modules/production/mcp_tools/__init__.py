"""生产模块 MCP Tools — 为一线工序负责人提供移动端（Agent）操作能力。

目标用户：由工段负责人配置的工序负责人，这些人可能无法接触电脑使用网页端生产工作台。
通过飞书 Agent 调用这些工具完成工序状态查询和操作。

工具函数通过 @mcp.tool() 装饰器注册到对应模块的 FastMCP 实例。
按业务功能拆分为 catalog / user_scope / execution / progress / fields / trace / plan 子模块。
"""

from app.modules.production.mcp_tools.catalog import (  # noqa: F401
    query_product_catalog,
)
from app.modules.production.mcp_tools.execution import (  # noqa: F401
    backfill_step_fields,
    change_batch_step_status,
)
from app.modules.production.mcp_tools.fields import (  # noqa: F401
    query_step_fields,
)
from app.modules.production.mcp_tools.plan import (  # noqa: F401
    query_plan_items_ending_on_date,
)
from app.modules.production.mcp_tools.progress import (  # noqa: F401
    query_batch_progress,
)
from app.modules.production.mcp_tools.trace import (  # noqa: F401
    query_batch_trace,
)
from app.modules.production.mcp_tools.user_scope import (  # noqa: F401
    query_user_active_batches,
    query_user_processes,
)
from app.modules.production.mcp_tools.workbench import (  # noqa: F401
    activate_planned_batch,
    query_workbench_todo,
    receive_batch,
)
