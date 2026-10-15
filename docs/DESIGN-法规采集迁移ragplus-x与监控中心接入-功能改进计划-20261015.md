# 法规采集迁移 ragplus-x 与监控中心接入 —— 功能改进计划（三期）

> 日期：2026-10-15（v2 重构，**取代同日 v1《法规爬虫现代化与监控中心接入》**——v1 按"dazah 侧现代化"设计，用户拍板改为采集端整体迁 ragplus-x）
> 代码基线：dazah @ 489496c2（feature/warehouse-module）· ragplus-x @ 97840f7
> **拍板口径（2026-10-15 用户）**：爬取与解析在同一端才符合系统性；ragplus-x=知识层，dazah=执行层；**dazah 爬虫退役**，采集并入 ragplus-x。同日追加拍板：**不分期**——两仓各按 feature-flow 一次性交付本仓全部工作包（下文分期结构保留作依赖顺序参考，"期"不再是交付边界）。
> 上游口径：
> - `DESIGN-法规标准与规程外接ragplus-x知识层-接入设计-20261013.md`（两层定位与既有接口面；本文把"法规发现"从该文档的 dazah 侧划归 ragplus-x，其余边界不变）
> - `DESIGN-安全模块Web退役与新面板-实施方案-20261012.md`（3.0 驾驶舱/无业务按钮/菜单按体系要素）
> - `DESIGN-安全模块3.0四期-四新域表结构与页面口径-20261014.md`（三态信封与页面四件套）
> - `DESIGN-安全模块后台监控化改造-联动编排架构方案-20261012.md`（R10 法规更新→影响分析；数据落位原则）

## 0. 一句话定位

法规采集（发现→获取→解析→暂存）整体落 ragplus-x，与分块/向量化/检索同端闭环（RAGFlow 原生解析直接产 Markdown，dazah 侧 2692 行抓取引擎退役删除）；dazah 只保留**业务收录**（预去重→AI 相关性判定→写 Bitable 台账→修订编排→飞书推送→事件）与**监控中心前端**，两端以三条契约 API 衔接。分三期：一期端到端最小闭环、二期监控前端+dazah 爬虫删码退役、三期韧性与联动。

## 1. 为什么可以这样迁（迁移风险≈0 的关键事实）

dazah 爬虫**从未上线**（2026-10-15 调研：路由从未挂载、无调度、无调用方、无前端入口）——没有存量运行数据、没有消费方、没有切换负担。因此这不是"迁移一个在跑的系统"，而是：

- **ragplus-x 侧 = 按目标架构新建**（移植 dazah 引擎中仍有价值的部分：10 源定义、列表页发现策略、负面词表）；
- **dazah 侧 = 只新建收录服务 + 删除死码**；
- **无双路径并存期、无切换开关**；Bitable「法规标准清单」台账存量（人工录入/历史数据）不动。

## 2. 目标架构：两层职责与数据流

### 2.1 职责划分（终态）

| 环节 | 归属 | 说明 |
|---|---|---|
| 源注册表（10 政务源 + 负面词表预过滤）、列表页发现 | **ragplus-x** | 移植 dazah `engine/sources.py` + strategies 的发现段 |
| fetch 层（限速/退避/会话）、原文 PDF 下载 | **ragplus-x** | 移植 openstd 三步下载等通道 |
| 解析→Markdown、分块、向量化、检索 | **ragplus-x** | RAGFlow 原生（引擎即服务，v1 方案要引 Crawl4AI 的理由消失） |
| 元数据提取（文号/日期/发布机关） | **ragplus-x** | 其自有 LLM + json_schema 结构化输出 |
| 爬取调度、候选暂存、采集留痕（runs/items/源健康） | **ragplus-x** | 采集侧权威留痕 |
| 预去重（vs Bitable 台账：标准号/文号/标题） | **dazah** | 台账在 dazah，查重必须在这端 |
| AI 行业相关性/类别判定 + 预算护栏 | **dazah** | 走 ai_config/ai_audit 场景治理（本厂业务判定，红线：知识层不做业务判定） |
| 写 Bitable「法规标准清单」、修订/替代/废止编排 | **dazah** | S2 域台账权威 |
| KB 生命周期指令（转正/拒绝/归档旧版） | dazah → ragplus-x | 契约② |
| `ragplus_doc_map` 映射登记 | **dazah** | 既有表沿用 |
| 飞书卡片推送、`regulation.updated` 事件、MCP 工具、采集监控前端 | **dazah** | 执行层资产 |
| 源健康探测、agent 兜底层（三期） | **ragplus-x** | 韧性能力随爬虫走 |

