# dazah 仓储模块（warehouse）设计文档

**日期**: 2026-09-03（V1.0 增补版）
**状态**: 待评审
**输入材料**:
- 《仓库AI应用实施计划》飞书文档 `Wkz0dUHLvokzDAxOAEscRKTBnrc`（13 项 AI 应用 + 共性能力 + 手机端约束）
- 4 个业务多维表格全量摸底（产物存于仓库 `base_scan/`）：物料系统 28 表 + 20 个自动化流程、GMP 质量物料 3 表、成品销售汇总 4 表、**成品产销存 42 表（2026-09-03 仓库专属应用实测已可访问）**
- 开源 WMS 调研（ERPNext / Odoo / InvenTree / JeeWMS / PaddleOCR）
- 现有 warehouse MVP 代码（`app/modules/warehouse/`，迁移 `97645df4a45e`）
- **仓库专属飞书应用凭证**（App ID `cli_aaa0eaf293fa5be0`，机器人「仓库管理机器人」，凭证已配置至本机 `backend/.env.development`，2026-09-03 实测验证）

## 版本路线总览（重要）

本设计分两卷，对应两个交付阶段：

| 卷 | 路线 | 数据面 | 用户入口 | 状态 |
|---|---|---|---|---|
| **上卷 V1.0** | **AI 植入多维表格**：dazah 作为 Agent 控制面，通过 Bitable API 读写现有 4 个 Base，业务数据不迁移 | 飞书多维表格（现状延续） | **手机 + 飞书机器人对话**（唯一入口） | 本版重点，立即启动 |
| 下卷 V2 | 平台化迁移：数据迁入 dazah PostgreSQL，完整业务管线与权限体系（原文档设计） | dazah 自建库 | Web 后台 + H5 + 机器人 | 规划保留，V1.0 验证后评估触发 |

**V1.0 决策理由**：业务方（仓储部）已在 Base 上运转全部日常业务，V1.0 不动数据、不动界面、不要求任何人切换习惯——dazah 只以「一个更聪明的机器人」形态切入（识别录入、查询、汇总推送），AI 价值最快兑现且零迁移风险。V2 的触发条件：Base 容量/性能瓶颈、流程需求超出飞书 workflow 能力、或业务方主动要求平台化。

---

# 上卷：V1.0 设计 —— 飞书机器人 Agent × 多维表格数据面

## V1.0-1. 仓库专属飞书应用（仓库管理机器人）

### 1.1 应用与凭证管理

| 项 | 值 |
|---|---|
| App ID | `cli_aaa0eaf293fa5be0` |
| 机器人名 | 仓库管理机器人（已激活，`activate_status=2`，open_id `ou_260db4ff7c9b361b9374c9516d3766ab`） |
| 配置键 | `WAREHOUSE_FEISHU_APP_ID` / `WAREHOUSE_FEISHU_APP_SECRET` / `WAREHOUSE_FEISHU_WS_ENABLED`（已写入 `backend/.env.development`，gitignore 文件） |
| 配置模式 | 对齐既有 `SAFETY_FEISHU_*` / `HR_TITLE_REVIEW_FEISHU_*` 每模块独立应用先例；Base token 走 `WAREHOUSE_FEISHU_BITABLE_*_APP_TOKEN` |

**安全红线**：App Secret 只存在于 `.env.{APP_ENV}`（gitignore），不进代码、不进本文档、不进 git 历史；泄露后立即在开发者后台轮换。

### 1.2 权限矩阵（2026-09-03 用新应用凭证实测，含关键发现）

**关键发现：物料系统存在两个 Base**——测试版（`LmuBb3WREah3BzsZW8CcfHqAnI3`，**实施计划文档引用的就是它**，28 张同名表但 table_id 不同，含 3273 条入库数据快照）与工作版（`BG4EbL901aYnUrs0I2CcG4YwnV7`，生产运行库，20 个自动化流程所在）。新应用能写的 3+1 个 Base 恰好全部是「测试版」。

| Base | 读表结构 | 读记录 | 写记录 | 说明 |
|---|---|---|---|---|
| **物料系统-测试版** `LmuBb3...` | ✅ 28 表 | ✅ | ✅（2026-09-03 管理权限已生效，文本+单选字符串写实测通过） | **V1.0 数据面**（计划文档引用） |
| 物料系统-工作版 `BG4Eb...` | ✅ | ✅ | ❌ 91403 | 生产库，V1.0 不写入（天然安全边界）；20 个 workflow 在此（新应用不可见） |
| GMP 质量物料-测试版 `RJGcbT...` | ✅ | ✅ | ✅（单据类型字符串写实测通过） | V1.0 数据面 |
| 成品销售汇总-测试版 `MtxPbT...` | ✅ | ✅ | ✅（品名字符串写实测通过） | V1.0 数据面 |
| 成品产销存-测试版 `L2O2bN...` | ✅ 42 表 | ✅ | ✅（写+删实测通过） | V1.0 数据面 |

**注意**：测试版克隆**未带自动化流程**（workflow 数量为 0）——试点期写入不会触发任何推送（对生产零干扰），但也无消息联动；生产切换时（写 BG4Eb 工作版）既有 20 个 workflow 会被触发（见 V1.0-2 决策③）。

### 1.3 待办与前置条件

1. ~~物料系统加可编辑协作者~~ **已完成**（测试版，管理权限，2026-09-03 实测生效）；
2. ~~与业务方确认 V1.0 数据面~~ **已确认（2026-09-03）**：多维表格**全部使用测试版**——V1.0 读写面 = 4 个测试版 Base，工作版完全不动（只读参照）。测试版与工作版数据会逐渐分叉属预期行为，生产切换（V1.1）前再定同步策略；
3. **数据治理：物料名称字段重复选项**——测试版「物料入库总账.物料名称」391 个选项中 `N,N-二甲基甲酰胺` 重复 ×2，导致该字段按名写入必然失败（1254062，实测所有值均失败）；需在 Base 内合并重复选项（一次性人工操作）；
4. 开发者后台 scope 核对：`bitable:app`、`im:message`、`im:message.group_at_msg`、`im:resource`、`interactive_card`；
5. 机器人发布范围：确认对仓储部全员可见可用。

## V1.0-2. Agent 总体架构（Harness 型 Agent）

**定位**：不是「带工具的聊天机器人」，而是 **harness 型 Agent**——把编码 Agent（如 ZCode）验证过的能力增强架构移植到仓储场景：模型本身不变，靠 harness 层（计划、技能、记忆、委派、验证）把业务任务与办公任务执行到位。模型不需要会编码，但拥有资深仓管员的「工作脚手架」。

```text
L6 元能力层  Harness（本设计的核心增量）
              ├─ 任务计划器：多步任务分解/进度跟踪/中断恢复（对标 TodoWrite）
              ├─ 技能库：业务 SOP 封装为按需加载的技能（对标 Skills）
              ├─ 长期记忆：用户偏好/业务惯例/术语别名，跨会话（对标 Memory）
              ├─ 子 Agent 委派：重上下文任务隔离执行（对标 SubAgent）
              └─ 后台任务：长任务异步执行+完成通知
L5 交互层    手机飞书（私聊 / 群 @ / 卡片按钮）
L4 网关层    gateway：去重·限流·会话定位·占位卡片·规则化预路由
L3 编排层    Orchestrator（双模执行）
              ├─ Runner：harness 化 tool-calling 循环 ← 查询/问答/多步业务任务
              └─ Pipeline：确定性状态机 ← 识别录入（识别→对齐→草稿→[确认]→写入）
L2 工具层    三域工具（@mcp.tool 统一注册）
              ├─ 业务域：query×4 / recognize / draft×2 / submit×3（V1.0-5 契约）
              ├─ 办公域：send_card（发卡片给人/群）/ create_reminder
              └─ harness域：plan / update_plan / load_skill / recall / save_memory / delegate
L1 数据层    4 测试版 Base（格式契约封装）+ Postgres（draft/session/audit/plan/memory）
```

### 三个关键设计决策

**① 双客户端隔离**：warehouse 使用独立飞书客户端（新应用凭证），不复用主应用/SAFETY/HR 的 client。理由：事件订阅、消息发送、机器人身份都要按应用隔离，且互不影响现有模块机器人。实现上在 `app/platform/integrations/feishu/` 增加按凭证构造多 client 的工厂（现有 `FeishuClient` 已按 settings 构造，增加显式传入凭证的能力即可），事件层为 warehouse 单独起一个 WS 长连接实例（参照 HR 职称评审独立 WS 的模式）。

**② MCP 双用途**：工具层用 `get_module_mcp("warehouse")` 注册（`app/platform/mcp/server.py` 现成框架 + 认证/DB会话/日志中间件，equipment 模块是完整范例）。同一套工具：
- 内部 Agent 直接函数调用（HTTP 请求路径内）；
- 挂载为标准 MCP 端点 `/mcp/warehouse`（`main.py` 中 `get_mcp_app(...)` 一行挂载），**供外部 Agent（飞书妙搭/豆包等）通过 `MCP_AGENT_API_KEYS` 接入**——这正是此前与业务方对齐的「送货单识别 + MCP 查询」试点形态。

**③ AI 植入不破坏现状（分两阶段生效）**：Agent 写入的目标 Base 上既有的自动化流程照常触发，dazah 不碰这些流程——AI 只是把「人工打开表格手填 20 个字段」变成「拍照→确认→自动填」。分阶段含义：
- **试点阶段（V1.0）**：写入 4 个测试版 Base——克隆**不带 workflow**，写入不触发任何推送，对生产零干扰（天然沙箱）；
- **生产阶段（V1.1）**：数据面切到工作版（物料系统 BG4Eb 等），此时既有 20 个 workflow 会被 Agent 写入正常触发（到货推送、请检推送、QC/QA 路由等），消息链路维持飞书 workflow 现状。

### Agent 执行内核：双模编排 + 草稿状态机

**架构立场**：LLM 不是执行器，是「理解与决策」组件。凡是能用确定性代码表达的（状态迁移、字段校验、写入、路由）一律代码化；LLM 只负责语言理解、单据识别、字段对齐与工具选择。收益：行为可预测（GMP 环境）、成本可控（确认动作零 token）、故障面小（状态机不会幻觉）。这是 2025 年以来 Agent 工程的共识路线——**workflow 与 agent 混合编排**，而非纯自由循环。

**双模执行**：

| 模式 | 适用 | 执行方式 |
|---|---|---|
| **Runner**（循环） | 查询、问答、草稿字段修改 | LLM tool-calling 循环（≤ MAX_TURNS=6） |
| **Pipeline**（状态机） | 送货单识别入库、出库登记 | 确定性阶段推进，LLM 仅在「识别」「对齐」两个阶段被调用 |

网关预路由（规则化，零 LLM 成本）：图片消息→Pipeline；卡片回调→确定性直调 submit/update/cancel（不过 LLM）；文本→Runner（若当前会话存在 pending 草稿，草稿摘要注入上下文，模型自然处理「把数量改成 200」这类指令）。

