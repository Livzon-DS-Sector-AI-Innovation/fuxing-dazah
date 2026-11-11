# Super-agent R3 运维自愈 —— 告警自修复设计

- 状态：设计稿（拍板点见 §12）
- 日期：2026-11-10
- 前序：底座一期（2026-11-02，`DESIGN-SuperAgent底座-一期平台基座设计-20261102.md`）、R1 报警联动（2026-11-03）、R2 监护人资格（2026-11-06）
- 触发场景：2026-11-09 RAG 知识层三次故障-恢复抖动 + 2026-11-10「作业票审核连续失败 3 次」推送失败告警

---

## 0. 一句话定位

把「系统报错 → 私发管理员卡片 → 人看到 → 人来叫 agent 修」翻转为「系统报错 → **自动开单诊断 → 授权内自动修复 → 每步结果通知（成功/失败）→ 恢复并通知双确认后才关单**」；修不了的带着根因诊断升级给人，人不用再从日志开始查。全链留痕，任何一单可回放完整时间线。

> 2026-11-11 追加三条用户要求（本版已并入）：
> ① 出问题时**通知并尝试解决**，解决结果也要通知——成功还是失败都要说；
> ② 系统服务问题同样生成**系统工单**，**直到恢复并通知以后才算关闭**（不是「动作做完」就关）；
> ③ 所有记录留痕。

## 1. 背景与决策链

### 1.1 现状问题

当前全部失败信号的处理链是「通报」终点型：

- 14 个告警点位（定时任务失败/RAG 探活/轮询失败/AI 调用失败/飞书事件失败/推送失败…）全部私发同一管理员（`scheduler.py:36 ALERT_NOTIFY_OPEN_ID`），人收到卡后**人工**去查日志、定位、处置；
- 既有自愈全是**固定规则**（补发窗口 10 分钟重试、failure_ledger 退避、effects 指数退避），没有「诊断归因」能力，跨信号关联（11-09 RAG 抖动 ×3 + 11-10 推送失败 = 网络不稳一波症状）完全靠人脑；
- 三个规则自愈的盲区没人兜底：补发窗口过期即静默放弃、隐患 AI 死信 TTL 7 天无人清、effects 连续失败 10 次 park 后永远 park。

### 1.2 既有可复用器官（不重造）

| 器官 | 位置 | R3 用法 |
|---|---|---|
| Source 插件协议 + `ingest_draft` 直投 | `platform/superagent/sources.py`、`ingest.py:46` | 扫描源 + RAG 探活直投 |
| observe/auto/off + 人工转正 | `policy.py:36`、`api.py:480` promote | 研判层模式闸 |
| effects 先存后做 + 退避 + park | `effects.py:90/133` | 修复动作执行通道 |
| Thread + 订阅直通 | `tasks.py:109/132` | 事件聚合与收口回注 |
| Watchdog 实质进展巡检 | `watchdog.py:39` | 自愈任务自身的兜底 |
| 隐患重跑核心 | `hazard_direct/rerun.py`（P3-1 下沉） | 死信/stale 重灌动作 |
| RAG 探活 | `knowledge/rag_health.py` | 信号源 + 诊断证据 |
| AI 调用底座 + 审计 | hazard AI 管线模式 / `ai_call_audits` | 诊断 LLM 调用与留痕 |

### 1.3 与既有口径的关系

- 遵守底座红线：副作用先存后做（禁裸 asyncio.create_task）、授权只看结构化字段（payload 文本永不参与）、模式切换权永远在人；
- 不建事件总线（10-12 推迟口径不变）：R3 只新增一个扫描 Source + 一处直投挂点，不动任何既有告警代码的发送逻辑。

## 2. 范围边界

### 2.1 做（一期）