**AI 分工原则**：ragplus-x 的 LLM 只做**知识加工**（提取/清洗）；dazah 的 AI 只做**业务判定**（相关性/类别，全审计）。两端 AI 成本各自记账。

### 2.2 数据流（含修订场景）

```
ragplus-x（知识层）                          dazah（执行层）
─────────────────────                       ─────────────────────
调度触发 → 10 源列表发现 → 预过滤
  → fetch 原文/PDF → RAGFlow 解析
    → Markdown + 元数据(schema) → 候选暂存
        │ 契约① 候选推送 ──────────────────▶ 收录服务：预去重(vs Bitable)
        │                                        → AI 批量判定(预算护栏)
        │                                        → 写台账（修订：旧记录标替代+新记录）
        │ 契约② 生命周期回执 ◀────────────────  → promote/reject/archive_superseded
  候选转正入「安全法规标准」库                → doc_map 登记 → 飞书推送
  （拒绝=删暂存；替代=旧文档移「已废止」库）  → emit regulation.updated（三期）
        │ 契约③ 状态查询 ◀──────────────────  监控聚合端点（漏推对账拉取兜底）
```

### 2.3 三条契约 API（双仓唯一事实源，版本化 v1）

| # | 方向 | 端点 | 要点 |
|---|---|---|---|
| ① | ragplus→dazah | `POST /api/v1/safety/regulation-ingest/candidates` | 批次推送候选：`{run_id, items[{candidate_id, source, url, title, metadata{doc_no,issued_at,puborg,effective_at}, attachment{file_id,filename}, content_digest, old_version_hint, discovered_at}]}`；鉴权 `X-Ingest-Secret`（app_config `SAFETY_REGULATION_INGEST_SECRET`） |
| ② | dazah→ragplus | `POST /api/v1/crawler/candidates/{id}/lifecycle` | `{action: promote\|reject\|archive_superseded, reason, replace_candidate_id?}`；走既有 Bearer 体系加 crawler scope；promote=候选转正入正式库，archive_superseded=旧文档移「已废止」归档库（溯源可回放） |
| ③ | dazah→ragplus | `GET /api/v1/crawler/status` | `{sources[{name,layer,last_success_at,consecutive_failures,items_7d,status}], runs[...]}`；dazah 聚合进监控信封；兼作漏推对账数据源 |

契约字段改动需双仓同步升版（v1→v2），不允许单端悄悄加字段。

## 3. 代码搬运与退役清单

### 3.1 ragplus-x 得到（在该仓另行立项，落 `backend/app/services/crawler/` + `api/crawler.py`）

| 搬运件 | 来源（dazah） | 处置 |
|---|---|---|
| 10 源定义 + 负面词表 | `regulation_crawler/engine/sources.py` | 移植，配置形态转 ragplus 侧（DB 或配置文件按其惯例） |
| 列表页发现策略（api/http_parse） | `engine/strategies.py` 发现段 | 移植瘦身 |
| fetch 限速/退避/会话 + openstd 三步下载 | `service.py` 抽取段 | 移植泛化 |
| 元数据提取 | `engine/extractors.py` | **不移植选择器堆**——改 RAGFlow 解析产 Markdown + LLM schema 提取（快路径正则可少量保留） |

### 3.2 dazah 保留/新建