**Draft 状态机（跨消息存活的 HITL 流程实例）**：

```text
created(识别完成) → aligned(主数据对齐完成) → pending_confirm(确认卡片已发)
  pending_confirm ──点[确认]──▶ confirmed ──▶ submitted(写 Base + 回执卡片)
  pending_confirm ──发文本修改──▶ updating ──▶ pending_confirm（卡片 patch 更新）
  任意状态 ──TTL 10min──▶ expired；──点[取消]──▶ cancelled
```

- 状态迁移全部代码化，每次迁移事件入 audit 表（谁、何时、从哪个状态到哪个状态）；
- **幂等**：draft_no 唯一约束 + 状态前置校验——用户重复点确认、飞书回调重放，都不会产生重复写入。

**上下文工程（Context Engineering）**：

| 层 | 内容 | 策略 |
|---|---|---|
| 系统提示词 | 角色 + 规则 + 字段字典 | 静态 ~3KB（字典来自 bitable_schema 常量） |
| 会话历史 | 最近 12 轮 | 超出裁剪，保留摘要头（「本会话正在处理草稿 #123」） |
| 工具结果 | 查询类返回 | **工具内部分页**：默认前 10 条 + 总数，用户追问再翻页——防止大结果集撑爆上下文 |
| 识别明细 | 全字段 + 置信度 | 不进 LLM 上下文，存 draft 表、卡片渲染；LLM 只见摘要 |

**错误处理与自修复**：

- 工具校验失败（如单选值不在选项集内）→ 结构化错误返回 Runner，模型自修复重试 ≤2 次，仍失败转人工话术；
- Base API 瞬时错误/限流 → 指数退避重试 ≤3 次；
- LLM 超时 → 占位卡片更新为降级话术 + audit 记录错误码；
- **识别低置信度字段（confidence < 0.7）→ 卡片高亮 ⚠，禁止 LLM 自动填，必须人工确认或修改**——质量红线，模型无权降低。

**评估闭环（上线门禁）**：

- 用摸底数据构建识别测试集：从「物料入库总账」3273 条真实记录抽取字段真值 + 附件照片，跑 recognize→对齐→字段级命中率报告；
- 验收线：字段级 ≥ 90%、主数据对齐 ≥ 95%（V1.0-7）；
- 提示词/模型每次变更重跑测试集回归，防「调好一个场景坏另一个」；
- 上线后每周从 audit 表聚合实际命中率，与测试集基线对比漂移。

### Harness 元能力层设计（对 ZCode 型 Agent 的移植）

#### 能力映射总表

| ZCode（编码 Agent）能力 | 仓储 Agent 对应物 | 解决的业务问题 |
|---|---|---|
| TodoWrite 任务计划 | **任务计划器**（plan / update_plan 工具 + 进度卡片） | 「盘本月呆料并通知各班组长」这类多步任务不丢步骤、进度可见、中断可续 |
| Skills 技能系统 | **技能库**（业务 SOP 文件，按需加载） | 资深仓管员经验固化：呆料分析、月度平衡、催办等操作有标准流程与标准输出 |
| Memory 跨会话记忆 | **长期记忆**（偏好/惯例/别名） | 用户不用每次解释「雷帕」是什么、报表按谁的口味分组 |
| SubAgent 子代理委派 | **子 Agent 委派**（delegate 工具） | 47 条呆料逐条分析这类重上下文任务，主会话不爆、可并行 |
| 后台任务 | **后台执行 + 完成通知** | 长任务（批量催办、周报生成）不阻塞对话 |
| 测试/验证闭环 | **写入读回核对 + 报表交叉验证** | 写入 Base 后读回比对；报表数字与明细合计核对 |
| 权限护栏 | 三重写入护栏（已有）+ 草稿确认 | GMP 合规 |

#### 1. 任务计划器（Plan）

```python
# harness 域工具
plan_task(title, steps: list[str]) -> plan_id     # ≥3 步的任务先出计划
update_plan(plan_id, step_no, status, note?)       # 单步完成/跳过/失败
```

- Runner 系统提示词规则：预估 ≥3 步的任务**必须先 plan_task**，并把计划概要回复用户；
- 进度通过**进度卡片**呈现（飞书卡片 patch 实时更新：✅ 步骤1 查呆料汇总 → ⏳ 步骤2 按班组长分组）；
- 计划持久化（`warehouse_agent_plans` 表），用户离开再回来说「继续」，从 plan 状态恢复执行上下文；
- 计划是模型的工作备忘，不是合同——用户可随时插入新指令，模型重新规划。

#### 2. 技能库（Skills）——把 SOP 编码进 harness

技能 = markdown 文件（`agent/skills/*.md`），三段结构：**触发描述**（何时用）+ **操作步骤**（调哪些工具、什么顺序、参数要点）+ **输出格式**（卡片模板）。系统提示词只注入技能目录（一行一条：名称+触发描述），Agent 判断任务匹配后 `load_skill(name)` 拉取完整 SOP——按需加载，上下文经济。

首批 5 个技能（全部来自业务摸底的真实 SOP）：

| 技能 | SOP 要点（封装的资深仓管员经验） |
|---|---|
| `dead-stock-analysis` 呆料分析 | 查呆料汇总表 → 按物料大类分组 → 每组关联班组长 → 生成分组报告卡片 → **经确认后** send_card 逐个通知班组长（对应 Base 呆料新增流程的 AI 版） |
| `monthly-balance` 易制毒月度平衡 | 读入库/出库台账 → 按备案证号归集 → 上月转存+本月入出=本月结余 → 生成平衡表卡片（对应月度平衡表 SOP） |
| `expiring-check` 复验期预警 | 查库存（复验期 < N 天）→ 按物料大类排序 → 高危标注 → 输出预警清单 |
| `weekly-stock-report` 周库存三态 | 按放行/待检/否决三态聚合 → 对比上周 → 周报卡片 |
| `overdue-chase` 超期催办 | 查未出报/未处理事项 → 按责任人群发催办卡片（对应每月 28 日催办流程的对话版） |

技能文件与提示词同权重纳入回归测试集（V1.0-2 评估闭环）。

#### 3. 长期记忆（Memory）

```python
recall_memory(keyword?) -> list[条目]        # 按当前用户+关键词查记忆
save_memory(type, content)                    # preference偏好 / convention惯例 / alias别名
```

- 存储：`warehouse_agent_memories` 表，双维度——**用户维度**（「郑旭偏好只看危化品」「他说的雷帕=雷帕霉素」）与**全局维度**（业务惯例：「呆料清单按原辅料/危化品/包材分组」「催办对象按物料大类路由班组长」）；
- 注入：会话开始时注入该用户偏好摘要（top 3 条）+ 全局惯例（top 5 条）；其余按需 recall；
- 写入规则：用户显式纠正（「以后报表别带包材」）或 Agent 发现高价值惯例时主动保存并在回复中告知；
- **记忆只影响表达与默认参数，不改变数据**——记忆错误最坏影响格式，不影响正确性（质量红线不依赖记忆）。

#### 4. 子 Agent 委派（Delegate）

```python
delegate(description: str, context: str) -> 摘要    # 启动子 Runner，独立上下文
```

- 场景：逐条分析 47 条呆料（每条要查库存+趋势+生成结论）——主上下文放不下，且与用户交互无耦合；
- 实现：子任务 = 干净上下文的 Runner 实例 + 委派描述 + 必要上下文片段；V1.0 串行执行，V1.1 可 `asyncio.gather` 并行（同一 Base 串行写、只读查询可并行的契约不变）；
- 子 Agent **没有 submit 权限**（只读+草稿）——委派只做分析归纳，写入动作永远留在主会话（可归因到用户的确认链）。

#### 5. 后台任务

- 预估 >30s 的任务（批量催办、全量周报）→ 转后台执行（asyncio task），立即回复「已转后台，完成后通知你」；
- 完成后主动发卡片（含结果摘要 + 「查看完整报表」链接）；
- 会话与后台任务解耦：用户可继续对话，任务进度可查（「刚才那个周报好了吗」）。

#### 6. 办公域工具（「办公任务执行到位」的直接支撑）

```python
send_card(target: user|group, card)     # 发消息卡片给指定人/群（催办、报告分发）
create_reminder(time, content, target)  # 定时提醒（复用平台 scheduler 动态任务）
```

- 发送前若内容含业务结论，先经用户确认（与写 Base 同级的 HITL 门）——**对外发出的每张卡片都代表仓储部**，不能由模型自主决定；
- 目标解析：人名→open_id（复用 `feishu/contact.py`）、群名→chat_id；记忆中的「班组长路由表」作为默认映射。

#### 7. 验证闭环（对 ZCode「跑测试」的移植）

| 动作 | 验证 |
|---|---|
| submit 写入 Base | 写入后**读回记录**，比对关键字段（数量/批号/物料），不一致立即告警并标记 audit |
| 报表/汇总生成 | 合计与明细逐项核对（Σ明细 = 合计），不一致在卡片自标注 ⚠ |
| 识别对齐 | 低置信度字段强制人工确认（已有红线） |

### Agent 层配置规范（模型 / 运行时 / 工具 / 提示词 / 路由）

#### A. 模型配置（单模型位，2026-09-03 已配置并通过五重验证）

一个**带视觉能力的对话模型**同时承担识别与决策。配置键（已写入 `.env.development`，密钥不入文档/不入库）：

| 配置键 | 已配置值 |
|---|---|
| `WAREHOUSE_AGENT_BASE_URL` | `https://api.deepseek.com`（与 meter 同网关） |
| `WAREHOUSE_AGENT_API_KEY` | 已配置（用户提供，2026-09-03 验证有效） |
| `WAREHOUSE_AGENT_MODEL` | `deepseek-v4-flash-vision-exp`（上下文 1M） |

**2026-09-03 连通性验证结论（五重）**：① 新 Secret 换 token 成功；② Secret 轮换后 Base 读取权限无损；③ 基础对话正常；④ **function calling 原生支持**（模型对"查硫酸库存"正确发起 `query_stock({"keyword":"硫酸"})`）——S0 的关键前提已排除风险；⑤ 视觉输入（base64 data URI）格式接受。

**该模型的开发契约要点（实测）**：
- 是 **reasoning 模型**：响应含 `reasoning_content`（思考过程）与 `content`（最终答案）两个字段——`AIService` 解析时取 `content`；`max_tokens` 必须给足（小额度会被 reasoning 耗尽导致 content 为空，实测 max_tokens=8 时 content 空、=200 正常）；`usage.completion_tokens` 含 reasoning 消耗（成本核算按此口径）；
- `chat()` 扩展 tool calling 时注意：发起工具调用轮的 `content` 可能为空、决策在 `tool_calls` 里——Runner 判断「最终回复」的依据是**无 tool_calls 且 content 非空**；
- 图片输入路径：飞书 IM 下载（im:resource）→ base64 data URI → `chat_vision`；
- 单模型下的调优隔离：识别 prompt 与对话 prompt 独立维护（`SCENE_PROMPTS` 按场景注入），互不干扰；改识别 prompt 不影响对话行为，回归测试集覆盖。