1. **信号层**：两类信号接入——定时任务失败（扫描 `scheduler_job_runs`/`scheduler_task_run_log`）+ RAG 探活故障/恢复（`rag_health.py` 状态翻转直投）；
2. **诊断执行器** `r3_ops_heal`：程序化证据采集 → 单次 LLM 归因（六分类 + 置信度）→ 处方枚举校验；
3. **修复动作白名单**（注册制、分级、日上限）：一期动作集 `notify_enriched / rag_recheck / hazard_dead_letter_rerun / hazard_stale_rerun / effects_unpark / job_backfill`；
4. **上游依赖恢复探测**：根因为上游断连的 open 工单，扫描轮持续探测依赖端点，恢复即回注工单（2026-11-10 特作平台断连案例的制度化——原「可选：定时探测」建议）；
5. **修复结果通知协议**：每轮修复结束发结果卡（动作 × 成功/失败 × 详情），失败带错误原文；
6. **工单生命周期**：关闭双条件 = 信号恢复验证 ∧ 关单通知已发；含漏审日补跑闭环；
7. **观测 REST**：自愈事件列表 + 全时间线回放 + 处置（对齐 `api/alarm_hazard_links.py` 范式）。

### 2.2 不做（一期不做 / 永不做）

- 不接其余 12 个告警点位（`ai_call_audits`、推送失败、飞书事件失败等——二期按同范式追加）；
- 不做 L2/L3 动作自动执行：配置翻转、补发窗口延长、游标重置、删数据、写 Bitable、重启进程——**L3 永不注册**，卡上也不出现，只报「需人工」；
- 不做宿主机级监控/外部探针：Agent 与后端同进程，网络全断时 Agent 同盲——R3 定位是**诊断归因 + 本地恢复动作 + 恢复后补做**，不是替代基础设施监控；
- 不做自愈任务的自动模式升级：repair_mode 从 observe 翻 auto 永远人工改配置。

## 3. 总体架构

```
                    ┌──────────── 既有链（不动）────────────┐
失败发生 ──► 固定规则自愈(补发窗口/退避/熔断) ──► 告警卡私发管理员
                    └───────────────────────────────────────┘
      │
      │ ①扫描(5min)/直投(翻转即投)
      ▼
 OpsScanSource / rag_health直投 ──► Trigger(结构化,幂等)
      │                                    thread=ops:<类>:<主体>:<日期>
      ▼
 Policy(rule=r3_ops_failure) ──observe: decisions留痕+需要人格
      │                        auto: 直接开单
      ▼
 任务(r3_ops_heal) ◄── 订阅直通(同thread后续trigger=新输入)
      │
      ▼
 ┌─ 执行器三段 ──────────────────────────────┐
 │ A 证据采集(只读工具,按信号类 checklist)    │
 │ B LLM归因(单次调用,JSON契约,六分类+处方)   │
 │ C 处方校验+执行(白名单∩模式闸∩日上限)      │
 └───────────────────────────────────────────┘
      │ L0通知/诊断(总发)  L1修复(auto模式才执行,走effects先存后做)
      ▼
 修复effect ──► 下轮扫描验证 ──► 恢复trigger(同thread) ──► 收口卡🟢
                    │ 两轮未收口
                    ▼
              升级卡🔴 needs_human（带根因诊断+已试动作）
```

## 4. 分层设计

### 4.1 信号层

**A. 扫描源 `OpsScanSource`**（kind=`ops_scan`，R1 `cron_scan` 的 interval 变体）

- 轮询周期 `SAFETY_R3_SCAN_INTERVAL_SECONDS`（默认 300s，随 SourcePollGenerator 30s 心跳调度）；
- 扫描查询（全部只读）：
  - `safety.scheduler_job_runs`：`status='failed' AND attempt_count>=3`（与既有告警阈值 `ALERT_AFTER_FAILURES` 对齐）→ 产 `failed` trigger；
  - 同表 `status` 由 failed 翻 success/no_source → 产 `recovered` trigger（收口信号）；
  - **上游依赖探测**：查 open 的 R3 工单中 `root_cause_class=upstream_outage` 的依赖端点清单（诊断时从错误原文提取并落 stage_facts）→ 逐端点 TCP/HTTP 探测；由不可达翻可达 → 产 `dep_recovered` trigger（回注原工单，驱动补跑+收口）；
  - `superagent.agent_effects`：`status='parked'` 计数 ≥1 → 产 `parked` trigger（每组件每日一次）；
  - Redis `safety:hazard:ai:dead_letters` 计数（fail-open：Redis 不可达跳过本轮该项，不算故障）→ 产 `dead_letter` trigger（每日一次）。
