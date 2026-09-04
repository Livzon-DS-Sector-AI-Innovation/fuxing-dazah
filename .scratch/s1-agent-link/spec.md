# S1 — 仓储 Agent 消息链路 + 查询 + Harness 元能力（Spec）

**日期**: 2026-09-03
**状态**: ready-for-agent
**上游**: 设计文档 V1.0-2（六层架构+Harness）/ V1.0-3（交互管线）/ V1.0-8（S1=原S4并入）；S0 地基已就绪（commit 38cf2df）

## Problem Statement

S0 交付了 Agent 的「手」（LLM 客户端、Base 适配器），但 Agent 还没有「耳朵和嘴」：warehouse 机器人（cli_aaa0eaf293fa5be0）收不到消息、无法对话、不能查询 Base、不能执行办公任务。S1 要把整条交互链路打通——用户在手机飞书对机器人说话/提问，Agent 理解意图、调用工具查真实数据、以卡片回复——并叠加 Harness 元能力（任务计划器、技能库、长期记忆、办公工具），使其成为能执行业务与办公任务的完整 Agent。

## Solution

分两批交付 8 个 ticket。**第一批（链路）**：warehouse 模块内自建原生 WebSocket 事件客户端（照搬 safety 模块成熟模式，绕开 lark_oapi SDK 单实例限制，WAREHOUSE_FEISHU_* 独立凭证）→ gateway 消息路由（去重/会话定位/占位卡片）→ Runner tool-calling 循环（复用 S0 的 WarehouseLLMClient + 4 个查询工具）→ 查询结果卡片渲染与回复。**第二批（Harness）**：任务计划器（plan_task/update_plan + 进度卡片）→ 长期记忆（recall/save + 会话注入）→ 办公工具（send_card 卡片确认门 / create_reminder 动态提醒）→ 技能库框架 + 首批 2 技能（呆料分析催办 / 复验期预警）。

## User Stories

1. 作为仓管员，我在手机飞书私聊机器人发「硫酸还有多少放行的」，5 秒内收到库存卡片（批号/数量/库位）。
2. 作为仓管员，我在群里 @仓库管理机器人提问，得到同样的回复（仅@消息响应，不刷屏）。
3. 作为仓管员，我发一张图片给机器人，得到友好引导（S2 才支持识别，S1 不误报错误）。
4. 作为仓管员，我让机器人「盘本月呆料并催办各班组长」，它先展示计划（分步进度卡片），逐步执行。
5. 作为仓管员，我对机器人说「以后报表别带包材」，它记住并在后续交互生效。
6. 作为仓管员，我让机器人把呆料报告发给某班组长，它先出预览卡片等我点「确认发送」，我不会误发。
7. 作为仓管员，我让机器人「明早 8 点提醒我看出报情况」，到点收到提醒卡片。
8. 作为开发者，Agent 的每次工具调用都有审计记录，会话历史可追溯。

## Implementation Decisions（2026-09-03 质询定稿）