#### B. Runner 运行时配置

```python
# config.py 新增（默认值即推荐值，均可 env 覆盖）
WAREHOUSE_AGENT_ENABLED: bool = True          # 总开关（灰度/应急停用）
WAREHOUSE_AGENT_MAX_TURNS: int = 6            # 单次对话最大工具调用轮数（防死循环）
WAREHOUSE_AGENT_TIMEOUT: int = 90             # 单次消息处理超时（秒），超时回复降级话术
WAREHOUSE_AGENT_TEMPERATURE: float = 0.1
WAREHOUSE_AGENT_MAX_TOKENS: int = 8192
WAREHOUSE_AGENT_SESSION_ROUNDS: int = 12      # 会话历史保留轮数（超出裁剪最旧）
WAREHOUSE_DRAFT_TTL_MINUTES: int = 10         # 识别草稿过期时间
WAREHOUSE_AGENT_ALLOWED_CHATS: str = ""       # 可选群白名单（空=私聊全放行+所有群@放行）
```

**Runner 核心循环**（`agent/runner.py`，全仓库首个 Agent 循环，作为后续模块模板）：

```python
async def run(self, session: AgentSession, user_msg: str | ImageMsg) -> AgentReply:
    for turn in range(settings.WAREHOUSE_AGENT_MAX_TURNS):
        resp = await brain.chat(messages=session.history, tools=TOOL_SCHEMAS)
        if not resp.tool_calls:                       # 无工具调用 → 最终回复
            return AgentReply(text=resp.content)
        for call in resp.tool_calls:                  # 并发执行工具调用
            result = await self._execute_tool(call, session)   # 见 D 护栏
            session.append_tool_result(call.id, result)        # 结果截断至 4KB/条
    return AgentReply(text="任务过于复杂，已生成部分结果，请缩小问题范围")  # 轮数兜底
```

#### C. 工具层配置（@mcp.tool 注册，装备模块模式）

工具 schema = **docstring（给 LLM 的功能描述）+ 类型注解（FastMCP 自动生成 JSON Schema）**。9 个工具分三档权限：

| 工具 | 档位 | 说明（即 docstring 要点） |
|---|---|---|
| `query_stock(keyword, qc_status?, expiring_days?)` | 只读 | 查库存：批号/数量/库位/三态/复验期 |
| `query_material(keyword)` | 只读 | 查物料主数据：编码/大类/换算/免检/出报天数 |
| `query_movements(material?, direction?, date_from?, date_to?)` | 只读 | 查出入库流水与汇总 |
| `query_report(report_type, period?)` | 只读 | 呆料清单/不合格清单/周库存三态 |
| `recognize_document(image_token, doc_type)` | 只读* | 图片→结构化字段（内部调视觉模型）；*只产草稿不落库 |
| `create_draft(scene, fields, image_token?)` | 草稿 | 生成待确认草稿，返回 draft_no |
| `update_draft(draft_no, fields)` | 草稿 | 草稿字段修改（对话中"把数量改成200"） |
| `submit_receipt(draft_no)` / `submit_outbound(draft_no)` / `submit_gmp(draft_no)` | **写入** | 草稿确认后写 Base（见 D 护栏） |
| `plan_task(title, steps)` / `update_plan(plan_id, step_no, status)` | harness | 任务计划与进度（≥3 步任务强制） |
| `load_skill(name)` | harness | 按需加载业务 SOP（系统提示词仅含目录） |
| `recall_memory(keyword?)` / `save_memory(type, content)` | harness | 长期记忆读写（用户偏好/业务惯例/别名） |
| `delegate(description, context)` | harness | 子 Agent 委派（只读+草稿权限，无 submit） |
| `send_card(target, card)` | 办公·**HITL** | 发卡片给人/群——含业务结论时先经用户确认 |
| `create_reminder(time, content, target)` | 办公·**HITL** | 定时提醒（复用平台 scheduler） |

> 卡片按钮「确认入库」走 `gateway` 直接调 `submit_*`（携带 draft_no），**不经过 LLM**——确认动作是确定性路由，不让模型参与，省 token 且消除误操作风险。

#### D. 写入护栏配置（三重校验，代码强制而非提示词约束）

```python
async def _execute_tool(call, session):
    if call.name.startswith("submit_"):
        draft = await repo.get_confirmed_draft(draft_no=call.args["draft_no"])   # ① 草稿状态=confirmed
        if draft.created_by != session.user_open_id: raise ToolDenied            # ② 仅发起人可提交
        if draft.expired: raise ToolExpired                                      # ③ TTL 内
    return await tool_fn(**call.args, ctx=mcp_ctx)   # ctx 由 MCP middleware 注入 DB session
```

#### E. 提示词配置（三段式，`agent/prompts.py`）

```python
SYSTEM_PROMPT = f"""你是丽珠福兴仓储部的仓库管理助手，通过飞书与仓管员对话。
规则：
1. 查询类问题直接调工具回答，数字必须来自工具结果，禁止编造；
2. 录入类需求先调 recognize/create_draft 生成草稿，引导用户点击卡片按钮确认，你不得代替用户确认；
3. 字段值必须用业务术语（物料名称/批号/供应商），来自工具返回的合法选项；
4. 不确定时追问，不要猜。
{FIELD_DICT_PROMPT}   # 注入核心表字段字典与单选选项集（来自 bitable_schema.py 常量，约 2KB）
"""
```

- 场景提示词（`SCENE_PROMPTS`）按 scene 追加：识别入库（字段映射说明+低置信度标记规则）、出库登记等；
- 支持配置覆盖：`WAREHOUSE_AGENT_SYSTEM_PROMPT`（对齐 `HR_AI_SYSTEM_PROMPT` 先例），调优不重新发版；
- 字段字典**静态快照**存 `bitable_schema.py`（构建时从 `base_scan/` 摸底结果生成），运行时工具再校验实际选项（防 Base 侧改选项后字典过期）。

#### F. 消息路由配置（`agent/gateway.py`）

| 入口 | 触发条件 | 管线 |
|---|---|---|
| 私聊机器人 | 全部消息（文本/图片） | 文本→Runner；图片→识别管线 |
| 群内 @机器人 | @ 提及消息（`im:message.group_at_msg` scope） | 同上；写入确认仅草稿发起人按钮生效 |
| 卡片回调 | 「确认入库/修改/取消」按钮 | 确定性路由直调 submit/update（不过 LLM） |
| 兜底 | 非目标会话/超时/异常 | 友好降级话术 + 错误码入审计表 |

**异步体验配置**：Agent 处理含多轮工具调用（5-30 秒），收到消息先回「⏳ 正在处理…」占位卡片，完成后**更新原卡片**（飞书卡片 patch 接口），避免刷屏。

#### G. 可观测性

- `warehouse_agent_audit`：每次工具调用记录 tool_name/args 摘要/结果状态/耗时/draft_id（第 V1.0-4 章的表）；
- 外部 Agent 经 `/mcp/warehouse` 接入时，MCP 平台 logging middleware（per-tool-call 日志）自动生效；
- 每周聚合：识别命中率、草稿确认率、工具错误率——V1.0 验收指标的数据来源。

## V1.0-3. 机器人交互管线（核心场景走查）

### 场景 A：送货单拍照识别入库（旗舰场景，对齐一期试点）

```text
1. 仓管员在手机飞书私聊机器人，拍送货单发图
2. Agent：im:resource 下载图片 → recognize_document 工具
   （视觉 LLM 严格 JSON：物料名/厂家批号/数量/单位/供应商/车牌/合同号…，
    复用 meter 的 3 次指数退避重试模式）
3. 字段对齐：识别结果与「物料名称代码一览表」(602条主数据) 模糊匹配
   ├─ 唯一命中 → 带出物料编码/大类/细分类/贮存点等字段
   └─ 未命中/多候选 → 留空并标记"待人工选择"
4. 生成识别草稿（draft，落 Postgres）→ 回复交互卡片：
   字段逐项展示（低置信度高亮 ⚠）、附原图缩略图
   按钮：[确认入库] [修改] [取消]
5. 用户点[确认入库]（卡片回调）→ Agent 校验字段 → submit_receipt 写入
   「物料入库总账」→ Base workflow 自动触发请检推送/到货群通知
6. 回执卡片：入库单摘要 + Base 记录直达链接
```

### 场景 B：自然语言查询（高频，纯只读）

- 「硫酸还有多少放行的？」→ `query_stock`（库存明细总表，QA放行=放行 筛选）→ 卡片回复：批号/数量/库位/入库日期 列表
- 「上个月乙醇入了多少？」→ `query_movements`（入库总账按月聚合）
- 「哪些物料快到复验期了？」→ `query_stock`（有效期至/复验期至 < N 天）

### 场景 C：GMP 出库登记（写测试版 Base）

质量部对话式登记出库（含生产批号）→ 草稿确认 → `submit_gmp` 写「GMP 物料出库总账」。

### 场景 D：成品出库 + 快递单识别

拍照出库单/快递面单 → 识别（品名/批号/数量/客户/快递号）→ 确认 → 写「成品出库台账」（快递号字段已有）；快递单号识别后可推送产销负责人。

### 场景 E：周期汇总问答

「本周成品数据汇总」→ `query_report` 聚合成品产销存（每周成品数据汇总表 / 每日发货明细）→ 卡片报表。V1.0 的推送类需求（周报）优先用飞书 Base 既有 workflow，Agent 提供对话式按需查询。

### 交互设计约束（全部场景）

- 所有写操作走**草稿→卡片确认→提交**两段式，Agent 永不直接写 Base；
- 卡片是手机第一公民：字段名用业务语言（物料/批号/数量），不用技术字段名；
- 识别原图与识别 JSON 全量留档（审计 + 模型改进语料）；
- 会话超时（如 10 分钟）未确认的草稿自动过期；
- 群内 @机器人 与私聊行为一致，但写操作确认只允许草稿发起人点击。

## V1.0-4. Postgres 辅助表（仅 Agent 状态，不存业务数据）

业务数据仍在 Base；dazah 只建 5 张轻量表支撑 Agent 运行（harness 升级后新增 plans / memories）：

```python
# schema: warehouse
warehouse_agent_drafts       # 识别草稿：draft_no, scene(receipt/gmp_outbound/finished_outbound),
                             # source_image(file token), recognized(JSONB 原始识别),
                             # aligned(JSONB 对齐后字段+置信度), status(pending/confirmed/expired/cancelled),
                             # target_base/table/record_id(回写后回填), created_by(feishu open_id), expires_at
warehouse_agent_sessions     # 会话上下文：chat_id, user_open_id, 最近消息与轮次摘要（LLM 上下文裁剪用）
warehouse_agent_audit        # 工具调用审计：tool_name, args 摘要, 结果状态, 耗时, draft_id/plan_id 关联
warehouse_agent_plans        # 任务计划：plan_id, session_id, title, steps(JSONB:[{no,desc,status,note}]),
                             # status(active/done/abandoned), created_by —— 中断恢复的持久化载体
warehouse_agent_memories     # 长期记忆：scope(user/global), owner_open_id, type(preference/convention/alias),
                             # content, hit_count(注入命中计数，用于淘汰), created_at
```