- **Trigger 幂等设计**（external_id 内嵌状态，对齐 BitablePollSource 指纹范式）：
  - `ops:job:<job_name>:<fired_date>:failed` / `…:recovered`
  - `ops:dep:<工单id>:<endpoint_hash>:recovered`（依赖探测翻转，回注原工单）
  - `ops:parked:<component>:<fired_date>`
  - `ops:deadletter:<fired_date>`
  - thread_key：`ops:job:<job_name>:<fired_date>`（每任务每天一单，抖动反复聚同单）；`ops:opsmisc:<fired_date>`（parked/deadletter 共用日常单）。
- **防风暴**：单轮扫描产出 trigger 上限 5 条，超限合并为一条聚合 trigger（payload 带清单），不逐条开单。

**B. RAG 探活直投**（audit_trail 留痕范式，`hazard_direct/audit_trail.py:61` 同款）

- `rag_health.py` 状态机翻转处（`run_rag_health_probe` 内）加 `ingest_draft`：健康→故障、故障→恢复两次翻转各投一条；
- source 行 `enabled=false` 仅作归属载体（不参与轮询）；external_id：`ops:rag:<date>:degraded:<first_failed_ts>` / `ops:rag:<date>:recovered:<ts>`（同日多次抖动各投各的，聚到同 thread）；
- thread_key：`ops:rag:<fired_date>`——11-09 型抖动自然聚合成单，跨信号关联（同日 job 失败单 + rag 单）由诊断阶段做证据交叉。

### 4.2 研判与策略层

- rule：`r3_ops_failure`——条件 `source == safety.ops.selfheal`，executor=`r3_ops_heal`；
- Policy 播种：**追加**进 `superagent_bridge.py ensure_guardian_r2_policy()` 的组合 rules 列表（全局单版本会合点，单播子集会挤掉 R1/R2/HW——既知坑）；
- **两层模式闸**（关键设计）：
  - 研判层 `accept_mode`：播种即 `auto`（开单+诊断自动跑——诊断全程只读+发卡，零业务副作用；这是「自修复」能落地的前提，不开 auto 则回到「人转正才诊断」的旧循环）；
  - 修复层 `SAFETY_R3_REPAIR_MODE`（app_config，默认 `observe`）：控制 L1 动作是否真正执行。observe=只报告将执行什么；auto=执行。冷启动验证跑通后人工翻 auto——修复动作的授权升级走人，符合底座红线。

### 4.3 诊断执行器 `r3_ops_heal`（三段式，程序抓证据、LLM 开处方、程序抓药）

**A. 证据采集**（按信号类的固定 checklist，纯只读，executor 内联实现）：

| 信号类 | 采集项 |
|---|---|
| job failed | run_log 最近 error 摘要（≤500 字符×3 行）、当日 attempt 历史、job 调度配置（retry_until 等）、**跨任务关联**（同窗口还有哪些 job failed）、RAG 快速探活、飞书连通性（get_tenant_access_token） |
| rag degraded/recovered | 探活错误原文（余额类错误一眼可辨）、持续时长、当日抖动次数 |
| parked effects | 组件名、last_error、park 前尝试次数 |
| dead letter | 条数、样本 record_id、最近一次死信原因 |

**B. LLM 归因**（单次调用，deepseek-flash，`ai_call_audits` scenario=`r3_ops_diagnosis` 留痕计费）：

- 输入：结构化证据 JSON + 信号类；
- 输出契约（JSON Schema 严格校验，解析失败/超时→降级 `unknown` + 纯规则证据直出）：

```json
{
  "root_cause_class": "upstream_outage | quota_exhausted | network | config_error | data_issue | code_bug | unknown",
  "confidence": 0.0,
  "reasoning": "≤120字",
  "cross_signals": ["可选:同根因的其他信号"],
  "prescriptions": [{"action": "<枚举>", "args": {}, "urgency": "now | next_scan | human"}]
}
```

- **LLM 只能从动作枚举里选**，action 之外的任何内容（包括文本）不参与授权——红线⑦在 R3 的具体化。

