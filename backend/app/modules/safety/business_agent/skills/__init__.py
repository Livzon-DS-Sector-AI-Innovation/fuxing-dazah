"""安全业务 Agent 技能（SOP）包。

约定（对齐仓储 agent/skills 模式）：
1. 三段式 markdown：frontmatter（``name``/``description``，目录注入用）
   + ``## 步骤``（调哪些工具、顺序、参数要点）+ ``## 输出格式``（模板）；
2. 按需加载：系统提示词只注入目录一行一条，Agent 判断匹配后才
   ``load_skill(name)`` 拉全文——上下文经济；
3. 红线：技能只编排既有工具、不引入新权限；写操作走既有确认流；
   事实性数据来自工具结果，禁止编造。
"""

from app.modules.safety.business_agent.skills.registry import (
    SkillRegistry,
    default_registry,
)

__all__ = ["SkillRegistry", "default_registry"]