- **新建 `regulation_ingest` 收录服务**（可由 regulation_crawler 瘦身改名）：候选接收端点（挂路由——补上 v1 诊断的"从未挂载"）、预去重、AI 批量判定、Bitable 写入与修订编排、doc_map 登记、生命周期回执、飞书推送、收录留痕；
- **留痕表**（alembic，平台 DB 留痕类）：`safety_regulation_ingest_runs`（run 级：批次来源 run_id、判定漏斗计数、逐条结果 jsonb、回执结果、AI token）；采集侧 runs/源健康留痕在 ragplus-x，dazah 不镜像；
- 复用既有：ai_config/ai_audit、bitable writer 写台账段、push_notifier、ragplus_doc_map。

### 3.3 dazah 删除（二期，独立 commit 可 revert）

- `regulation_crawler/engine/` 全部（strategies/extractors/sources/base ≈2692 行）；
- `service.py` 的抓取/详情富化/PDF 下载/Playwright/渲染 PDF/正文保存段（收录服务只留判定+写入+推送）；
- changedetection webhook 端点与 `DEPLOY.md`（调度在 ragplus，changedetection.io 彻底退役）；
- app_config 键清理：`SAFETY_REGULATION_CRAWLER_INTERVAL_HOURS`、`SAFETY_REGULATION_CRAWLER_WEBHOOK_SECRET` 废弃；`ENABLED` 保留为收录总闸；新增 `SAFETY_REGULATION_INGEST_SECRET`、`SAFETY_REGULATION_CRAWLER_MAX_AI_TOKENS_PER_RUN`（更名 ingest 口径）。

## 4. 工作包与实施顺序（原三期划分，现仅作依赖顺序参考）

> **铁则：每个工作包只属于一个仓**，两仓各自独立开分支、开发、提交、回归，互不穿插；联调与 DoD 验收涉及双仓。
> 2026-10-15 用户拍板不分期：两仓各一次性开发全部工作包；推荐顺序仍为 契约冻结 → 采集+收录（原一期）→ 监控+退役（原二期）→ 韧性+联动（原三期），dazah 删码票以"ragplus 侧移植联调完成"为开工闸（Q4）。
> 工作区：**ragplus-x = `~/Agent work/ragplus-x`**（爬虫与解析）· **dazah = `~/Agent work/fuxing-dazah`**（收录与监控）。开发会话按仓各开一个，提示词/票据/commit 都不跨仓。

### 4.0 工作包归属矩阵（一图定分工）

| 工作包 | 开发仓 | 期 | 落点 |
|---|---|---|---|
| 契约 v1 字段冻结（§2.3） | 双仓评审、本文档为唯一事实源 | 一期前置 | 冻结后双仓并行；改动须升版双仓同步 |
| 爬虫服务：源注册（10 源+负面词表）/列表发现/fetch/解析→Markdown/元数据提取/调度/候选暂存 | **ragplus-x** | 一期 | `backend/app/services/crawler/` |
| 契约①②③服务端（含 secret/scope 鉴权） | **ragplus-x** | 一期 | `backend/app/api/crawler.py` |
| 收录服务：候选接收端点/预去重/AI 判定/台账写入/修订编排/生命周期回执/飞书推送 | **dazah** | 一期 | `app/modules/safety/regulation_ingest/` |
| 收录留痕表 + app_config 新键 | **dazah** | 一期 | alembic / registry.py |
| 监控聚合端点 + 漏推对账兜底 | **dazah** | 二期 | safety 域 API |
| 采集监控 Tab 前端 + 驾驶舱 S2 卡 | **dazah** | 二期 | `frontend/src/components/safety/regulation/` 等 |
| dazah 爬虫删码退役 + app_config 键清理 | **dazah** | 二期 | `regulation_crawler/` 删（独立 commit） |
| 源健康探测 / 浏览器动作 agent 兜底 / 自愈提取 | **ragplus-x** | 三期 | `services/crawler/` 内 |
| `regulation.updated` 事件钩子 / MCP 只读工具 | **dazah** | 三期 | 收录服务内 / mcp_tools |

