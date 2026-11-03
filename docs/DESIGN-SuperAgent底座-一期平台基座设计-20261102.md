# Super-agent 底座 —— 一期平台基座设计

> 日期：2026-11-02
> 代码基线：feature/warehouse-module @ 1c52d163
> 前置学习：
> - DeepSeek《Super-agent 设计探索：迈向更自主的 Agent 系统》（2026-10-31，知乎官方号）——五个模块：双层架构/事件驱动/面向人的交互/存算分离/Watchdog，及消融与批处理实验数据
> - github.com/deepseek-ai/dsh-superagent-prototype（MIT 研究原型，docs/000~008 全套设计文档已研读）
> 前置文档：
> - docs/DESIGN-安全模块后台监控化改造-联动编排架构方案-20261012.md（当时拍板「不建通用事件总线/规则引擎，推迟」——**本设计取代该推迟口径**，理由见 §1.2）
> - docs/DESIGN-报警记录联动生成隐患追踪-设计方案-20261019.md（R1 样板纵切，将成二期首个接入应用）
> 性质：**两期路线的一期**。一期只建平台级基座（本设计）；二期按应用、按模式渐进改造（另行讨论）。

---

## 0. 一句话定位

把 Super-agent 的五个模式抽成一个**平台级基座**（`app/platform/superagent/`）：统一事件入口（Source/Trigger，DB 级幂等+持久化读位）、两级过滤与研判（Fast Path 规则 + observe/auto 放权开关）、任务域（Task/授权/订阅直通）、副作用队列（先存后做+保序）、Watchdog（健康+任务实质进展）——**一期不动任何现有应用行为，旁路上线，三个冒烟用例验收**；二期安全模块（首批：报警联动 R1、督办闭环、速递推送）逐应用接入。

## 1. 背景与决策链

### 1.1 路径拍板（2026-11-02）

- Super-agent 不是整体产品：文章=5 个可独立落地的模式；开源仓库=绑定 DeepSeek Harness 运行时的单 GitHub 仓库编码协作参考实现。**可引入的只有模式，不是代码**（Python/FastAPI/PG 与其 Node/TS 运行时不兼容）。
- 消融实验的关键教训（文章 §7.1）：单 Session 靠提示词让模型自行委派，5 次实验 0 次委派；「提示优先委派」仍有长尾。→ 结构性分派（Router 不配执行工具）必须由系统保证，不能靠 prompt——这是二期 delegate 转正的依据，也说明底座要先有任务域。
- 两期拍板：**一期=底座**（本设计，参考文章+仓库）；**二期=按应用按模式渐进改造**（待讨论，首批候选：安全模块）。

### 1.2 与 10-12「不建通用事件总线」推迟口径的关系

当时推迟的理由：无消费方、无形态、怕过度设计。现在条件变了：① Super-agent 提供了经过内部验证的形态与概念体系；② 已累积四个「各自手写事件循环」的现实痛（safety/warehouse 两套 event_client 进程内去重拷贝、hazard 四常驻轮询自管读位、catch_up 手工补扫、22 个调度 job 直推不经研判）；③ 报警联动 R1 已证明「候选→确认→写→督办接管」形态成立，缺的就是承接它的通用骨架。**推迟口径由本设计正式取代**；R1 设计里的工程铁律（幂等/串行写/gate/留痕）全部继承进底座。

### 1.3 现有可复用器官（不重造）

| 已有资产 | 位置 | 底座复用方式 |
|---|---|---|
| 平台调度引擎（tick 循环+TaskDefinition/TaskGenerator） | `app/platform/scheduler/` | 时间成为 Source 之一；effects 消费复用 TaskGenerator 机制（§4.4） |
| `scheduler_job_runs` 持久化补发范式 | `scheduler.py:15-45` | effects 表设计直接借鉴（先存后做/失败补发/三连败告警） |
| 事件去重（进程内 TTL） | `feishu/event_client.py:754-776` ×2 拷贝 | 下沉为 DB 唯一约束，重启不丢窗口（二期收编） |
| Bitable 漏单补扫 | `feishu/catch_up.py` | 读位持久化后成为框架能力，补扫逻辑退役 |
| `agent_pending_actions` 六态机 | `business_agent/models.py:92-140` | 不动；二期与 agent_tasks 的关系另议（§6） |
| 速递总卡/格子 | `feishu/daily_digest.py` | 一期加「需要人」回放格子（§4.6） |
| 确认卡 resume 链 | handler+executor | 不动；二期作为 Attention 的一种交付形态 |
| deny-by-default 角色三档 | `core/permissions.py` | 不动；底座准入表是它上面一层（会话范围维度），不是替代 |