1. **WS 实现照搬 safety 模式**：`warehouse/feishu/event_client.py` 用原生 WebSocket + protobuf（`websockets` 库 + 飞书 `/callback/ws/endpoint`），WAREHOUSE_FEISHU_* 独立凭证，无限重连，`@on_event` 注册表分发。理由：lark_oapi SDK WS 是模块级全局 loop 单实例（main.py 注释明确），平台全局应用已占用；safety/设备模块已验证此模式可多实例并行。
2. **发送通道自建**：`warehouse/feishu/notification.py` 用独立凭证发消息/卡片（仿 safety/feishu/notification.py）——platform 的 send_group_card 走全局凭证，不复用。
3. **main.py 接线**（黄色操作，质询方案 preview 已含并获确认）：仿 safety 加 `warehouse_ws_task = asyncio.create_task(start_ws())` + lifespan stop，约 4 行；`WAREHOUSE_FEISHU_WS_ENABLED` 键补进 config.py（S0 漏声明，env 已有值）。
4. **gateway 职责**：事件去重（复用平台 Redis 模式）、会话定位（chat_id+open_id → sessions 表）、占位卡片（「⏳ 正在处理…」，完成后更新/新发结果卡片）、卡片按钮回调路由（card.action.trigger → 确认门）、群@检测（仅提及消息响应）、图片消息友好引导（S2 接管）、兜底降级话术。
5. **Runner v1**：tool-calling 循环（WAREHOUSE_AGENT_MAX_TURNS=6/TIMEOUT），上下文=系统提示词+会话历史（SESSION_ROUNDS=12 裁剪）+pending 草稿摘要；终局判定=无 tool_calls 且 content 非空（reasoning 契约）；工具结果截断 4KB/条。4 个查询工具为纯 async 函数（注册表结构，S3 套 MCP 壳）：query_stock（库存明细表，按名称/批号/三态/复验期过滤）、query_material（一览表主数据）、query_movements（入/出库总账汇总）、query_report（呆料/不合格清单）。
6. **Harness**：计划器（plan_task/update_plan 工具+plans 表+进度卡片 patch）；记忆（recall_memory/save_memory 工具+memories 表+会话开始注入用户偏好 top3+全局惯例 top5；记忆只影响表达不影响数据）；办公工具 send_card（**HITL 确认门**：预览卡片[确认发送][取消]→回调路由→仅发起人生效，pending 状态存 drafts 表 scene=confirm_action——S2 识别草稿复用同一回调机制）、create_reminder（scheduler register_generator 动态任务）；技能库（agent/skills/*.md 三段式：触发描述+步骤+输出格式，系统提示词只注入目录，load_skill 按需拉取；首批 dead-stock-analysis、expiring-check）。
7. **配置键新增**（config.py，S1 补）：WAREHOUSE_FEISHU_WS_ENABLED、WAREHOUSE_AGENT_MAX_TURNS、WAREHOUSE_AGENT_SESSION_ROUNDS、WAREHOUSE_TEST_CHAT_ID（可选，冒烟测试用）。

## Testing Decisions

- **全 live + 发送 dry-run**（质询定稿）：LLM 真调、Base 真查（真实测试版 Base）、表真读写；**消息发送类 dry-run**——单测构建卡片断言内容但不真发；`notification.py` 提供 `dry_run` 注入口。
- **两条接缝**：
  - 主接缝 `gateway.handle_event(event_dict)`：模拟 im.message.receive_v1 payload（文本/群@/图片/卡片回调），全链路真实（路由→Runner→工具→Base→卡片构建→发送 dry-run 捕获）。
  - Harness 组件直测：PlanService（plans 表读写+步骤状态机）、SkillRegistry（load 返回完整 SOP）、MemoryService（recall/save+注入排序）、ConfirmService（请求→预览→点确认→执行；仅发起人可点）。
- 冒烟测试（手动）：WAREHOUSE_TEST_CHAT_ID 配置时真发一条卡片到测试群；未配置则 skip。
- 运行：`DATABASE_URL=...whdev uv run pytest tests/modules/warehouse/ -v`（live 套件与 S0 同库不同文件）。

## Out of Scope

- 图片识别与 Draft 状态机（S2）；MCP 端点挂载（S3）；submit 写 Base 工具（S2）
- delegate 子委派、后台任务引擎（V1.1）
- 群消息主动推送引擎（Base workflow 继续负责，V2 才迁移）
- WS 事件的多 worker 水平扩展（单进程假设，与 safety 一致）

## Further Notes

**实现偏差补记（2026-09-03 审查后确认）**：
- MAX_TURNS 默认值取 **10**（非决策 5 的 6）——票05 live 实测多步计划任务 6 轮耗尽；
- create_reminder 采用 asyncio 延时任务表 + drafts 落库（非决策 6 的 scheduler register_generator——其为启动期静态注册；重启不恢复提醒，完整方案 V1.1）；
- 确认门终态前置：confirmed 状态在回调执行前落库（防重复发送），回调失败置 failed 不回滚 pending；gateway ACK 窗口用 asyncio.shield 防止 2.9s 超时取消导致状态回滚。

- safety 的 event_client 约 300 行（连接+protobuf+分发），warehouse 版本预期同量级；protobuf 解码逻辑直接参照，不改 safety。
- gateway 的卡片回调与 S2 识别确认共用路由注册表——S1 设计回调路由时留 scene 字段。
- 机器人 open_id `ou_260db4ff7c9b361b9374c9516d3766ab`（去重时排除机器人自身消息）。