> V2 迁移时这五张表自然保留（Agent 状态层与数据层分离，迁移互不影响）。

## V1.0-5. Base 读写契约（工具层实现规范）

**读**：`platform/integrations/feishu/bitable.py` 已有 `list_all_records/list_tables/list_fields`，按需增加带 `filter`/`sort` 的查询封装与字段类型解码器（select 数组、lookup、formula、user 对象）。

**写**规范（全部来自实测，写入契约必须内置）：

| 规则 | 依据（实测证据） |
|---|---|
| **单选字段（type 3）写入必须传纯字符串** `"选项名"`，不能传数组 `["选项名"]`——尽管**读取时返回的是数组**（读写不对称！） | 数组写→1254062 SingleSelectFieldConvFail；字符串写→code 0（物料大类/单位/品名/单据类型跨 3 个 Base 验证） |
| **存在重复选项名的字段，按名写入必然失败**（如「物料入库总账.物料名称」391 选项中 `N,N-二甲基甲酰胺` 重复 ×2，该字段所有值写入均 1254062） | 重复选项导致名称解析歧义；需数据治理合并重复项（见 1.3） |
| 字段键只能用**字段名**，field_id 不被接受 | field_id 作键→1254045 FieldNameNotFound |
| 字段名必须精确匹配（含全角括号/点号/空格） | FieldNameNotFound（1254045） |
| lookup / formula / created_by / auto_number 只读，写入会被忽略或报错 | Base 字段类型规则 |
| 附件先上传拿 file_token 再写 attachment 列 | 图片入库链路 |
| 写前先 `list_fields` 拉目标表 schema 做校验（选项集内校验单选值） | 防字段改名/选项变更导致静默失败 |
| 写并发控制：同表串行写、批量≤200 条/批 | Base API 限制（1254291 并发冲突） |
| 权限校验（91403）先于字段校验（125xxxx）发生 | BG4Eb 无权限时传非法选项值仍返回 91403 而非字段错误 |

**核心表写入映射**（Agent 输出字段 → Base 字段）：

| Agent 字段 | Base「物料入库总账」字段 | 类型/格式 |
|---|---|---|
| material_name | 物料名称 | 单选（**字符串**，须为既有选项；⚠️ 该字段当前有重复选项待治理，治理前写入会失败） |
| batch_no | 物料批号 | 文本 |
| vendor_batch_no | 厂家批号 | 文本 |
| quantity / unit | 入库数量 / 单位 | 数字 / 单选（字符串） |
| supplier / manufacturer | 供应商 / 生产商 | 单选（字符串） |
| arrived_type | 到货情况 | 单选（字符串：到货物料/A类物料） |
| plate_no / contract_no | 车牌 / 合同编号或订单号 | 文本 |
| storage_point | 贮存/槽车取样点 | 单选（字符串） |
| photos | 外包装/厂家报告单/送货单照片 | 附件（file_token） |
| inspection_type | 是否加急检测 等 | 单选（字符串） |

（GMP/成品出库映射同理，开发时按 `base_scan/` 摸底字段建完整映射表，作为工具层的静态 schema 常量。）

## V1.0-6. 模块结构（V1.0 增量）

```text
app/modules/warehouse/
├── api.py                      # 现有 MVP 路由（保持不动）
├── agent/
│   ├── gateway.py              # 机器人消息路由：文本/图片/卡片回调 → Agent
│   ├── runner.py               # Agent 执行循环（LLM tool calling）
│   ├── prompts.py              # 系统提示词（角色/业务规则/字段字典）
│   └── cards.py                # 交互卡片构建（草稿确认/查询结果/回执）
├── mcp_tools/
│   ├── __init__.py
│   ├── query.py                # query_stock / query_material / query_movements / query_report
│   ├── submit.py               # submit_receipt / submit_outbound / submit_gmp（草稿确认后解锁）
│   └── recognize.py            # recognize_document（图片→JSON）
├── bitable_schema.py           # 4 Base 核心表字段映射常量 + 写入契约校验
├── models.py                   # +3 张 Agent 辅助表（现有 MVP 表保持不动）
├── scheduler.py                # （预留）草稿过期清理等轻量任务
└── feishu/                     # 独立 WS 客户端装配（新应用凭证）
```

`app/main.py` 增加一行挂载：`warehouse_mcp_asgi = get_mcp_app(get_module_mcp("warehouse"), path="/", middleware=mcp_middleware)`。

## V1.0-7. 范围与验收

**V1.0 交付（按优先级）**：
1. 飞书应用接入（独立 WS + 消息路由 + 群/私聊）；
2. 场景 A 送货单识别入库（物料系统，依赖写权限开通）；
3. 场景 B 自然语言查询（库存/物料/流水/复验期）；
4. 场景 C/D GMP 出库与成品出库识别登记（测试版 Base，已可写）；
5. MCP 端点暴露（外部 Agent 接入试点）。

**验收标准**：
- 仓管员全程只用手机飞书完成「拍照→确认→入库」，单据录入耗时 < 1 分钟（对比手工填表 3-5 分钟）；
- 识别准确率：字段级 ≥ 90%，主数据对齐命中率 ≥ 95%（人工确认率兜底 100%）；
- 写入测试版 Base 的记录 100% 符合字段契约（单选字符串格式、选项值合法、无静默失败）；
- 生产切换后（V1.1，写工作版）：Agent 写入的记录 100% 正常触发既有 workflow 推送；
- 只读查询响应 < 5 秒；
- 所有写入有审计记录（audit 表）+ 原图留档。

**明确不做（V1.0 边界）**：数据迁移、自建库存表、审批流改造、报表系统重建、既有 20 个 workflow 的任何改动。

---

## V1.0-8. 分阶段实施计划（2026-09-03 设计确认后排期）

**排序原则**：
1. **依赖驱动**：外部依赖（AI KEY / IM scope / 重复选项治理）越多的阶段越后置，依赖项从 S0 起并行催办；
2. **链路先行 + 同期建元能力**：S1 用查询场景把「飞书消息 → Runner → 工具 → Base」整条链打通（不需要任何写权限），Harness 元能力（计划/技能/记忆/办公工具）与查询链路同期建设——它们同为只读+对话性质，不依赖 S2 的写路径与 Draft 状态机；S2 的识别入库在这条链上做增量；
3. **每阶段独立可验收**：阶段结束即有可演示物，业务方可提前试用建立信任。

```text
S0 地基 ──▶ S1 消息链路 + 查询 + Harness 元能力 ──▶ S2 识别入库旗舰 ──▶ S3 多场景写入+MCP
```
（2026-09-03 调整：原 S4 并入 S1——Harness 元能力与查询链路同为只读+对话性质，一次交付完整的 Agent 体验）

| 阶段 | 交付物 | 关键 ticket | 外部依赖 | 阶段验收 |
|---|---|---|---|---|
| **S0 地基** | 可跑的 Agent 基础设施 | ① AIService 扩展 tool calling（chat 加 tools 参数 + tool_calls 解析）② 配置键落地（WAREHOUSE_AGENT_* 三键 + 运行时参数，env 留空位等 KEY）③ 5 张辅助表 Alembic 迁移 ④ bitable 适配器增强：写契约封装（单选字符串/字段名/选项集缓存/错误分类）+ 带过滤查询 | AI KEY（仅 T0.② 留空位，S1 才需要） | 单测：mock tool-calling 循环通过；适配器对测试版 Base 的读写契约测试通过 |
| **S1 消息链路+查询+Harness** | 完整 Agent 体验（对话+查询+办公任务） | ① 独立 WS 客户端装配 + 事件注册 ② gateway：去重/会话定位/占位卡片 ③ Runner v1（MAX_TURNS/TIMEOUT/上下文裁剪）+ 4 个 query 工具 ④ 查询结果卡片渲染 ⑤ 任务计划器（plan_task/update_plan + 进度卡片 + plans 表）⑥ 技能库框架 + 首批 2 技能（dead-stock-analysis / expiring-check）⑦ 长期记忆（recall/save + 会话注入）⑧ 办公工具（send_card HITL 确认门 / create_reminder）——⑤-⑧ 在 ①-④ 链路上依次叠加，每个独立可验收 | IM 收消息 scope 核对 | 手机飞书问「硫酸还有多少放行的」→ <5s 卡片回复；私聊+群@ 均可用；**「盘本月呆料并催办各班组长」对话式全流程完成**（计划卡片→分组报告→经确认后逐个发送）；audit 表有记录 |
| **S2 识别入库旗舰** | 场景 A 全流程（价值最高） | ① recognize pipeline（图片下载→chat_vision→严格 JSON→重试）② 字段对齐器（602 条主数据模糊匹配+置信度）③ Draft 状态机（TTL/幂等/状态迁移审计）④ 确认卡片+按钮回调确定性直调 ⑤ submit_receipt + 写入读回核对 | AI KEY（视觉）；im:resource scope；**物料名称重复选项治理** | 拍照→确认→入库 <1min；字段级识别 ≥90%、主数据对齐 ≥95%（测试集基线）；写入后读回 100% 一致 |
| **S3 多场景写入+MCP** | 场景 C/D + 对外试点 | ① submit_gmp（出库总账含生产批号）② submit_outbound（成品出库台账含快递号）③ 快递单识别→推送产销负责人 ④ `/mcp/warehouse` 挂载 + MCP_AGENT_API_KEYS 认证 | 无新依赖（测试版 Base 已全部可写） | GMP/成品出库对话式登记成功；外部 Agent（妙搭等）经 MCP 查询库存成功 |

**关键路径**：
- **V1.0 全程线性串行：S0 → S1 → S2 → S3**（每步是下一步的地基，S1 已含 Harness 元能力，无并行分支）；
- S1 内部顺序：①②③ 链路核心先跑通（可先演示查询），④-⑦ Harness 元能力依次叠加；
- delegate 子委派与后台任务放 V1.1（非核心闭环，避免 S1 过重）。

**外部依赖催办清单**（从现在开始并行推进，不阻塞 S0 开工）：

| 依赖项 | 状态（2026-09-03） |
|---|---|
| 带视觉模型 API KEY | ✅ 已配置并五重验证（function calling 原生支持，reasoning 模型契约见 V1.0-2.A） |
| IM scope 核对（收消息/图片/卡片回调） | ✅ 业务方已在开发者后台配置完成 |
| 物料名称重复选项合并 | ⏸ 业务方决定暂缓——S2 联调时「物料名称」字段写入做降级处理（跳过该字段+卡片提示人工补填），其余字段不受影响 |
| App Secret 轮换 | ✅ 已重置，新凭证换 token + Base 读取验证通过 |

**结论：S1 开工的全部外部依赖已就绪；S2 仅剩物料名称字段降级方案（已内置，不再阻塞）。**

