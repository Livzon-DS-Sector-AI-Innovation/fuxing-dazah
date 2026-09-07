"""仓储模块暴露给外部 AI Agent 的 MCP Tools（只读）。

仅注册 4 个只读查询工具（query_mcp）；写入工具只存在于飞书对话 Runner
（agent/tools/），不进入 MCP 端点（外部 Agent 经 MCP 写入会绕过确认门，
安全决策见 spec Implementation Decisions 4）。
"""

from app.modules.warehouse.mcp_tools.query_mcp import (  # noqa: F401
    query_material,
    query_movements,
    query_report,
    query_stock,
)
