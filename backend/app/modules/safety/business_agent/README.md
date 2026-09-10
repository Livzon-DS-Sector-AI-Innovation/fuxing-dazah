# 安全模块业务 Agent（business_agent）

将安全模块的「信息查询」从单轮只读 RAG 升级为**可调用平台业务功能的对话式业务 Agent**：
用户在飞书/Web 下命令 → Agent 识别用户身份 → 按固定权限调用业务功能 → 写操作先出方案待确认 → 执行并审计。

## 配置约定（重要，区别于其它 AI 工作流）

安全模块其它 AI 工作流（`ai_hazard_identification`、`ai_rectification_review` 等）的人设/规则写在 Python `prompts.py` 常量里。
**本 Agent 不同**——采用「软硬分离」：

| 类型 | 载体 | 是否强制 | 谁维护 |
|------|------|----------|--------|
| 软性：人设 / 语言习惯 / 能力清单 / 业务规则 | `agent.md`（Markdown） | 引导，模型可能不遵守 | 安全管理人员可直接编辑，走 git |
| 硬护栏：用户权限 / 写操作确认 / 输出校验 / 禁语拦截 | `permissions.py` / `rules.py` / `executor.py`（代码） | **代码强制** | 开发者 |

**铁律**：安全底线绝不能只写在 `agent.md` 里指望模型自觉。授权、写确认等一律在工具执行层由代码强制。

## 文件结构

```
business_agent/
├── agent.md          # 软性配置（人设/语言习惯/能力/业务规则）
├── README.md         # 本文件
├── loader.py         # 读 agent.md → instructions（UTF-8、缓存、reload）
├── agent.py          # Pydantic AI Agent 定义 + SafetyDeps（依赖 pydantic-ai）
├── executor.py       # run_turn / resume：驱动 agent，写操作挂起为 PendingAction
├── rules.py          # 硬护栏：RuleEngine 输出校验 + BANNED_PHRASES（复用隐患识别的列表）
├── permissions.py    # ROLE_TOOL_POLICY + check()，deny-by-default
├── schemas.py        # SafetyDeps / PendingActionData / 输入输出模型
├── models.py         # ORM：agent_sessions / agent_messages / agent_pending_actions
├── session_store.py  # 会话历史 + PendingAction 持久化
└── tools/
    ├── registry.py   # 工具注册 + is_write 标记
    ├── read_tools.py # 查隐患/检查/事故 + knowledge_search（薄包装现有 service）
    └── write_tools.py# 建隐患/派整改（requires_approval）
```

## 身份与权限

- 飞书入口：从 `im.message.receive_v1` 事件读 `sender_id.user_id`（**非 open_id**，安全 App open_id 与 `identity.users` 命名空间不一致）→ 经 `IdentityResolver.resolve_by_user_id()` 映射到 `identity.users`。
- 权限：`agent_user_roles(feishu_user_id → role)` 表定「谁是什么角色」，`permissions.py` 的 `ROLE_TOOL_POLICY` 定「每个角色能调哪些工具、哪些需确认」。deny-by-default。

## 框架

Pydantic AI。自带模型层，指向与 `SAFETY_AI_TEXT_*` 相同的 DeepSeek 端点，**不改动** `app/platform` 的 `AIService`；与现有 RAG / 隐患识别工作流并存互不干扰。