## 2. 一期范围边界

### 2.1 做（五件）

1. **事件层**：Source 插件抽象 + Trigger/Thread 落库 + DB 级幂等 + 持久化读位 + Fast Path 程序过滤
2. **研判与策略层**：Eval 接口（两级过滤的 Slow Path）+ 规则引擎默认实现 + Policy 版本化 + **observe/auto 模式** + Mandate 记录
3. **任务域**：agent_tasks + 阶段表（推导式）+ 订阅直通 + Inputs；执行器只有**程序执行器**（注册的同步/异步函数）
4. **副作用层**：agent_effects 持久化队列（先存后做/退避重试/Later 语义）+ agent_outbox 会话内保序
5. **Watchdog + 观测面**：HealthBoard 组件健康注册 + 任务实质进展巡检 + DM 管理员告警；REST 端点 + 速递总卡「需要人」回放格

### 2.2 不做（留给二期/不做）

| 项 | 理由 |
|---|---|
| Router/Worker 会话分层、LLM worker | delegate（URS 试点）转正是二期安全模块首刀；消融数据证明需结构保证，随首个应用一起落 |
| 任何业务域改造（报警联动/督办/作业票/速递推送迁移） | 二期按应用渐进，另行讨论 |
| 仓储模块任何改动 | 二期复制配方时再说 |
| Eval 的 LLM 研判实现 | 一期默认规则引擎（确定性可测）；LLM assessor 只留接口（§4.2） |
| 新 Web 面板 | 一期只出 REST + 速递格子；独立面板等有真实使用再议 |
| 端侧 daemon（BYOM） | 无场景：执行环境本就常驻服务器，存算分离天然达标 |
| A2A 跨 app 通道 | 安全×仓储联动是终局选项 |
| 全量收编现有轮询 | 一期只收编 1 个作样板（拍板点⑤） |

## 3. 总体架构

```
                        ┌─────────── app/platform/superagent/ ───────────┐
                        │                                                 │
 飞书WS消息(二期)  Bitable轮询 ─┐                                        │
 报警事件(二期)   3x回调(二期)   │  ┌── Sources(插件注册) ── 读位cursor/   │
 cron定时(一期内置)──────────────┼─▶│   scope准入/翻译→Trigger             │
                        │      │  └──────────┬───────────────────────── │
                        │      │      DB幂等(uniq约束) + disposition     │
                        │      │             ▼                           │
                        │      │  Fast Path(程序过滤) ──▶ Slow Path      │
                        │      │                        Eval(规则引擎,   │
                        │      │                        observe/auto)   │
                        │      │             ▼ Decision                  │
                        │      │      Task(+Mandate) ── 订阅直通          │
                        │      │        │                                │
                        │      │   程序执行器(注册函数)                    │
                        │      │        │                                │
                        │      │  Effects队列(先存后做) ── Outbox(保序)   │
                        │      │        │                                │
                        │      │  Watchdog(健康+实质进展) ── DM管理员     │
                        │      └───────────────────────────────────────── │
                        │  PG: agent_triggers/threads/tasks/subscriptions │
                        │      /decisions/policies/effects/outbox/health  │
                        └─────────────────────────────────────────────────┘
  现有系统全部不动：business_agent(handler/确认卡/工具)、22个调度job、
  event_client、daily_digest(只加一个格子)、delegate(URS试点维持现状)
```

进程模型：基座运行在现有 backend 进程内，与 SchedulerEngine 同生命周期。effects 消费与 Source 轮询复用调度引擎的 TaskGenerator 机制（统一监督/超时），不新起裸 asyncio 循环。多消费者安全：effects 领取用 `SELECT … FOR UPDATE SKIP LOCKED`（防未来多进程部署；当前单进程亦正确）。

## 4. 分层设计

### 4.1 事件层（文章 §3.1/3.2；仓库 docs/001 Source/Trigger/Thread）

**Source 插件**（对标仓库 `SourceKind`）：每个来源声明 `kind`（稳定标识）、`scope`（收什么/不收什么，仅凭 meta 与配置判定——复验也要用）、`poll`（拉取一轮并翻译为 Trigger，推进读位）、`fields`（配置 schema）。一期内置两个：

- `cron_tick`：把平台调度的 tick 翻译成 Trigger（定时→研判→任务，为二期「定时任务工单化」铺路；external_id=`job名:计划时间`，天然幂等防重启重发——**直接修掉「重启即发定时任务」类风险**）
- `bitable_poll`：样板收编 hazard 督办轮询（现有 supervision 轮询改走 Source；读位入库，重启不重放，补扫逻辑退役）