**C. 处方校验与执行**（程序，LLM 输出永不直接执行）：

逐条处方过四道闸：① `SAFETY_R3_ALLOWED_ACTIONS` 白名单；② repair_mode（L1 类 auto 才执行）；③ 前置条件（如 dead_letter 数>0、真机重算能力已解锁）；④ 日上限（见 §4.4 动作表）。通过则 `enqueue_effect(kind=r3_repair)` 先存后做；不通过降级为卡上「建议」。每事件最多 **2 轮**修复，超限转 `needs_human`。

### 4.4 修复动作白名单（注册制 effect handler）

| action kind | 级 | 语义 | 前置/上限 |
|---|---|---|---|
| `notify_enriched` | L0 | 诊断报告卡（根因+证据+已做/建议） | 总发，不设限 |
| `rag_recheck` | L0 | 立即跑一轮探活刷新证据 | 每诊断轮 1 次 |
| `hazard_dead_letter_rerun` | L1 | 调 `hazard_direct/rerun.py` 核心重灌死信 | **依赖 P3-2 真机 --confirm 验证通过后才进白名单**；日 1 次 ≤50 条 |
| `hazard_stale_rerun` | L1 | C7 stale 标记按需重算 | 同上依赖；日 1 次 ≤50 条 |
| `effects_unpark` | L1 | parked effect 重置为 pending（attempts 清零） | 每组件日 3 次 |
| `job_backfill` | L1 | **漏审日补跑**：按「该日补发窗口已耗尽仍 failed」判定漏审日清单，逐日调该任务的可编程补跑核心（一期唯一 adapter=作业票审核，走 `WorkTicketReviewService` 同 `POST /workticket-review/run` 之核心） | 前置：依赖探测已恢复；**逐日执行、逐日出结果**；每事件 ≤5 日；与当日定时任务错峰（当日窗口未耗尽不补当日） |
| `job_window_extend` | L2 | 延长当日补发窗口（仅卡上建议+一键执行入口，一期不自动） | 人工确认 |
| ~~cursor_reset / 删数据 / 写 Bitable / 重启进程~~ | L3 | **永不注册** | — |

**漏审日判定规则**（job_backfill 的输入，纯程序推导）：`scheduler_job_runs` 中 `fired_date=D` 的行在 D 日补发窗口耗尽后仍 `failed` ⇒ D 为漏审日；当日行还在重试中不计。恢复触发时点的当日漏审需等当日窗口耗尽后下轮扫描补判，避免与正在跑的定时重试撞车。

### 4.5 工单生命周期与收口（阶段机，`derive_stage` 纯函数）

**工单 = 系统事件单，跨天持有**：信号产生即开单，**关闭双条件 = ①信号恢复已验证 ∧ ②关单通知已送达**——修复动作做完但信号未恢复、或恢复通知没发出去，工单一律保持 open。上游断连类工单在依赖探测确认恢复 + 补跑 + 通知完成前永不关闭（11-10 特作平台案例：断连当天告警一次后无人盯恢复，工单制要堵的就是这个洞）。

```
detected → diagnosed → repairing → verify_wait → closed（双条件：恢复验证 ∧ 关单通知）
                 └──────────────────────► needs_human（2轮未收口 / 处方=human / L2建议未决）
                     needs_human ── 依赖恢复/人工处置后 ──► repairing → …（可复活重入收口）
```

- 修复 effect 执行后不主动轮询等待，靠**下一轮扫描/恢复 trigger**（同 thread 订阅直通）回注：`recovered`/`dep_recovered` trigger 到达 → 执行器核对「处方动作已执行 + 信号已清除 + 漏审日已补齐」→ 全绿才 stage=closed 并发收口卡；**收口卡发送失败 ⇒ 工单不置 closed**，下轮重发（双条件的②由机制保证）；
- 跨天漏审补跑链：`dep_recovered` → `job_backfill` 逐日执行、逐日结果入 stage_facts → 全部漏审日有终态（成功/失败）才进收口判定；某日补跑失败重试 1 次，再败升级卡（其余日不受阻）；
- 任务 open 超 24h 未收口 → 底座 Watchdog `blocked` 规则自然兜底 DM。

