"""安全模块业务 Agent（business_agent）

将安全模块从「单轮只读 RAG」升级为可调用平台业务功能的对话式业务 Agent。

配置约定（区别于其它 AI 工作流的 prompts.py）：
- 软性配置（人设 / 语言习惯 / 能力清单 / 业务规则）→ ``agent.md``（人可编辑，走 git review）
- 硬护栏（权限校验 / 写操作确认 / 输出校验 / 禁语）→ ``rules.py`` + ``permissions.py``（代码强制，非提示词软约束）

详见 README.md。
"""

from app.modules.safety.business_agent.loader import (
    load_instructions,
    reload_instructions,
)

__all__ = ["load_instructions", "reload_instructions"]
