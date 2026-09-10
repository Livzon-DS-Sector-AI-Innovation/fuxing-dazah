"""业务 Agent 工具集。

- ``registry.py``：工具注册表 + ``is_write`` 标记
- ``read_tools.py``：只读工具（查隐患/检查/事故 + 知识库检索）
- ``write_tools.py``：写工具（建隐患/派整改），标记 ``requires_approval=True``

工具体内通过 ``ctx.deps.db`` 调用各子功能的已有 service，**不重写业务逻辑**。
"""

from app.modules.safety.business_agent.tools.registry import (
    TOOL_KIND,
    register_all_tools,
)

__all__ = ["TOOL_KIND", "register_all_tools"]