### 4.6 汇报卡（四形态，全部走 `dm_admin` effect，先存后发）

1. **诊断卡**：事件 / 根因分类+置信度 / 证据摘要 / 已执行（auto）或将执行（observe）/ 建议 / 是否需人；
2. **修复结果卡**（每轮修复结束必发）：`<动作> × N 逐项 ✅成功/❌失败`；失败项带错误原文与下一步（重试/升级）；observe 模式发「将执行」版；
3. **收口卡 🟢**：`<事件> 已自愈：根因=<class>，持续 <时长>，动作 <清单×结果>，补跑 <日期×结果>，验证通过，工单关闭`；
4. **升级卡 🔴**：`自愈未收口：已试 <动作>×<轮>×<结果>，根因判断 <class>，需人工：<具体指引>`——把「人从日志查起」变成「人按指引决策」。

### 4.7 留痕（全时间线落表映射，任何一单可回放）

| 环节 | 落点 |
|---|---|
| 信号（含依赖探测翻转、恢复） | `agent_triggers`（external_id 幂等，payload 带结构化证据快照） |
| 开单与授权 | `agent_tasks`（mandate）+ `agent_decisions`（研判快照） |
| 诊断结论/根因/处方 | `agent_tasks.stage_facts` + `agent_inputs`（每轮证据回注留痕） |
| 修复动作执行与结果 | `agent_effects`（kind=r3_repair；attempts/last_error/status 即修复审计） |
| 每张通知卡 | `agent_effects`（dm_admin）+ `agent_outbox`（会话保序） |
| 补跑逐日结果 | effects payload + `scheduler_task_run_log`（补跑走既有核心时自然留痕） |
| 全时间线回放 | 观测 REST：按工单聚合 trigger→decision→input→effect 时间线（§2.1 第 7 项） |

## 5. 数据模型

**一期零新表**（区别于 R1 的 links 表——R3 无业务映射关系）：全链留痕复用底座 12 表——triggers（信号）/ tasks+stage_facts（诊断结论与阶段）/ inputs / decisions / effects（修复动作与卡片，attempts+last_error 即修复审计）。

一个 alembic 迁移（仿 `a1b3c5d7e9f1`）：seed `agent_sources` 两行（`safety.ops.selfheal` 扫描源 enabled=false；`safety.ops.rag_inject` 直投载体行 enabled=false），`ON CONFLICT DO NOTHING`。

## 6. 配置清单（app_config registry，全热生效除注明）

| 键 | 默认 | 说明 |
|---|---|---|
| `SAFETY_R3_OPS_ENABLED` | false | R3 总闸（+source.enabled 双闸，三层开关链惯例） |
| `SAFETY_R3_SCAN_INTERVAL_SECONDS` | 300 | 扫描周期（restart_required） |
| `SAFETY_R3_DIAG_LLM_ENABLED` | true | false=纯规则降级（证据直出不上 LLM） |
| `SAFETY_R3_REPAIR_MODE` | observe | L1 动作闸：observe/auto |
| `SAFETY_R3_ALLOWED_ACTIONS` | L0 两项 | 白名单 csv，热调 |
| `SAFETY_R3_MAX_REPAIR_ROUNDS` | 2 | 每事件修复轮上限 |
| `SAFETY_R3_DAILY_RERUN_CAP` | 50 | 死信/stale 重灌日上限 |

## 7. 与现有系统的关系（一期红线：告警链零改动）

- 既有告警卡片照发（人继续收，收口卡是增量不是替代）；
- `scheduler_job_runs`/`scheduler_task_run_log`/`agent_effects` 只读；
- `rag_health.py` 仅加直投两行（翻转处），告警逻辑不动；
- 补发窗口/退避/熔断等固定规则自愈**原样保留**——R3 是其上的诊断兜底层，不接管不绕过；
- 失败重试既有语义不变：R3 的 `job_window_extend` 走建议+人工，不自动改窗口。

## 8. 工作样例（验收对照用）