**Trigger**：不可变事件。`(source_id, external_id)` 唯一约束=幂等（重复投递返回 duplicate，只创建一个任务——仓库同款）。携带：thread_key（归属线程）、actor（来源原生身份）、human/addressed（是否人/是否点名）、payload jsonb、channel（回哪里）。**自己的消息不产生 Trigger**（防环，继承现有 event_client 惯例）。

**Thread**：同话题事件的时间序集合（一个飞书话题/一个 Bitable 记录/一个督办事项=一条 Thread）。Thread 持有订阅与研判串行锁（同 Thread 至多一个 Eval 在跑，期间到达的合并进下一批——仓库同款，天然吃掉文章 §2.1 的批处理红利）。

**Fast Path**：程序级确定性过滤（来源开关/群白名单/发送者名单/明确忽略规则），不命中任何接收范围的记 `filtered`（含原因）不进研判。对应现有三层防线不动，Fast Path 配置只是把它们的事件面收进框架可见。

### 4.2 研判与策略层（文章 §3.1 两级过滤；仓库 docs/002）

**Eval = Gate（确定性）+ Assessment（策略）**：

- Gate：沿用并细化现有口径——名单内+点名=explicit；名单外跟进/admission 表=inferred；其余不准入。准入表按「接收范围 × 发送者 × 是否点名」三维（行=群/事件面，列=在名单未点名/不在名单点名/不在名单未点名），默认值沿用仓库推荐（保守）。
- Assessment：**一期=规则引擎**。每条规则描述一类「值得做的事」，输入=Trigger 批+Thread 快照+该 Thread 现存任务列表（防重复开工），输出=对每条启用规则逐一给判定（命中与否+证据），Decision ∈ {accept, stop, ignore, unavailable}。

**observe/auto 模式**（Policy 的一部分，全局+可按规则覆写）：

| 模式 | 行为 |
|---|---|
| `off` | inferred 一律不产生候选 |
| `observe`（默认） | 评估通过**只记 Decision（would_accept=true）不执行**，次日速递格回放，人可一键「转正/忽略」 |
| `auto` | 评估通过即开任务 |

explicit 请求任何模式都受理（这是对人的承诺，不是对系统的）。

**LLM assessor 接口预留**：`Assessor` 协议（`assess(batch, thread_snapshot, policy) -> AssessmentResult`），规则引擎是第一个实现；二期接 LLM（带置信度+逐规则判定），prompt 属于各应用，不在基座。

**Policy 版本化**：rules+accept_mode+各 Source 准入表 哈希成版本号；每次 accept 的任务记录其 Policy 版本。改版：进行中的 Eval 作废重排（对齐仓库「规则变了重研判」，但**不撤销已开任务**——只给受影响任务投递一条 policy_changed Input，避免半成品）。

### 4.3 任务域（仓库 docs/001 Ticket/Subscription/Assignment；文章 §3.2 订阅直通）

**命名**：概念名「任务」，表名 `agent_tasks`——**刻意避开「工单/Ticket」**：安全域 work_ticket=作业票（动火/高处/吊装作业许可），撞名会出人命级混淆（拍板点②）。

**Task**：一次被授权的工作。字段：origin_trigger、mandate jsonb（policy_version/scope/strength/命中规则/发起人来源身份）、stage_facts jsonb（阶段推导的输入事实：最新报告、未读输入、是否等人）、status（open/ended）+outcome。**阶段不落库，纯函数推导**（对齐仓库「Ticket 自定义状态，不跟执行器走」）：

| 阶段 | 条件（自上而下首中即用） | 总卡展示 |
|---|---|---|
| 等交付 | 输入投递失败重试中 | 投递失败 |
| 等回答 | 有 Attention（待人工问题） | 待回答 |
| 等验收 | 最新报告=ready | 待验收 |
| 受阻/失败 | 最新报告=blocked/failed 且此后无人的消息 | 受阻·失败 |
| 排队 | 无执行中 Assignment | 排队 |
| 空闲 | 最新报告=waiting | 等触发 |
| 工作中 | 其余 | 工作中 |

**订阅直通**（文章 §3.2 消融验证：省 Router 30% 决定量/37% token）：任务开单即订阅 origin Thread；同 Thread 后续 Trigger **不经研判直接作为 Input 送达该任务**（context_only 订阅不授新权）。人的消息在已订阅 Thread 上=该任务执行器自己消化（范围内处理/超范围回交重新研判）。落选的 Phase 2 场景（督办对象群里回一句→直达原督办任务）就靠这个。