**S2 验收用测试集**：S2 开工首日先从「物料入库总账」3273 条记录抽取字段真值+附件照片构建识别测试集（≈100 张抽样），此后每次 prompt/模型变更重跑回归——这是「字段级 ≥90%」验收口径的数据基础。

**推荐执行方式**：每阶段的 ticket 可用 `/feature-flow` 体系落地（S0/S1 用 `--skip-grill` 从规格起步；单 ticket 实现可委派 feature-dev 子代理，每阶段完成后用 feature-reviewer 双轴审查）。

---

# 下卷：V2 平台化路线（原设计，V1.0 验证后评估启动）

## 1. 背景与目标

丽珠福兴仓储部当前以 4 个飞书多维表格承载业务，20 个自动化流程全部为确定性规则（零 AI 使用）。按实施计划，目标是在 dazah 平台内建成覆盖「原辅料 + 成品」两大业务域的仓储管理系统，分两层能力：

1. **业务闭环层**：把飞书侧已验证的请验-出报-放行质量流程、领料审批、库存台账、专项合规、消息推送迁移为 dazah 内建能力，与数据库事务绑定；
2. **AI 增强层**：在闭环数据之上叠加拍照识别录入（OCR）、库存合理化建议、自然语言查询等增量能力。

统一约束：**所有面向一线的功能必须支持手机端操作**（飞书内 H5）。

验收口径：飞书 Base 现有的每条业务规则与消息推送，在 dazah 内有等价实现；AI 能力以「识别 → 人工确认 → 落库」的方式引入，不改变现有责任链。

---

## 2. 现状盘点

### 2.1 dazah 现有实现（MVP，commit `1e20b8c`）

**后端** `app/modules/warehouse/`（api 304 行 / service 596 行 / repository 386 行），PostgreSQL 独立 schema `warehouse`，6 张表：

| 表 | 说明 | 关键字段 |
|---|---|---|
| `warehouse_materials` | 物料主数据 | code(唯一)、name、category(raw/auxiliary/packaging/intermediate/finished)、spec、unit、safety_stock |
| `warehouse_locations` | 库位 | code(唯一)、name、location_type(normal/cold/danger) |
| `warehouse_stocks` | 现有库存 | material+batch+location 唯一、quantity |
| `warehouse_movements` | 出入库流水 | movement_no(唯一)、direction(inbound/outbound/adjust)、source_type、quantity(恒正)、occurred_at |
| `warehouse_stocktakes` / `..._items` | 盘点单 | draft→confirmed，book_quantity 账面快照 |

20 条 API 路由（overview/materials/locations/stocks/movements/stocktakes 的 CRUD + 盘点确认）。约定：软删除（`is_deleted` 部分唯一索引）、code/name 冗余列、`BaseModel` 基类。

**前端** `frontend/src/app/(dashboard)/warehouse/`：概览 / inventory / inout / stocktake 四页。

**差距**（对照 Base 业务）：无质量状态与请检流程、无领料审批与批号匹配、无消息推送、无供应商主数据、无专项台账、无报表、无 AI。

### 2.2 平台可复用底座（不重复建设）

| 能力 | 位置 | 现状与先例 |
|---|---|---|
| 定时任务 | `app/platform/scheduler/` | TaskDefinition + cron 表达式（croniter）；energy 模块已注册 4 个定时推送任务（每日采集、车间告警、日报推送、氮气推送） |
| 飞书消息 | `app/platform/integrations/feishu/message.py` | `send_group_card` 群卡片、工单卡片、超时通知——推送引擎直接复用 |
| 飞书审批 | `.../feishu/approval.py` | 审批实例查询 API；hr 职称评审已用「轮询实例状态」模式集成（`approval_client.py`） |
| 飞书事件 | `.../feishu/event_handler.py` + `ws_client.py` | 长连接事件订阅（IM 消息、卡片回调已接） |
| AI 客户端 | `app/platform/integrations/ai/` | client + document_parser + prompts；meter 模块已验证「多模态视觉 LLM 识别 PDF/图片 → 严格 JSON → 重试退避」管线（`meter/ai_service.py`），hr 模块有 AI 出题先例 |
| ERP 集成 | `app/platform/integrations/erp/` | 空占位，三期使用 |
| 权限 | `app/platform/permission/` + 模块 `permissions.py` | warehouse 已有模块权限定义 |

### 2.3 飞书 Base 业务现状（全量摸底结论）

**物料系统（BG4EbL901aYnUrs0I2CcG4YwnV7，28 表）** 是核心，业务逻辑还原：

- **入库总账（62 字段）是质量流程主实体**：到货（到货情况：到货物料/A类物料、车牌、合同号、到货时间段）→ 请检（请检类型：普通/加急/取样复核；槽车到货单独路由；三类照片附件：外包装/厂家报告单/送货单、请验单、QC报告单）→ 取样（QC取样情况：已取样/未取样/无需取）→ 出报（QC出报：已出报合格/不合格/未出报；应出报日期=请检+N 天，N 来自物料主数据）→ 放行（QA放行：放行/条件放行/否决，QA放行人）。
- **领料审批是目标态**：「物料出库总账(备用)」（33 字段：领用审核人、审核人意见、发料人、可领量、领用人.部门、跨批号新增按钮）已建模但 0 记录未投产；现状在出库总账直接录出库，出库质量门禁（未出结果/否决/退货发料→告警仓储部群）。
- **专项合规台账**：入库表/出库表/月度平衡表三张易制毒台账（备案证号、仓管员两人签名、使用单位签名、领料员签名、上月转存/本月结余）。
- **支撑表**：物料名称代码一览（602 条主数据：ERP 编码、件数/数量/单位换算、有效期/复验期、免检、请检后出报天数、全检周期、法规危险性分类、双标）、数量预警表（预警阈值+充足/不足）、呆料汇总（46 字段，月度出库趋势+处理进度+金额）、不合格汇总（不合格项目+处理方式）、全检物料周期表、双标物料一览、原材料周库存报表（放行/待检/否决三态列）、6 张分类月度报表 + 6 张数据筛选表。
- **20 个自动化流程**（触发器分布：Timer×3、AddRecord×4、ChangeRecord×4、SetRecord×6、Button×2；停用 1 个）：请检推送（到货类型×请检类型多级路由）、QC出报推QA、QA放行/条件放行/否决分级路由（5 个群）、每日 08:30 QC 漏取+库存预警（危化品额外发危化品群）、每日 17:30 按物料大类分群播报出入库+槽车请检催办、出库质量门禁、发料减超告警、呆料/不合格新增按大类定向班组长（原辅料陈玉英/危化品冷莉/包材张亚丽/中间体王朱宝，高跃庆汇总）、每月 28 日不合格/呆料催办、入库→库存明细自动同步、药用聚乙烯袋到货定向通知。

**GMP 质量物料（RJGcbTCHQaIm3wsSEZrcDRFDnLb，3 表）**：入库总账与仓储端同构（37 字段，含 SourceID 回链）；出库总账含单据类型与**生产批号**（如 MA-ET-2026-050A）；出库每日汇总按日期列透视。零自动化。

**成品销售汇总（MtxPbT0xAaVAQHs8ixoctousnif，4 表，正式/测试版结构相同）**：销售明细（日期/品名/数量/**客户**/单位）；月度汇总为日历式（1–31 号列）+ **开票发货四口径**（本月开票合计、上月开票本月发货、本月发货未开票、本月开票未发货）+ 退货退票；年度汇总带历年同比。特殊换算：硫酸黏菌素 1kg = 22.5 十亿。零自动化。

**成品产销存（L2O2bNm3SaqzdVse6q5cCi8Anbe，42 表，2026-09-03 仓库专属应用实测可读写）**：核心台账——成品入库台账（25 字段：产品/批号/品规 15 选项/数量/单位 kg|十亿|g/件数/包装规格 15 选项/入库车间/库区位置/**质量状态：合格|待检|待处理|退货**/退货原因/退货客户/换算公斤）、成品出库台账（21 字段：销售客户/**用途 8 选项（车间分装/QC注册/外部检测或取样/销售/生产领用/客户小样/返工处理/外购样品出库）**/业务员/温度计/**快递号**/产销负责人）、每日发货明细（41 字段：1-31 号日历列+本月接收订单量/发货量/库存/入库量+上月发货本月开票）、未满批审批汇总表（**车间负责人+QA 两级审批已内建于 Base**：同意入库/拒绝入库）；24 张按产品库存表（达托霉素/万古霉素/雷帕霉素/硫酸黏菌素…）；支撑表：每周成品数据汇总、外购样品、产品ERP代码、产品及品规对应表、退货汇总表、不合格产品汇总表、古田单卡、缺货订单描述。

---

## 3. 开源调研结论与借鉴决策

**总体决策：不整体引入任何开源 WMS，采用「逻辑级参考 + 组件级复用」。** 理由：技术栈不对齐（Java/PHP 系）、场景错配（开源 WMS 面向 3PL/电商物流，无 GMP 质检放行、易制毒双人签名等制药合规）、dazah 已有 MVP 与平台底座。

| 来源 | License | 借鉴内容 | 红线 |
|---|---|---|---|
| **ERPNext**（38.8k★） | GPL-3.0 | **质量检验模型**：检验单从收货单创建；物料级「需检验」开关——**单据不提交则库存不可动**（=我们的出库质量门禁）；读数超差自动 Rejected + Manual Inspection 人工放行（=条件放行）；Incoming/Outgoing/In-Process 三类检验 | GPL 传染，**只看设计不抄代码** |
| **Odoo Community**（LGPL-3.0） | LGPL-3.0 | **双重记账**：每笔库存变化=一条不可变流水（move）+现存量（quant）分表维护，天然支持审计与月度平衡；**FIFO/FEFO 出库策略**；**reordering rules**（min/max 补货规则=安全库存）；社区版「质量控制库位+预失败量」做隔离（用库位表达质量状态的低成本方案） | 避免整段拷贝代码 |
| **InvenTree**（7.5k★） | **MIT** | **Allocation 两段式模型**：领料单行 → allocation 到具体 StockItem（material+batch）→ confirmed 扣减；状态 allocated/issued 与我们的「匹配批号→确认发料」一一对应；插件体系与 API-first 设计 | **可复制代码**（保留版权声明） |
| **PaddleOCR** | Apache-2.0 | 中文票据/单据文字+版面识别，作为 LLM 识别的增强/后备组件 | 可直接集成 |
| JeeWMS / RuoYi-WMS | 双授权/质量参差 | 仅参考 PDA 扫码操作交互，不引入 | 商用授权风险 |
| n8n / Dify | fair-code / 附加条款 | 不引入，推送与审批自研 | 不可商用分发 |

**对设计的直接影响**：
1. 库存模型向 Odoo「流水 + 现存量」演进——现有 `movements`/`stocks` 已天然符合，只需增强，不需重构；
2. 质检管线对标 ERPNext Quality Inspection 设计「检验单 + 物料级检验开关 + 提交门禁」；
3. 领料分配对标 InvenTree allocation 设计两段式表结构（MIT，实现细节可参考其源码）；
4. OCR 管线复用 meter 已验证的「视觉 LLM 严格 JSON」模式，PaddleOCR 作为复杂版面的后备。