**样例 1：网络瞬断（11-10 作业票场景）**
10:23 作业票失败 3 次卡发出（既有）→ 10:25 扫描产 `ops:job:workticket_audit:2026-11-10:failed` → 自动开单 → 证据：run_log=`httpx ConnectError`、同窗口无其他 job 失败、飞书连通性探测失败 → LLM：`network`/0.85 → 处方 `rag_recheck`(L0)+无 L1 可修（网络非本地可修）→ 诊断卡「等待网络恢复，补发窗口内自动重试中」→ 11:02 网络恢复，10 分钟重试成功 → `recovered` trigger → 收口卡 🟢「已自愈：网络中断 39 分钟，无数据损失」。

**样例 2：余额耗尽（11-04 场景重演）**
embedding 429/1113 → rag_health 翻转直投 `degraded` → 开单 → 证据：错误原文含「余额不足」→ LLM：`quota_exhausted`/0.95 → 处方 urgency=human → **不修，直接升级卡**「需充值智谱账号，充值后探活将自动确认恢复」→ 充值 → `recovered` → 收口卡。

**样例 3：死 letter 积压**
死信 ≥1 → 扫描 trigger → 诊断：AI 分析超时类死信 12 条 → 处方 `hazard_dead_letter_rerun` → repair_mode=auto 时 effect 调 rerun 核心重灌 → 修复结果卡（重灌 12 条 ✅10 ❌2，失败 2 条原因+重试计划）→ 下轮扫描死信清零 → 收口卡 🟢；repair_mode=observe 时卡上「将执行重灌 12 条」+ 一键转正。

**样例 4：上游断连跨天 + 漏审补跑（11-10/11-11 特作平台真实案例，R3 的定型场景）**
11-10 10:23 既有告警卡发出 → 10:25 扫描开单（thread=`ops:job:作业票审核:2026-11-10`）→ 证据：run_log=`平台接口超时 POST http://192.168.5.7:9550/...`、本机网关通/外网通、飞书连通 ✅ → LLM：`upstream_outage`/0.9，从错误原文提取依赖端点 `192.168.5.7:9550` 落 stage_facts → 处方：本地不可修 + urgency=human → 诊断卡「特作平台服务器不可达，需联系平台方/厂区 IT；恢复后将自动补跑漏审日」→ 12:00 窗口耗尽仍 failed（11-09 判定漏审）→ **工单保持 open，不关单** → 此后每轮扫描（5min）探测 9550 → 11-XX 平台恢复 → `dep_recovered` trigger 回注 → 判定漏审日=[11-09, 11-10, …] → `job_backfill` 逐日补跑 → 修复结果卡（11-09 ✅ 复审 N 张 / 11-10 ✅ …）→ 逐日全终态 + 当日定时任务恢复成功 → 收口卡 🟢「已自愈+补跑完成，工单关闭」。对照现状：11-10 告警一次后无人盯恢复、漏审日靠人记着补——R3 把整段变成工单内自动闭环。

## 9. 冒烟验收与停损

1. dev 拔网/错配 token 制造 job 连续失败 → trigger 落库 → observe 全程零 L1 effect 执行 → 卡片正确；
2. 注入死信 → auto 模式重灌 → 修复结果卡（含失败项）→ 清零 → 收口卡；
3. 停 embedding key → 直投 → quota_exhausted 升级卡（不修）→ 恢复 key → 收口；
4. **跨天断连**：模拟上游不可达 → 工单 open 过夜 → 恢复 → dep_recovered → 补跑逐日出结果 → 双条件关单；收口卡发送故意失败一次 → 验证工单不置 closed、下轮重发；
5. 防风暴：同 job 反复失败当日只一单；修复 2 轮未收口转 needs_human；单轮扫描 5 条上限；
6. 停损：`SAFETY_R3_OPS_ENABLED=false` 一键全停，扫描源与执行器全静默，不影响任何既有任务。

## 10. 实施切片