**执行器（一期仅程序执行器）**：注册制——`Executor` 协议 `run(task, inputs) -> Report`。一期执行器=确定性函数（如「写 Bitable+发卡」「汇总落格」），带超时与结果截断。**LLM worker 是二期的 Executor 实现之一**（delegate 转正后挂进来），基座不需要为此预留任何特例。

**Report** ∈ {progress/waiting/ready/blocked/failed/dropped}——Attention 用结构化字段问问题，禁止从自由文本推断「在等人」（仓库 rejected concepts 同款教训）。

### 4.4 副作用层（仓库 Effects/Outbox；文章 §5.1 计算无状态化）

**agent_effects**：一切外部副作用（推卡/改卡/写 Bitable/发文件/DM）**先入库后执行**。`(kind, dedupe_key)` 待处理唯一——重复入队=替换 payload 并立即到期（不改变排队序）。执行：到期即取，失败指数退避（2s 起倍增至 60s），连续 3 次失败→HealthBoard 告警；执行器抛 `Later` 不计失败（槽位/依赖未就绪）。这直接推广 `scheduler_job_runs` 范式到全链路，**修掉裸 `asyncio.create_task` 重启即丢**的账单。

**agent_outbox 保序**：同一 (task, conversation) 的消息严格按入队顺序发送——确认先于结果，先发的失败不堵别家。目标 chat_id 等地址写入行内，任何下游组件（含总卡聚合）**不可覆盖**——修「push 指定群被总卡吞 chat_id」事故的根因。

**消费协程**：注册为调度引擎 TaskGenerator（interval 2s，逐项独立事务+超时）——统一监督，不新造第二个调度器。

### 4.5 Watchdog（文章 §6）

双层：

1. **组件健康 HealthBoard**：各组件（每个 Source/effects 各 kind/outbox/watchdog 自身）启动时**认领**健康条目（一人一条，拒绝重复认领——修 WS status 那类多写者漂移坑），状态 ready/error/paused 定时落 `agent_health` 表。error 判据沿用「连续 3 次失败才报」的既有口径，一次性网络抖动不打扰人。
2. **实质进展巡检**：不只查进程存活——按任务查「同阶段停留超阈值」（如 blocked 超 24h 无人的消息、排队超 2h 无执行器空位、observe 积压超 N 条未回放），命中则 DM 管理员一条结构化清单。巡检本身走 effects（先存后发），自举不裸奔。

一期形态=规则巡检+DM 告警；**LLM 问诊版**（自然语言问故障原因、在线改提示词/规则）是二期把 Watchdog 自身变成 observe 任务的事，接口已预留。

### 4.6 观测面（文章 §4.2 多信道规范；仓库 docs/005 三问原则）

- **REST**（`/api/platform/superagent/*`，走现有认证）：`/state`（健康+负载+暂停位）、`/tasks?stage=`、`/triggers?disposition=`、`/decisions?mode=observe&would_accept=true`、`/tasks/{id}`（含 Mandate/Inputs/订阅）。
- **速递总卡「需要人」格**：一期唯一的 UI 落点。内容=待验收+待回答+受阻超时+**observe 回放（would_accept 的 Decision 摘要，一键转正/忽略）**。健康态不占版面（仓库面板原则⑥）。
- IM 侧输出规范（100 词内/只问直接问题/只在该说话时说话）写入基座常量，供二期各应用复用。

## 5. 数据模型（PG；alembic 迁移，播种一律 ON CONFLICT DO NOTHING）

| 表 | 关键字段 | 约束/说明 |
|---|---|---|
| agent_sources | kind, name, config jsonb, enabled | 注册实例；kind 稳定复用 |
| agent_source_cursors | source_id, name, value | 持久化读位；推进仅在所覆盖 Trigger 全部落库后 |
| agent_triggers | source_id, external_id, thread_key, actor jsonb, human, addressed, payload jsonb, disposition jsonb, received_at | **uniq(source_id, external_id)**；disposition 追加式（stored/duplicate/filtered/reached_task+原因） |
| agent_threads | thread_key, label, url, meta jsonb, last_trigger_at | uniq(thread_key) |
| agent_policies | version_hash, rules jsonb, accept_mode, admission jsonb, created_at | 版本不可变；当前指针存 KV |
| agent_decisions | trigger_id, eval_id, outcome, would_accept bool, reason jsonb, policy_version, created_at | observe 回放数据源 |
| agent_tasks | short_name, title, origin_trigger_id, mandate jsonb, stage_facts jsonb, status, outcome, ended_at | 概念名「任务」；阶段不落库 |
| agent_task_subscriptions | task_id, thread_key, context_only | 多对多；ended 任务保留订阅（人的消息可唤醒） |
| agent_inputs | task_id, trigger_id?, kind, payload jsonb, delivered_at, read_at | read_at 语义对齐仓库「计入会话历史才算读」 |
| agent_effects | kind, dedupe_key, payload jsonb, status, attempts, next_due_at, last_error | 待处理 (kind,dedupe_key) 唯一；SKIP LOCKED 领取 |
| agent_outbox | task_id?, channel jsonb, purpose, body, status, attempts, sent_at, dropped_reason? | 同 (task,conversation) 严格保序 |
| agent_health | component, state, detail, updated_at | 一组件一行，认领制 |