---

## 4. 总体架构

### 4.1 技术栈（延续现有，不引入新框架）

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.0 (async) + Pydantic v2 | 与现有模块一致 |
| 数据库 | PostgreSQL，独立 schema `warehouse` | 沿用；流水表按年分区预留（movements 已过万条/半年） |
| 迁移 | Alembic | 每期一个迁移文件 |
| 前端 | Next.js (App Router) + TanStack Query + Tailwind + shadcn/ui | 对齐现有 dashboard |
| 移动端 | 飞书内 H5（响应式页面）+ 手机拍照上传 | 录入类页面优先适配 |
| 消息推送 | `platform/integrations/feishu/message.py` 群卡片 | 复用 |
| 审批 | 飞书原生审批实例（hr 职称评审轮询模式） | 复用 |
| 定时任务 | `platform/scheduler`（cron TaskDefinition） | 复用 |
| AI | `platform/integrations/ai` + 多模态视觉 LLM（DeepSeek vision 模式） | 复用 meter 管线模式 |

### 4.2 模块结构（对齐模块约定，规模增长后分包）

```text
app/modules/warehouse/
├── api/                        # 按域拆分路由
│   ├── materials.py            # 主数据 + 供应商
│   ├── receipts.py             # 入库与质检
│   ├── requisitions.py         # 领料与发料
│   ├── stocks.py               # 库存/流水/盘点（现有）
│   ├── reports.py              # 报表与台账
│   └── ai.py                   # OCR 识别
├── models/                     # 按域拆分 ORM
│   ├── base.py                 # 现有 6 表（演进）
│   ├── quality.py              # 入库单/质检单/质量主数据
│   ├── requisition.py          # 领料单/allocation
│   ├── compliance.py           # 专项台账/呆料/不合格处理
│   └── sales.py                # 销售/开票
├── service/                    # 业务编排（一域一文件）
│   ├── receipt_service.py      # 入库→请检→出报→放行状态机
│   ├── requisition_service.py  # 审批→FIFO 匹配→发料→扣减
│   ├── inspection_service.py
│   ├── notify_service.py       # 推送编排（事件型）
│   ├── report_service.py
│   └── ai_service.py           # OCR 识别管线
├── repository.py / schemas.py / permissions.py   # 随域扩展
├── scheduler.py                # 定时推送任务注册（对标 energy/scheduler.py）
└── feishu/                     # 消息模板 + 路由规则
    ├── templates.py            # 卡片文案（对应 Base 20 流程的消息）
    └── routing.py              # 物料大类→群/人 路由
```

### 4.3 领域总览

```text
┌─────────────────────────── warehouse 模块 ───────────────────────────┐
│                                                                      │
│  主数据域                作业域                     分析/合规域        │
│  ┌─────────────┐   ┌──────────────────┐   ┌────────────────────┐  │
│  │ 物料(扩展)   │   │ 入库单 receipt    │   │ 三态库存/周报表     │  │
│  │ 库位         │──▶│ 质检单 inspection │──▶│ 呆料/不合格处理     │  │
│  │ 供应商名录   │   │ 领料单 requisition│   │ 专项台账(易制毒)    │  │
│  │ 质量主数据   │   │ 库存/流水/盘点    │   │ 销售与开票四口径    │  │
│  └─────────────┘   └──────────────────┘   └────────────────────┘  │
│         ▲                  ▲    │                 ▲                │
│         │          ┌───────┘    ▼                 │                │
│  ┌──────┴───────┐  │   ┌──────────────┐  ┌───────┴────────┐       │
│  │ OCR 识别管线  │──┘   │ 推送/审批管线 │  │ GMP/ERP 同步    │       │
│  └──────────────┘      └──────────────┘  └────────────────┘       │
│                          （复用平台底座）                            │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 5. 数据模型设计

### 5.1 现有表演进（不破坏 MVP 语义）

**`warehouse_materials` 扩展**（对标「物料名称代码一览表」25 字段）：

```python
# 新增列
erp_code: Mapped[str | None]            # ERP 编码（如 11005948）
erp_name / erp_spec: Mapped[str | None] # ERP 名称/规格（识别对齐用）
hazard_class: Mapped[str | None]        # 法规危险性分类（危化品/易制毒/易制爆标记）
package_spec: Mapped[str | None]        # 包装规格（如 25Kg/袋、槽车）
unit_conversions: Mapped[dict]          # JSONB：件数换算/数量换算/单位换算（含 kg↔十亿等特殊换算）
shelf_life_days: Mapped[int | None]     # 有效期（天）
retest_days: Mapped[int | None]         # 复验期（天）
inspection_required: Mapped[bool]       # 物料级检验开关（对标 ERPNext，默认 True）
exempt_inspection: Mapped[bool]         # 免检物料（默认 False）
report_days: Mapped[int]                # 请检后出报天数（默认 3，驱动应出报日期）
full_inspect_cycle_months: Mapped[int | None]  # 全检周期（月）
is_dual_standard: Mapped[bool]          # 双标物料
sub_category: Mapped[str | None]        # 细分类：固体/液体/槽车（原辅料库）/铝听/橡胶圈（包材）
usage_departments: Mapped[list[str]]    # JSONB：使用部门清单（车间用量计划用）
```

**`warehouse_stocks` 扩展**：

```python
qc_status: Mapped[str]     # pending待检 / released放行 / conditional条件放行 / rejected否决 / returned退货
received_at: Mapped[datetime | None]    # 入库日期（FIFO 排序键）
expires_at: Mapped[datetime | None]     # 有效期至/复验期至（FEFO 与到期提醒）
supplier_id: Mapped[uuid.UUID | None]   # 供应商（入库带入）
```

**`warehouse_movements` 扩展**：

```python
source_no: Mapped[str | None]           # 关联业务单据号（入库单/领料单/盘点单）
qc_status_at_move: Mapped[str | None]   # 移动时的质量状态快照（质量门禁审计）
operator_id: Mapped[uuid.UUID | None]   # 操作人（入库仓管员/发料人）
usage_department: Mapped[str | None]    # 领用部门
usage_type: Mapped[str | None]          # 领用类型：生产使用/销售/返工/退货
```

### 5.2 新增表

#### 质量域（对标入库总账 62 字段 + ERPNext QI）

**`warehouse_receipts` 入库单（业务主实体，一单一批次）**

```python
receipt_no: str                  # 单号（如 SRM26123101 风格）
# 到货信息
arrival_type: str                # 到货情况：material到货物料 / type_a A类物料 / tanker 槽车
arrived_at: datetime             # 到货日期
arrival_period: str | None       # 到货时间段（槽车）
plate_no: str | None             # 车牌
contract_no: str | None          # 合同编号或订单号
supplier_id / manufacturer_id    # 供应商/生产商
material_id, batch_no, vendor_batch_no, quantity, unit, package_qty
produced_at / expires_at         # 生产日期/有效期至
storage_point: str               # 贮存/槽车取样点
photos: JSONB                    # 外包装/厂家报告单/送货单照片（附件 token 列表）
# 请检信息
inspection_type: str             # normal普通 / urgent加急 / sample_recheck取样复核（可组合标志位）
inspection_at: datetime | None   # 请检日期
expected_report_at: datetime | None  # 应出报日期 = 请检 + material.report_days
# 状态机
status: str                      # arrived到货 → requested已请检 → sampling已取样
                                 # → reported已出报 → released放行/conditional/rejected
                                 # → stocked已入库（放行后生成 movement+stock）
inspected_by / released_by: uuid # QC出报人 / QA放行人
reported_at / released_at: datetime
remark: str
```

**`warehouse_inspections` 质检单（对标 ERPNext QI，含请验单附件）**

```python
inspection_no: str
receipt_id: uuid                 # 关联入库单
stage: str                       # incoming入厂检验（预留 in_process/outgoing）
sampling_status: str             # sampled已取样 / not_sampled未取样 / not_required无需取
sampled_at: datetime | None
request_form: JSONB              # 请验单附件
qc_report: JSONB                 # QC报告单附件
qc_result: str | None            # qualified合格 / unqualified不合格
qc_reported_at: datetime | None  # 出报提交时间（超期=now-expected_report_at）
qc_reported_by: uuid | None
unqualified_items: str | None    # 不合格项目（如"干燥失重10.3%，标准≤10.0%"）
qa_decision: str | None          # released放行 / conditional条件放行 / rejected否决
qa_decided_at / qa_decided_by
reviewer_id: uuid | None         # 原辅料取样记录复核人
```

> **设计决策**：Base 把 62 个字段平铺在入库总账一行；dazah 拆为 receipt（到货+状态）+ inspection（QC/QA 过程）两张表，receipt 冗余最终状态列。拆分理由：出报/放行是不同角色在不同时间的操作，分表后权限与乐观锁更干净；前端仍以「批次视图」（JOIN）还原 Base 的单行体验。

#### 领料域（对标备用表 33 字段 + InvenTree allocation）

**`warehouse_requisitions` 领料单**

```python
requisition_no: str
requisition_date: datetime
requester_id: uuid                # 领用人
usage_department: str             # 领用部门（发酵工程一部/提炼工程四部…）
usage_type: str                   # 生产使用/销售/返工/退货
status: str                       # draft → pending_approval待审批 → approved已批
                                 # → allocated已匹配 → issued已发料 → cancelled