| 切片 | 内容 | 可独立验收 |
|---|---|---|
| S1 | OpsScanSource（含依赖探测）+ rag 直投 + 迁移种子 + bridge 挂载 | triggers 按设计落库（含防风暴、dep_recovered） |
| S2 | 诊断执行器 A/B/C 段 + 四形态卡 + observe 全程跑通 | 样例 1/2 observe 路径 |
| S3 | L1 effect handlers（unpark 即刻；job_backfill 作业票 adapter 即刻；rerun 两项等 P3-2 解锁）+ repair_mode 闸 + 跨天收口 | 样例 3/4 auto 路径 |
| S4 | 观测 REST（含工单时间线回放）+ 全链冒烟 + 冷启动观察 1-2 周 → 人工翻 `repair_mode=auto` | §9 全项 |

依赖声明：`hazard_dead_letter_rerun/hazard_stale_rerun` 依赖 P3-2「真机 --confirm 重算」验证通过（当前白名单仅 L0+unpark，rerun 两项 `SAFETY_R3_ALLOWED_ACTIONS` 里不预置）。

## 11. 注册点清单（对照底座接入范式，9 点）

1. Source：`modules/safety/service/ops_selfheal_r3/scan_source.py`（+ rag 直投挂点在 `rag_health.py` 翻转处）；
2. 种子迁移：alembic `ON CONFLICT DO NOTHING` 两行 source；
3. rule + Policy 组合播种：追加 `ensure_guardian_r2_policy()` rules 列表（会合点坑）；
4. 执行器：`ops_selfheal_r3/executor.py`，bridge `register_executor()`；
5. 外发：复用 `feishu_dm_card`/`feishu_card` sender；
6. 修复 effect：`register_effect_handler('r3_repair', …)`；
7. 配置键：`app_config/registry.py` §6 七键；
8. 观测 REST：`api/ops_selfheal.py` 挂 `api/__init__.py`；
9. `main.py` 不动（bootstrap 内含）。

## 12. 拍板点

| # | 问题 | 推荐 |
|---|---|---|
| 1 | 研判层播种即 auto（开单+诊断自动跑），修复层 observe 起步 | **是**——不开 auto 则回到人转正才诊断的旧循环 |
| 2 | L1 一期动作集：`effects_unpark` + `job_backfill`（作业票 adapter）即刻，rerun 两项等 P3-2 | **是** |
| 3 | `job_window_extend` 只建议不执行（补发窗口语义敏感） | **是** |
| 4 | 死信/stale 重灌日上限 50 条、日 1 次；补跑每事件 ≤5 漏审日 | **是** |
| 5 | 冷启动观察期 1-2 周后人工翻 repair_mode=auto | **是** |
| 6 | 关单双条件（恢复验证 ∧ 通知送达）+ 修复结果卡每轮必发（含失败项） | **是**（2026-11-11 用户要求，已并入 §4.5/§4.6） |
| 7 | 工单跨天持有：上游断连类永不因「动作做完」关单，依赖探测恢复才进收口 | **是**（同上，样例 4 为定型场景） |

## 13. 风险与坑清单（实现期对照）

- **LLM 幻觉处方**：枚举白名单 + 四道闸程序校验兜底，解析失败降级 unknown 纯规则直出；
- **修复风暴**：每事件 2 轮 × 每动作日上限 × repair_mode 闸三层叠加；自愈自身故障走 effects 健康告警既有通道，不自我修复；
- **policy 会合点**：新 rule 必须 append 组合列表，单播子集挤掉 R1/R2/HW（既知坑）；
- **诊断计费**：仅新事件触发 LLM（trigger 幂等保证），扫描轮零 LLM 调用；
- **同机局限**：宿主机断网 Agent 同盲——收口靠恢复后补做，卡片时序可能滞后，卡片里写「事件时间」非「发现时间」防误读；
- **Redis 依赖**：死信计数 fail-open，Redis 不可达只跳过该项不产故障信号；
- **补跑与定时重试撞车**：漏审日判定只认「窗口已耗尽仍 failed」，当日行重试中不计（§4.4 判定规则），恢复恰逢当日任务运行期也不并发补当日；
- **既有缺陷顺带暴露**（独立修复，不属 R3 范围）：11-10 实证重试窗口漂移（12:00 截止实际跑到 12:57）——R3 扫描天然能暴露此类异常，修复归 scheduler 域；
- **测试真写库**：effects/policy 断言须用事务回滚隔离（R1 六件套 `test_r1_fire_chain_db.py` 范式）。