> ragplus-x 侧的移植素材（dazah `engine/sources.py` 等）**只读参考、不回写 dazah**；dazah 死码按 Q4 建议二期监控验收后才删，一期保留正为移植对照。

### 4.1 一期：端到端最小闭环（约 2-3 周；契约冻结 → 双仓并行 → 联调收口）

**ragplus-x 仓（在 `~/Agent work/ragplus-x` 开发，独立分支）**
- `backend/app/services/crawler/`：源注册表（10 源+负面词表，移植 dazah `engine/sources.py`）→ 列表页发现（api/http_parse 策略移植瘦身）→ fetch（限速/退避/会话，移植 openstd 三步下载）→ RAGFlow 原生解析产 Markdown → 元数据 LLM+json_schema 提取 → 候选暂存表（其 DB 惯例）→ 自带调度（周一 06:00 起步）；
- `backend/app/api/crawler.py`：契约①推送 dazah（X-Ingest-Secret）、契约②生命周期（promote/reject/archive_superseded，正式库/废止库切换）、契约③状态查询；鉴权走其 Bearer 体系加 crawler scope。

**dazah 仓（在 `~/Agent work/fuxing-dazah` 开发，独立分支）**
- `app/modules/safety/regulation_ingest/`：契约①接收端点（挂 `api/__init__.py`——补上"从未挂载"断点）→ 预去重 vs Bitable → AI 批量判定（token 预算护栏，超限标 pending 留痕）→ 写台账 + 修订/替代/废止编排 → 契约②回执调用 → `ragplus_doc_map` 登记 → 飞书推送；
- alembic：`safety_regulation_ingest_runs`；app_config：`SAFETY_REGULATION_INGEST_SECRET` + AI token 预算键；
- 最小测试：候选接收幂等 / 预去重幂等 / 修订编排单测（ragplus 侧 mock 契约）。

**联调（一期收口，双仓同席）**
- DoD：真机全量一次跑通（ragplus 爬 10 源 → dazah 判定 → Bitable 新增可查 → ragplus 正式库出现文档 → 飞书卡送达）；同批候选重放幂等（不重复入台账/KB）；修订场景双端一致（旧文档归档+台账旧标替代）；两端留痕可按 run_id 对账；ruff/mypy 双仓对照基线零新增。

### 4.2 二期：监控中心前端 + dazah 爬虫退役（约 2 周；**全部在 dazah 仓**）

- 监控聚合端点 `GET /api/v1/safety/regulation-monitor`（契约③聚合+收录留痕）与漏推对账兜底（定时拉取 ragplus runs 比对补处理）；
- 「采集监控」Tab 全套（§5，含三态/漏斗/运行历史/详情 Drawer）+ 驾驶舱 S2 卡 metric；
- 删码退役（独立 commit 可 revert）：`regulation_crawler/engine/` 全部、`service.py` 抓取/下载/富化段、changedetection webhook、DEPLOY.md、app_config 键清理（INTERVAL_HOURS/WEBHOOK_SECRET 废弃）；
- DoD：监控页三态齐、零业务按钮、一次拉取 <2s；漏斗两端对账一致；删码后 pytest 基线与前端 build/test 全绿；对账兜底演练（人为漏推一批，巡检拉取补处理）。

### 4.3 三期：韧性与联动（约 2-3 周，独立开关默认关；**主体在 ragplus-x 仓，dazah 仓一小块**）

**ragplus-x 仓**：源健康探测（连续失败≥3 或近 7 日条数环比突降>50% → `suspect_rebuild`，契约③透出）；浏览器动作 agent 兜底（LLM 步进 Playwright，只读动作集、域白名单=10 源域、步数预算≤15、接地校验、步轨迹落采集留痕，人工点发起步）；自愈提取（解析空值换策略重试）。