approval_instance_id: str | None  # 飞书审批实例 code
approval_opinion: str | None      # 审核人意见
approved_by: uuid | None
remark: str                       # 备注（如指定厂家批号）
```

**`warehouse_requisition_items` 领料明细行**

```python
requisition_id, material_id, quantity, unit
```

**`warehouse_allocations` 批号分配（对标 InvenTree StockItem allocation）**

```python
requisition_item_id, stock_id    # 分配到具体库存行（material+batch+location）
batch_no, location_id            # 冗余快照
allocated_qty: Decimal
strategy: str                    # fifo / fefo / manual（人工调整批号时标记 manual 并记原因）
status: str                      # allocated → issued；发料确认后置 issued
adjust_reason: str | None        # 人工换批号原因
issued_by: uuid | None           # 发料人
issued_at: datetime | None
```

#### 供应商域（Base 无此表，新建）

**`warehouse_suppliers`**：`code, name, type(供应商/生产商), qualified(合格/待审/暂停), audit_status, audit_date, materials(JSONB 供货物料与编码), contact, remark`
**`warehouse_supplier_changes`**：准入/变更审计流水（采购发起→QA 同意的审批记录，复用审批管线）。

#### 合规与处理域

**`warehouse_compliance_records` 专项台账**（易制毒/易制爆，覆盖 Base 入库表/出库表/月度平衡表）：

```python
record_type: str                 # inbound / outbound / monthly_balance
regulatory_type: str             # precursor易制毒 / explosive易制爆 / hazmat危化品
filing_no: str | None            # 备案证号
keeper_signatures: JSONB         # 仓管员两人签名（user_id+时间戳，电子签）
recipient_signature: uuid | None # 使用单位签名
picker_signature: uuid | None    # 领料员签名
movement_id: uuid | None         # 关联流水
prev_month_carry / month_balance: Decimal | None   # 上月转存/本月结余（月度平衡）
```

**`warehouse_disposal_cases` 呆料/不合格处理单**（覆盖呆料汇总 46 字段 + 不合格汇总 21 字段的处理闭环）：

```python
case_type: str                   # dead呆料 / unqualified不合格 / returned退货
source_receipt_id / source_movement_id
material_id, batch_no, quantity, unit
reason: str                      # 停用原因/不合格项目
monthly_usage: JSONB             # 月度出库趋势（自动统计回填）
processing_method: str | None    # 处理方式（退货/销毁/复产消耗…）
processed_qty: Decimal           # 已处理总量
progress: str                    # 待处理/处理中/已处理
approval_instance_id: str | None # 处理方案审批
unit_price / total_value: Decimal | None   # 呆料金额
owner_id: uuid                   # 责任班组长（按大类路由）
```

#### 分析与销售域

**`warehouse_usage_plans` 车间用量计划**：`department, material_id, period(周/月), planned_qty` —— 安全库存动态提醒的数据源（计划文档 1.5 项）。
**`warehouse_sales_records` 销售记录**（对标销售明细表）：`sale_date, material_id(成品), customer, quantity, unit, converted_qty, remark`。
**`warehouse_invoice_records` 开票记录**：`invoice_date, material_id, customer, quantity, unit, sale_record_id | None` —— 与销售记录独立成表，四口径由 SQL 聚合（见 6.9）。

### 5.3 主数据迁移与字典对齐

- 「物料名称代码一览表」602 条 → `warehouse_materials` 扩展后字段直迁（供应商/生产商选项 → supplier 表 + 关联）；
- 三态周报表、月度报表**不建表**，改为报表服务实时聚合（Base 里它们本来就是 formula/lookup 投影）；
- Base 的「数据筛选」类表（单行查询参数表）不迁移，由 API 查询参数替代。

---

## 6. 业务管线设计

### 6.1 质量管线：入库 → 请检 → 出报 → 放行（P1 核心）

```text
手机拍照/手工录入 → 入库单(arrived)
    ├─[免检物料]──────────────────────────────▶ 直接入库 stocked
    └─ 请检(inspection_type=普通/加急/取样复核) ─▶ inspection 创建(sampling=not_sampled)
         │  推送：物料取样群「请验单:物料 批号」（槽车→车间槽车沟通群）
         ▼
      QC 取样(sampling=sampled) ── QC 出报(result=合格/不合格, qc_report 附件)
         │  定时：每日 08:30 漏取/超期提醒（应出报日期已过仍未出报；加急醒目标识）
         │  推送：物料放行群「已出报:物料 批号」
         ▼
      QA 决策(released / conditional / rejected)
         │  推送：放行→仓库到货信息群+槽车群；条件放行→槽车群；否决→取样群+到货群
         ▼
      released → 生成 inbound movement + stock(qc_status=released) [同一事务]
      rejected → stock(qc_status=rejected, 隔离库位) → 触发 disposal_case(不合格)
```

**规则（迁移自 Base 20 流程 + ERPNext 借鉴）**：
- 出报超期：`expected_report_at = inspection_at + material.report_days`，超期天数入库单冗余列，每日定时任务扫描；
- 全检物料：按 `full_inspect_cycle_months` 计算下次全检日期，到期提醒（对标全检物料周期表）；
- 检验开关：`material.inspection_required=false` 的物料走免检直入（对标 ERPNext Item 级开关 + Base 免检判断）；
- 重复到货判断：同物料+厂家批号+合同号重复时提醒（对标「判断入库报表重复」公式）。

### 6.2 领料管线：提单 → 审批 → FIFO 匹配 → 发料（P1 核心）

```text
车间在 H5 提领料单(明细行=物料+数量)
    ▼
部门负责人审批（飞书原生审批实例，轮询回调状态）
    ▼ approved
自动匹配：对每个明细行，在 stocks 中筛选
    qc_status IN (released, conditional) AND quantity > 0
    ORDER BY received_at ASC（FIFO；危化品近效期可配 FEFO: ORDER BY expires_at ASC）
    生成 allocations（可跨多批次拆分）
    ▼
发料人在 H5 确认发料（可人工换批号：改 allocation，strategy=manual+原因）
    ▼ issued
校验质量门禁：批号 qc_status ∉ (released, conditional) → 拦截并告警仓储部群
    （对标 Base 出库质量门禁：未出结果/否决/退货发料告警）
    ▼
生成 outbound movement（含 operator=发料人, qc_status_at_move 快照）+ 扣减 stock
    ├─ 剩余数量 < 0 → 回滚 + 推送「数量减超」告警（对标减超提醒流程）
    └─ 物料属易制毒/易制爆 → 自动生成 compliance_record(出库台账)，双人签名待补
```

**对标来源**：InvenTree allocation 两段式（MIT，表结构与状态流转参考其源码）；Odoo removal strategy（FIFO/FEFO 策略配置）；Base 备用表字段（领用审核人/审核人意见/发料人/可领量/跨批号=多批次拆分）。

### 6.3 库存账务与三态视图

- **流水不可变**：movements 只增不改不删（MVP 的「撤销=软删」改为「红冲流水」——新增一笔反向 movement，对标 Odoo stock.move 与 GMP 审计要求）；
- **现存量唯一权威**：stocks.quantity 由 service 层在 movement 事务内增减（对标 Odoo quant）；
- **三态视图**：任意时点按 `qc_status` 聚合（放行/待检/否决），即 Base「原材料周库存报表」与三态列的替代；
- **盘点**：沿用现有 stocktake，confirm 时生成 adjust movement（已实现，补 qc_status 快照）。

### 6.4 推送管线（推送引擎）

**统一抽象**：`notify_service.publish(event_key, payload)` → 查 `warehouse_notify_rules` 路由 → 渲染模板 → `send_group_card`。

```python
# 路由规则表（替代 Base 流程里的 Switch 分支）
warehouse_notify_rules:
  rule_key       # arrival / inspection_request / qc_reported / qa_decision /
                 # daily_summary / overdue_report / stock_alert / disposal_new / ...
  category       # raw 原辅料 / hazmat 危化品 / packaging 包材 / intermediate 中间体 / all
  targets        # JSONB: [{type: group|user, id: 飞书群/人}]
  enabled: bool
```

**事件型**（service 事务提交后异步发）：到货、请检、出报、放行/否决、出库门禁告警、减超告警、呆料/不合格新增（定向班组长）。
**定时型**（scheduler 注册，对标 Base Timer×3）：

| 任务 | cron | 内容 |
|---|---|---|
| 漏取/超期提醒 | 每日 08:30 | 未取样超 1 天、应出报未出报（加急醒目标识）；危化品另发危化品群 |
| 出入库日报 | 每日 17:30 | 按大类分群播报今日入库/出库汇总（含槽车请检催办） |
| 库存预警 | 每日 08:30 | stocks 低于 material.safety_stock → 推送预警清单 |
| 不合格/呆料催办 | 每月 28 日 | disposal_cases 处理方式未填 → 定向班组长+管理人员群 |
| 周库存报表 | 每周一 09:00 | 三态周报推送特定人员 |

### 6.5 审批管线（通用组件）

复用 hr 职称评审模式：`approval_service.start(key, form, fields)` → 飞书原生审批实例 → 定时轮询（scheduler 复用）或事件回调 → 更新业务单据状态。适用：**领料审批、呆料/不合格处理方案审批、供应商准入审批**（三处共用，即计划文档的「审批流程联动」共性能力）。

> 备选：若业务方要求审批留痕在 dazah 内，增加 `approval_snapshot` JSONB 列存实例详情。默认走飞书原生，移动端体验最好。

### 6.6 OCR 智能录入管线（P2，AI 增强）

```text
手机拍照（H5 上传：送货单/厂家报告单/快递单）
    ▼
识别服务 ai_service.recognize(doc_type, image)
    ├─ 优先：多模态视觉 LLM（复用 meter 模式：VISION_PROMPT + 严格 JSON + 3 次指数退避重试）
    ├─ 后备：PaddleOCR 文字+版面 → LLM 抽取（版面复杂表格时）
    ▼
字段对齐：识别结果模糊匹配 warehouse_materials（名称/ERP编码/规格/供应商，602 条主数据字典）
    ├─ 唯一命中 → 预填入库单草稿
    ├─ 多候选/未命中 → 标记人工选择/新建物料
    ▼
H5 人工确认表单（识别置信度可视化，低置信字段高亮）
    ▼
确认后走 6.1 质量管线正常入库（来源标记 ocr）
```

**关键约束**：识别结果**永不直接落库**，一律走「草稿 + 人工确认」；每张单据保留原图附件与识别 JSON（审计与模型改进数据）。快递单号识别同管线（识别→推送特定人员）。

### 6.7 专项合规台账（易制毒/易制爆）

- 入库/出库流水发生时，物料 `hazard_class ∈ (易制毒, 易制爆)` 自动生成 `compliance_records`（入库台账/出库台账）；
- 双人签名：仓管员签名列记录操作人与复核人两个 user_id+时间戳（H5 依次确认）；使用单位/领料员签名由领料方在 H5 补签；
- 月度平衡表：定时任务每月生成（上月转存 + 本月入出 + 本月结余），对标 Base 月度平衡表；
- 监管报表导出：按备案证号/时间段导出 Excel（复用安全模块 template_export 模式）。

### 6.8 GMP 质量端数据

Base 现状是质量部在 GMP Base 重复录入仓储端数据（SourceID 回链）。dazah 方案：**单一数据源**——仓储端入库单即为质量端数据，GMP 出库（含生产批号、单据类型）在领料管线中以 `usage_type + production_batch_no` 扩展字段承载；「出库每日汇总」改为报表服务按日透视。历史 GMP Base 数据（1729 条入库 + 132 条出库）导入 movements/stocks 并打 `source='gmp_import'` 标记。质量部验收口径：GMP Base 的两张总账在 dazah 的「批次视图 + 出库流水」中等价可查。

### 6.9 销售与开票（P3）

- `sales_records`（发货）与 `invoice_records`（开票）双轨独立录入（可各自 OCR 辅助）；
- **四口径 = SQL 聚合视图**：本月开票合计（invoice 按月）、本月发货未开票（sale 无关联 invoice）、本月开票未发货（invoice 无关联 sale）、上月开票本月发货（invoice 上月 + sale 本月关联）——替代 Base 月度汇总表的手工 number 列；
- 代理商分析：sales_records 按 customer 聚合，与 usage_plans 中成品月计划对比（辅助排产）；
- 特殊单位换算走 material.unit_conversions（硫酸黏菌素 kg↔十亿），报表双单位展示。

---

## 7. API 设计（在现有 20 条之上按域扩展）

```text
/api/v1/warehouse/
├── overview / materials / locations / stocks / movements / stocktakes   # 现有
├── suppliers                  # GET/POST/PUT/DELETE + 准入审批发起
├── receipts                   # GET(分页/按状态筛选)/POST/PUT
│   ├── {id}/request-inspection    # 发起请检（含请检类型）
│   ├── {id}/sample                # QC 取样登记
│   ├── {id}/report                # QC 出报（结果+附件）
│   ├── {id}/decide                # QA 放行/条件放行/否决
│   └── {id}/stock-in              # 放行后入库确认
├── inspections                # 质检单查询/详情（含超期标记）
├── requisitions               # GET/POST(提单)/PUT
│   ├── {id}/submit                # 提交审批（发起飞书审批）
│   ├── {id}/allocations           # GET 自动匹配结果 / PUT 人工调整批号
│   └── {id}/issue                 # 确认发料（含质量门禁校验）
├── compliance-records         # 专项台账查询/签名/月度平衡生成/导出
├── disposal-cases             # 呆料/不合格处理单 CRUD + 审批发起 + 统计
├── usage-plans                # 车间用量计划 CRUD
├── sales-records / invoice-records   # 销售/开票 CRUD + 四口径汇总 GET /summary
├── reports/
│   ├── weekly-stock            # 三态周库存
│   ├── monthly-summary         # 分类月度出入库汇总（6 张报表合一参数化）
│   └── aging                   # 超 6 月未出库/呆料清单
└── ai/
    └── recognize               # POST 图片 → 识别草稿（入库单预填）
