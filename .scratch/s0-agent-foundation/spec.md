# S0 — 仓储 Agent 地基（Spec）

**日期**: 2026-09-03
**状态**: ready-for-agent
**上游设计**: `backend/docs/warehouse-module-design.md`（V1.0-2 / V1.0-4 / V1.0-5 / V1.0-8）

## Problem Statement

仓储 Agent（V1.0）需要调用两个外部系统——DeepSeek 模型 API（对话+识别）和飞书多维表格（业务数据读写）。当前 dazah 后端没有：可发起 tool-calling 的模型客户端、面向 4 个测试版 Base 的读写适配器（含实测踩坑得来的写契约）、Agent 状态表（草稿/会话/审计/计划/记忆）、以及仓储专属飞书应用与 Agent 模型的配置键。没有这些地基，S1 的消息链路与 Runner 无法开工。

## Solution

在 `app/modules/warehouse/` 内新建两类基础设施组件：带 tool-calling 能力的 LLM 客户端（直连 DeepSeek 网关）、飞书 Base 读写适配器（复用 platform 现有 bitable 传输层并传入仓储应用凭证，写契约校验内置）。同时在 `app/core/config.py` 补充 WAREHOUSE_* 配置键（纯字段声明，对齐 METER_AI_*/SAFETY_FEISHU_* 既有模式），并新增 Alembic 迁移一次性建齐 5 张 Agent 状态表。

## User Stories

1. 作为 Agent Runner（S1 开发者），我要能调用一个支持 function calling 的 LLM 客户端，发起工具调用循环，以便实现自然语言查询与业务任务。
2. 作为 Agent Runner，我要从模型响应中拿到结构化的 tool_calls / content / reasoning_content，以便正确判断「终局回复」与「继续调用工具」。
3. 作为 Agent 工具层（S1 开发者），我要通过适配器按业务语义查询 4 个测试版 Base 的记录，以便回答库存/物料/流水/报表问题。
4. 作为 Agent 工具层，我要通过适配器向 Base 写入记录，且写入前字段与选项已被校验（单选传字符串、字段名精确、只读字段拒写），以便避免实测踩过的格式坑导致静默失败。
5. 作为平台运维者，我要仓储飞书应用与 Agent 模型的凭证集中配置在 Settings，以便环境切换时只改 env。
6. 作为后续阶段（S1/S2），我要 5 张 Agent 状态表已建好，以便草稿/会话/审计/计划/记忆有持久化载体。

## Implementation Decisions（2026-09-03 质询定稿）

1. **LLM 客户端在 warehouse 模块内新建**（`app/modules/warehouse/agent/llm_client.py`），不触碰 `platform/integrations/ai/client.py` 的逻辑——用户拍板，platform 零逻辑改动。
2. **配置键对齐既有模式**：`core/config.py` 的 Settings 加 WAREHOUSE_* 字段（纯声明、默认空串），S0 仅加当前需要的键：`WAREHOUSE_FEISHU_APP_ID/SECRET`、4 个 `WAREHOUSE_FEISHU_BITABLE_*_APP_TOKEN`、`WAREHOUSE_AGENT_BASE_URL/API_KEY/MODEL/TIMEOUT`；其余运行时键（MAX_TURNS 等）S1 按需补。
3. **bitable 适配器复用 platform 传输层**：调 `platform/integrations/feishu/bitable.py` 的 `_request` 系（该层已支持传入独立应用凭证且 token 缓存按 `app_id:app_secret` 隔离），适配器传入 warehouse 凭证——platform 文件零改动。
4. **写契约内置**（实测结论，见设计文档 V1.0-5）：单选字段写**纯字符串**（读取返回数组，读写不对称）；字段键只用字段名；重复选项名字段写入会失败（已知：物料名称字段，S2 走降级）；lookup/formula/created_by/auto_number 拒写；错误码分类（91403 权限 / 1254045 字段名 / 1254062 选项值 / 1254291 并发）。
5. **字段映射常量**（`bitable_schema.py`）：核心表（物料入库总账/出库总账/库存明细、GMP 两表、成品出库台账、销售明细）的字段名+类型+单选选项集快照，来源 `base_scan/` 摸底数据；适配器写前校验用，运行时可用 `list_fields` 刷新缓存。
6. **5 张辅助表一次建齐**（Alembic 迁移，黄色操作已确认）：`warehouse_agent_drafts / sessions / audit / plans / memories`，schema=`warehouse`（已存在，无需 CREATE SCHEMA），字段定义按设计文档 V1.0-4，继承 BaseModel。
6b. **drafts.status 枚举**为完整状态机取值（created/aligned/pending_confirm/confirmed/submitted/expired/cancelled），比设计文档 V1.0-4 的摘要描述更细——以本 spec 为准。
7. **S0 不含 Runner**：LLM 客户端只提供 `chat_with_tools()` 单次调用原语；循环/提示词/会话管理在 S1。

## Testing Decisions

- **全 live 测试**（用户拍板）：所有测试打真实 API——真实 DeepSeek 网关（WAREHOUSE_AGENT_*）+ 真实测试版 Base（LmuBb3 等）。理由：格式坑（单选字符串、reasoning_content、max_tokens）纯 mock 无法复现，mock 通过≠真实可用。
- **两条接缝**（不造 facade）：
  - 接缝① `WarehouseLLMClient.chat_with_tools()`：验证 tools 往返（发起 tool_calls→回填结果→终局回复）、reasoning 契约（content 非空判定、max_tokens 给足）、多轮消息协议。
  - 接缝② warehouse bitable 适配器：验证 写→读→删 往返、写契约校验（合法值通过/非法选项被拦/只读字段拒写）、错误分类。
- **live 测试数据纪律**：写测试记录必须清理（删除）；优先用低风险表（成品销售-测试版 10月汇总表 `tbl2ANgtopqvgvbr` 或物料系统-测试版备用表）；同表串行避免 1254291。
- **迁移验证**：`alembic upgrade head` 到 `dazah_whdev`（DATABASE_URL 覆盖）+ downgrade/upgrade 往返 + 表结构断言（列/索引/schema）。
- 先例：`tests/modules/warehouse/` 已有 conftest 与 API 测试组织方式；live 标记约定为模块内新增 `test_live_*.py`。

## Out of Scope

- Runner 循环、系统提示词、会话管理（S1）
- 飞书 WS 客户端、gateway、消息/卡片（S1）
- 识别 pipeline、Draft 状态机、submit 工具（S2）
- MCP 端点挂载（S3）
- 计划器/技能库/记忆的业务逻辑（S1 harness，S0 仅建 plans/memories 表）
- 物料名称重复选项治理（业务方暂缓，S2 降级方案）

## Further Notes

- `.env.development` 已含全部 WAREHOUSE_* 实际值（模型 KEY 2026-09-03 五重验证通过：function calling 原生支持、reasoning 模型契约实测）。
- deepseek-v4-flash-vision-exp 是 reasoning 模型：响应含 `reasoning_content`+`content`；max_tokens 过小会被 reasoning 耗尽致 content 空（实测 8→空、200→正常）；tool-call 轮 content 可能为空。
- 测试命令需带 `DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"` 覆盖（旧 dazah 库不可用）。