## 6. 与现有系统的关系（一期红线：全部不动）

| 现有组件 | 一期动作 |
|---|---|
| business_agent（handler/会话/工具/确认卡） | 零改动 |
| event_client（WS+进程内去重）×2 | 零改动（二期收编去重入 DB） |
| 22 个调度 job 直推链 | 零改动（冒烟①仅旁挂一个 job 走 effects，原路径并行，开关切换） |
| agent_pending_actions | 零改动；与 agent_tasks 的归并二期随首个应用定（候选：pending_actions 降级为确认卡专用，任务语义归 agent_tasks） |
| daily_digest | 仅新增「需要人」格子，只读 REST |
| delegate（URS 试点） | 维持现状；二期转正为 LLM Executor |
| supervision 督办轮询 | 冒烟②样板改走 bitable_poll Source（原逻辑保留开关回退） |

## 7. 冒烟验收与停损

底座最大的历史风险=「线上孤儿代码」（法规爬虫 6000 行从未挂载的教训）。一期以三个**真链路冒烟**验收，全部通过才视为底座成立；任一不达即回退，不留半成品：

1. **冒烟①（effects）**：速递总卡某一格子的更新改走 agent_effects+outbox（原路径开关并行一周）；验收=重启进程消息不丢、目标 chat_id 不被覆盖、失败重试可见。
2. **冒烟②（Source/读位）**：hazard 督办轮询改走 bitable_poll Source；验收=重启不重放不漏单（人为 kill -9 后对账）、Trigger/Thread/disposition 在 REST 可查、catch_up 路径零调用。
3. **冒烟③（observe）**：报警联动候选规则（R1 设计的消防白名单口径，日均~1.5 条）以 observe 模式挂上：只记 Decision，次日速递格回放；验收=一周回放与人工判断一致率可统计，误报可接受后才有资格谈切 auto（切换本身是二期拍板）。

## 8. 实施切片

| 切片 | 内容 | 独立验收物 |
|---|---|---|
| 1a 事件+副作用 | Source 抽象/Trigger 落库/cursor/effects/outbox + 冒烟①② | 重启对账报告 |
| 1b 任务域 | tasks/subscriptions/inputs/阶段推导/程序执行器 | REST 全链路可查 |
| 1c 策略+观测 | policies/rules/observe/decisions/watchdog/需要人格 + 冒烟③ | 一周回放一致率报告 |

每切片独立 commit 进 feature/warehouse-module（唯一分支规约），pytest 全绿基线不回退（预存红名单除外）。

## 9. 拍板记录（2026-11-02 用户定案：均按推荐）

1. **基座位置与命名**：✅ `app/platform/superagent/`（与 scheduler 平级，安全/仓储二期共用）。
2. **任务命名**：✅ 「任务/agent_tasks」（避开作业票 work_ticket 撞名）。
3. **冒烟①旁挂对象**：✅ 速递总卡格子（影响面最小，原路径开关并行一周）。
4. **冒烟②样板轮询**：✅ hazard 督办轮询（二期「订阅直通」首个消费方，原逻辑保留开关回退）。
5. **observe 回放格式**：✅ 速递格逐条摘要+一键转正/忽略卡。
6. **LLM assessor**：✅ 预留骨架空实现（协议+空类），二期随首个应用接真实现。

## 10. 风险与坑清单（实现期对照）

- alembic 播种全部 ON CONFLICT DO NOTHING（迁移播种幂等修复的既有教训）。
- 健康条目认领制防多写者（WS status global 假报的同类坑）。
- effects 执行器内禁止再裸 create_task（链路必须可对账，否则先存后做失去意义）。
- stage 推导函数必须纯函数+全量单测（阶段表是所有观测的口径源头）。
- observe 切 auto 的决定权在人（速递格回放+一期不提供自动切换）。
- 研判串行锁按 Thread 粒度，绝不全局锁（防把并发又退化成串行——那正是要摆脱的现状）。
- 所有 Trigger payload 里的消息文本=不可信数据，永不参与授权判定（仓库 §004 最弱层原则）。
