"""安全模块暴露给外部 AI Agent 的 MCP Tools（只读）。

仅注册 5 个只读查询工具（query_mcp，2-E 暴露侧首批口径）；写入工具只存在于
business_agent/tools/（经 execute_tool 管道 + requires_approval 确认门），
不进入 /mcp/safety 端点（外部 Agent 经 MCP 写入会绕过确认门——结构性排除，
非运行时过滤）。扩充暴露面需重新评审（首批 5 个口径见二期 spec）。
"""

from app.modules.safety.mcp_tools.query_mcp import (  # noqa: F401
    query_chemical_inventory,
    query_hazard_stats,
    query_hazards,
    query_latest_regulations,
    query_special_op_records,
)