**dazah 仓**：收录路径 emit `regulation.updated`（对齐后台监控化 §3.1 接入 B，R10 规则本体随事件总线项目另排）；MCP 暴露 `query_regulation_crawl_status` / `query_regulation_latest` 只读工具（聚合 ragplus 状态）；（可选）bot 命令「法规采集状态」。

**DoD**：agent 护栏用例全过（白名单/步数/接地）；步轨迹可回放；事件信封可观测；MCP 工具真机可查。

## 5. 前端监控中心设计（3.0 口径，沿用 v1 已拍板形态；**本节全部为 dazah 仓工作**）

### 5.1 形态

`/safety/knowledge-base` 双 Tab：法规清单与检索（现有）｜采集监控（新增，`?tab=monitor` 直达）；不加菜单项；运维视角的触发/开关在 ragplus-x 侧管理，dazah 前端零业务按钮（3.0 铁律）。

### 5.2 采集监控 Tab 布局（只读）

```
│ Tabs：[法规清单与检索] [采集监控]
│ ┌ StatCard 行（6 卡）───────────────────────────────────────────┐
│ │ [监控数据源 10 · 健康 8] [近7日新增 12] [AI 判定相关 5]         │
│ │ [待人工复核 2] [原文待补 3] [最近运行 10-20 06:00 · 成功]       │
│ └────────────────────────────────────────────────────────────────┘
│ ┌ SectionCard 数据源健康度 ─────────┐ ┌ SectionCard 最新法规流 ────┐
│ │ 源名/策略层/最近成功/连续失败/      │ │ 最新入库卡片流（20 条）：   │
│ │ 近7日条数(环比)/状态 Tag            │ │ 标题·类别·AI 相关性·       │
│ │ (ok|warn|down|suspect_rebuild)     │ │ 修订标记·原文链接          │
│ │ 行点击 → 源详情 Drawer              │ │ 详情复用 KnowledgeDetail   │
│ └────────────────────────────────────┘ │ Drawer（零新开发）         │
│ ┌ SectionCard 采集判定漏斗（近 30 天）───────────────────────────┐
│ │ 发现 320 → 解析成功 300 → 候选去重后 45 → AI 判定 18 →          │
│ │ 相关 12 → 入库 12 → 推送 12（左半=ragplus 留痕，右半=dazah 留痕）│
│ └──────────────────────────────────────────────────────────────────┘
│ ┌ SectionCard 运行历史（分页表）──────────────────────────────────┐
│ │ 运行时间/触发/耗时/各源 ok·fail/新增·去重·AI·待补/错误摘要       │
│ │ 行点击 → 运行详情 Drawer（采集段 ragplus 快照 + 收录段逐条管线）  │
│ └──────────────────────────────────────────────────────────────────┘
```

### 5.3 端点与三态信封（对齐四期口径）

```
GET /api/v1/safety/regulation-monitor
→ { status: not_connected | live | degraded,
    stats{...}, sources[], feed[], funnel{}, runs{data,meta}, errors }

GET /api/v1/safety/regulation-monitor/runs/{run_id}   # 两段拼接的运行详情
```

| 态 | 判定 |
|---|---|
| not_connected | ragplus 爬虫模块未部署/契约③ 404/未配 Ingest 对接 |
| live | 对接正常且无 down 源 |
| degraded | ragplus 不可达（超时报错不静默）、或存在 down/suspect_rebuild 源、或最近 run failed |

前端新增文件沿用 v1 清单：`lib/api/safety/regulation-monitor.ts` + `components/safety/regulation/`（CrawlMonitorPanel / SourceHealthTable / CrawlRunTable / RegulationFeed / AiFunnel）+ knowledge-base 页 Tabs 改造 + 驾驶舱 S2 卡（`SafetyOverviewDashboard.tsx` 有未提交改动，动前先确认基线）。

## 6. 数据落位（对齐后台监控化 §6）