```

权限：沿用模块 `permissions.py` 模式，新增 `warehouse.qc`（QC 取样/出报）、`warehouse.qa`（放行决策）、`warehouse.keeper`（仓管/发料）、`warehouse.approver`（领料审批）等角色动作。

---

## 8. 前端与移动端

**桌面端**（现有 4 页扩展）：
- `warehouse/` 概览：增加质量看板（待检/超期/待放行数量）+ 预警清单；
- `warehouse/receipts` 入库单列表/详情（新）：状态时间线、附件预览、请检/出报/放行操作按钮（按角色显隐）；
- `warehouse/requisition` 领料单（新）：提单→审批状态→分配结果（批号表格可改）→发料确认；
- `warehouse/inventory` 增加 qc_status 筛选与三态汇总卡；`warehouse/reports` 报表中心（新）；`warehouse/compliance` 专项台账（新）。

**移动端（飞书 H5）**——按「现场操作优先」排序：
1. 拍照录入（OCR 管线入口，送货单拍照→确认表单）；
2. 领料提单与发料确认（车间与仓管高频操作）；
3. 入库登记与请检（到货现场）；
4. 审批待办（跳转飞书审批原生页面，不自建）；
5. 消息卡片按钮直达对应单据（复用卡片回调能力）。

实现方式：响应式页面（同一 Next.js 路由，移动布局断点），不单独维护小程序；列表类页面保持桌面优先。

---

## 9. 数据迁移（Base → dazah）

| Base 表 | 目标 | 策略 |
|---|---|---|
| 物料名称代码一览（602） | materials + suppliers | 字段映射脚本导入，供应商选项独立成表 |
| 物料入库总账（3285） | receipts + inspections | 全量导入；质量状态按 QC出报/QA放行 列映射；附件 token 迁移（bitable 附件下载转存 OSS/本地 uploads） |
| 物料出库总账（17196）+ 备用表 | movements（source='legacy'） | 历史流水直入，不回溯生成领料单 |
| 物料库存明细总表（2249） | stocks | 以明细总表为现存量基线（与流水核对，差异出盘点单） |
| 呆料汇总/不合格汇总 | disposal_cases | 导入存量，状态映射 |
| 全检周期/双标/数量预警 | materials 扩展字段 + safety_stock | 字段级映射 |
| GMP 两张总账 | movements（source='gmp_import'） | 按 SourceID 与仓储端去重 |
| 销售明细/月度汇总 | sales_records/invoice_records | 明细导入；汇总表不导（视图重建） |

迁移工具：一次性脚本 `scripts/migrate_from_feishu_base.py`（读 base_scan 同款 lark-cli 通道），导入后出「迁移对账报告」（各表行数、库存金额对平、状态分布）。

---

## 10. 分期实施计划

### P1 业务闭环（目标：替换物料系统 Base 的日常操作）

| 交付物 | 内容 | 对应计划文档 |
|---|---|---|
| 主数据扩展 | materials 新列 + suppliers + 主数据迁移 | 前置 |
| 质量管线 | receipts/inspections 全流程 + 状态机 + 质量门禁 | 原辅料 1（除拍照）、2 的门禁部分 |
| 领料管线 | requisitions/allocations + 飞书审批 + FIFO/FEFO | 原辅料 2 |
| 推送引擎 | notify_rules + 事件/定时任务 + 5 类定时推送 | 原辅料 5/7 的推送部分 |
| 报表 v1 | 三态周库存、月度汇总、超 6 月清单、周报推送 | 原辅料 5/7 |
| 专项台账 v1 | compliance_records + 双人签名 + 导出 | 原辅料 7（危化品/易制毒/易制爆报表） |
| 移动端 v1 | 拍照上传、入库登记、领料提单/发料、H5 适配 | 手机端约束 |
| 数据迁移 | 物料系统全量迁移 + 对账报告 | 前置/并行 |

**P1 验收**：Base 20 个流程的每条消息在 dazah 有等价推送；郑旭等一线人员完成 2 周双轨并行后切换。

### P2 AI 增强

OCR 识别管线（送货单/厂家报告单/快递单号）+ 识别草稿确认流（原辅料 1 拍照部分、3、成品 2 部分）；呆料/不合格处理审批闭环（disposal_cases + 审批）；安全库存动态提醒（usage_plans 驱动，原辅料 5）；GMP 历史数据导入与批次视图（原辅料 3）；合理化库存 AI 建议 v1（用量规律分析报告，原辅料 6）。

### P3 外部集成与成品

（成品产销存 Base 已于 2026-09-03 授权可读写，原阻塞解除；V1.0 场景 D 先行试点成品出库识别登记）。成品出入库/库存（常温/冷藏分区、外购样品，成品 1/3）；退货/不合格/待处理闭环（成品 4）；销售/开票双轨与四口径（成品 5/6 + G3/G4）；发货去向与代理商分析（成品 5）；ERP 衔接（`platform/integrations/erp` 落地，出入库与库存双向同步，原辅料 1/成品 1 的 ERP 部分）；自然语言库存查询（V1.0 已通过机器人 Agent 提供，V2 并入 Web 端）。

---

## 11. 风险与待确认事项（含 V1.0）

| # | 事项 | 影响 | 责任方 |
|---|---|---|---|
| 1 | ~~物料系统写权限~~ **已解决**（测试版管理权限生效，2026-09-03 实测读写全通） | — | — |
| 2 | ~~测试版与工作版数据分叉管理~~ **已确认（2026-09-03）**：多维表格全部使用测试版，工作版完全不动；数据分叉属预期，生产切换策略留到 V1.1 | V1.0→V1.1 切换 | 已决策 |
| 3 | **物料名称字段重复选项（N,N-二甲基甲酰胺 ×2）**：该字段按名写入必然失败 | S2 该字段写入降级处理（跳过+人工补填提示）；后续治理恢复直写 | 业务方暂缓，待办 |
| 4 | ~~新应用 scope 核对~~ **已完成**（2026-09-03 业务方确认配置好收消息/图片/卡片回调） | — | — |
| 5 | ~~App Secret 轮换~~ **已完成**（2026-09-03 已重置并验证换 token/Base 读取正常） | — | — |
| 6 | 13 项计划的责任人与时间全部「待定」 | 排期无法锁定 | 仓储部确认优先级 |
| 7 | 消息路由的目标群/人员名单（5 群 + 班组长×4 + 汇总人） | V2 推送引擎联调依赖（V1.0 不涉及） | 仓储部提供清单 |
| 8 | 飞书审批需在开发者后台创建 3 个审批定义 | V2 审批管线依赖 | 开发+管理后台 |
| 9 | 附件迁移量（入库总账照片数千张）与存储位置 | V2 迁移工作量 | 开发评估 |
| 10 | ERP 对接方式未知（接口/文件） | V2/V3 ERP 衔接 | IT/业务方 |
| 11 | 双轨并行期间 Base 与 dazah 数据一致性策略（V2 建议：Base 只读，dazah 唯一写入） | V2 切换风险 | 仓储部决策 |
| 12 | 旧 `dazah` 库不可用，开发/验证统一用 `dazah_whdev` + DATABASE_URL 覆盖 | 开发环境 | 已知，遵守 |
| 13 | Base 写入的并发/限流（1254291 冲突）与字段改名导致的静默失败 | V1.0 工具层稳定性 | 开发：写前 schema 校验+重试 |

---

## 附录 A：飞书 20 个流程 → dazah 能力映射

| Base 流程 | 触发 | dazah 归属 |
|---|---|---|
| 请检推送按钮 | Button | receipt.request-inspection → 事件推送（多级路由） |
| QC出报推送QA | ChangeRecord | inspection.report → 事件推送 |
| QA放行否决推送 | ChangeRecord | inspection.decide → 分级路由推送 |
| 出报状态改动/报告单改动 | SetRecord | inspection 状态审计通知 |
| 到货推送到货群 | ChangeRecord | receipt 创建 → 事件推送 |
| 入库复核（按大类分群） | AddRecord | receipt 创建 → 按 category 路由 |
| 出库推送（质量门禁+减超） | AddRecord | requisition.issue → 门禁校验+告警 |
| 领料推送审核人/班组群 | Add/SetRecord | requisition.submit → 审批发起+通知 |
| 发料填发料人+减超提醒 | ChangeRecord | allocation.issue → 扣减校验+告警 |
| 改入库自动改库存明细 | SetRecord | receipt.stock-in → 事务内 stock 同步 |
| 不合格/呆料新增并通知班组长 | SetRecord | disposal_case 创建 → 定向通知 |
| 每日入库出库通知（17:30） | Timer | scheduler 日报任务 |
| QC领用7天漏取提醒（08:30） | Timer | scheduler 超期扫描任务 |
| 每月通知（28 日催办） | Timer | scheduler 催办任务 |
| 领用新增按钮（跨批次） | Button | allocation 多批次拆分（自动+手动） |
| 通知吴志华（药用聚乙烯袋） | AddRecord | notify_rules 定向规则（参数化） |
| 每日入库出库通知（旧版停用） | Timer | 已被 17:30 版替代，不迁移 |

## 附录 B：License 合规红线

- ERPNext（GPL-3.0）：仅设计参考，禁止复制源码；
- Odoo（LGPL-3.0）：模型参考，避免整段拷贝；
- InvenTree（MIT）：可复制代码，保留版权声明；
- PaddleOCR（Apache-2.0）：可自由集成；
- 国内 Java WMS（双授权）：不引入代码，仅交互参考。
