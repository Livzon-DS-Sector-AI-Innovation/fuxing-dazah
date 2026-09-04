"""仓储 Agent 技能库（S1 ticket 08，spec Implementation Decisions 6）。

技能 = markdown 文件（本目录 ``*.md``），三段式结构：
1. frontmatter 触发描述（``name`` / ``description``，目录注入用）；
2. ``## 步骤``（调哪些工具、什么顺序、参数要点）；
3. ``## 输出格式``（卡片模板）。

系统提示词只注入技能目录（一行一条：名称 + 触发描述，``registry.
default_registry.catalog_markdown()``），Agent 判断任务匹配后再调
``load_skill(name)`` 工具拉取完整 SOP——按需加载，上下文经济。

红线：技能只编排既有工具（查询/计划/记忆/办公），不引入新权限；SOP 中的
催办目标映射（班组长姓名）仅作报告展示信息，真实外发必须经 send_card
确认门（用户提供确切 open_id/chat_id）。
"""