| 数据 | 落位 |
|---|---|
| 法规条目本体 | Bitable「法规标准清单」（不变，单源权威） |
| 采集留痕（runs/items/源健康/agent 轨迹） | **ragplus-x DB**（采集侧权威） |
| 收录留痕（判定漏斗/回执）+ AI 审计 | dazah `safety_regulation_ingest_runs` + ai_call_audits |
| 契约鉴权与预算 | dazah app_config（Ingest secret / AI token 预算）；ragplus 侧调度周期在其配置体系 |

## 7. 决策点（待拍板）

| # | 决策 | 建议 |
|---|---|---|
| Q1 | 候选入正式库时机 | **判定前只进暂存区，dazah 判定相关才 promote**——保检索质量（不相关标准不污染 KB）， rejected 即删暂存 |
| Q2 | 接口模式 | **推送为主 + 拉取对账兜底**（巡检器模式，漏推补偿） |
| Q3 | 爬取调度载体 | **ragplus-x 自带调度**；dazah 不远程触发（两层解耦，对账兜底已覆盖漏跑） |
| Q4 | dazah 死码删除时机 | **二期监控验收后删**（一期保留作参考实现，方便 ragplus 侧移植对照） |
| Q5 | 元数据提取 LLM 归属 | **ragplus 自有 LLM**（知识加工同端）；若成本归口需要可后移 dazah 网关 |
| Q6 | changedetection.io | **彻底退役**（调度+探测都在 ragplus，不再需要外部监控组件） |
| Q7 | 前端形态 | knowledge-base 双 Tab（沿用 v1 拍板） |
| Q8 | dazah 定时任务页是否展示 ragplus 侧任务 | 一期不展示；二期监控页给只读运行视图即可，不在 dazah 建跨系统任务开关 |

## 8. 验收口径（DoD 汇总）

- **一期**：真机全量闭环跑通（爬→判→台账→KB→推送）；重放幂等；修订场景双端一致（旧文档归档+新文档转正+台账旧标替代）；两端 run_id 对账；ruff/mypy 双仓零新增。
- **二期**：监控页三态齐、零业务按钮、一次拉取 <2s；漏斗两端对账一致；删码后回归全绿；对账兜底演练（人为漏推一批，巡检拉取补处理）。
- **三期**：agent 兜底护栏用例全过（白名单/步数/接地）；步轨迹可回放；事件信封可观测；MCP 工具可查。

## 9. 明确不做

- 反爬对抗/检测规避（政务公开站无需求）；外部商用爬取 API 与云浏览器；Firecrawl（AGPL）；
- ragplus-x 直接写 Bitable / 发飞书卡（知识层不做业务执行——依赖必须单向 dazah→消费）；
- 全 LLM 图式爬取常驻链路；独立消息队列（推送+对账已够）；
- dazah 前端任何触发/编辑按钮（3.0 无按钮铁律）；
- 双仓之外的第三组件（changedetection.io 退役，不再引入外部监控）。

## 10. 跨仓协作说明（谁在哪开发）

- **开发会话按仓各开一个**：ragplus-x 侧会话的工作目录必须是 `~/Agent work/ragplus-x`，dazah 侧是 `~/Agent work/fuxing-dazah`；分支、票据（feature-flow 的 `.scratch/`）、commit 全部不跨仓。
- **本文档对两仓的角色不同**：对 dazah 是实施设计（直接照 §4 dazah 行开发）；对 ragplus-x 是**需求与契约规格**（§2.3 契约 + §4 ragplus-x 行），ragplus-x 仓内的实施票据/技术设计应落 ragplus-x 自己的 docs/，字段口径回链本文 §2.3。
- 契约字段以本文 §2.3 为唯一事实源，升版双仓同步（v1→v2），不允许单端悄悄加字段；
- 排期与依赖：契约 v1 冻结（前置，双仓半小时评审）→ 一期双仓并行 → 联调收口；二期纯 dazah；三期 ragplus-x 为主体、dazah 一小块（可并行）。
