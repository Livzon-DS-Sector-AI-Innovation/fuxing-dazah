# 安全 Agent 验收问题修复计划

依据：`docs/agent-acceptance-20261029/report.md`（2026-10-29 全能力实测，47 用例 11 缺陷）。
本文逐项给出**代码级根因（已侦查核实到 file:line）→ 修复方案 → 验收口径 → 风险**，最后给批次排序、拍板点与回归清单。本计划只读不改，动工须另开实施窗口。

---

## P0-1 web 链路 role=None 无 viewer 兜底

**根因**（已核实）：
- 飞书链路有兜底：`feishu/business_agent_bot_handler.py:601,607` — `role = "viewer"` 默认 + `get_user_role(...) or "viewer"`。
- web 链路无兜底：`api/business_agent.py:119-124 _build_deps` — `role = await get_user_role(db, feishu_user_id)` 无 `or "viewer"`；未绑定 → None → `core/permissions.py:443 allowed_tools(None)` 返回空集 → 全拒（含查询）。

**修复**：`_build_deps` 中 `role = await get_user_role(db, feishu_user_id) or "viewer"`，仅当 `feishu_user_id` 非空（即已登录）时兜 viewer；**匿名（无 cookie）保持全拒**（web 无飞书租户边界，匿名给只读等于内网裸奔数据面）。
**验收**：未绑定登录身份问「灭火器什么时候到期」正常返回（viewer 55 工具口径）；匿名直调 API 仍 403/全拒；C3/C1v 回归变绿。
**风险**：低。注意 `confirm_action` 端点同用 `_build_deps`，行为同步变化（未绑定时取消卡从「权限不足」变正常拒绝路径），需回归确认卡取消。
**估时**：0.5h 代码 + 回归。

## P0-2 主模型 LLM 调用间歇挂死、无超时（挂死率 5/30≈17%）

**根因**（已核实）：
- `business_agent/agent.py:118` `DeepSeekProvider(api_key=...)` 未传 `http_client` → 走 openai SDK 默认超时 **600s**（`openai/_constants.py:9 DEFAULT_TIMEOUT=Timeout(600, connect=5)`）——单次调用最长挂 10 分钟。
- `agent.py:110` 注释自认「base_url/timeout 字段暂不消费」：ai_config registry 里 `timeout: 120` 默认值（`ai_config/registry.py:59,82`）**从未传到 provider**。
- executor `run_turn`/`resume` 的 `_agent_run` 无整体看门狗；工具调用层（`core/pipeline.py execute_tool`）也无超时。
- 前端：SSE error 事件仅在服务端抛异常时下发（挂死=不抛）；「停止」按钮纯前端（`AgentChat.tsx /stop` 只置 cancelledRef），服务端轮次继续。

**修复**（三层）：
1. **Provider 超时**：`_build_agent` 构造 `httpx.AsyncClient(timeout=httpx.Timeout(float(cfg.timeout or 120), connect=5))` 传入 `DeepSeekProvider(api_key=..., http_client=...)`；`AgentRuntimeConfig` 增加 `timeout` 字段并从 ai_config 读（registry 默认 120s 已存在，纯接线）。配置指纹并入 timeout。
2. **轮次看门狗**：`executor.py` 两处 `_agent_run(...)` 外包 `asyncio.wait_for(..., timeout=超时+30s)`；超时走既有 failed 审计 + 返回友好话术（复用 `executor.py:173` 的 err_msg 路径）→ SSE 会下发 error 事件，前端不再永远转圈。工具层 `pipeline.execute_tool` 同样包 `asyncio.wait_for`（默认 120s，写工具可放宽）——顺带兜住 #6 的慢工具。
3. **前端止损**（可选加固）：`AgentChat.tsx` fetch 加 `AbortController`，前端计时（如 150s）主动 abort 并渲染「请求超时，请重试」；「停止」语义文案改为「停止显示（后台可能仍在处理）」。

**验收**：复跑 A05/A10/A29/A13/A15 五问法——每轮必在 timeout+30s 内终态（答案或超时话术），ai_call_audits 出现 failed(timeout) 行；前端不再无限 loading；正常 10s 用例时延无回归。
**风险**：中。120s 需覆盖最大合法轮（A04 曾 29s；大扇出可能 60-90s）——建议 120s 起步观察审计分位再调；重试不加（写工具已过确认门，但重试放大扇出，先只做超时+降话术）。
**估时**：0.5-1d 含回归。

## P0-3 push_report_to_chat 显式 chat_id 被「安全速递总卡」吞掉

**根因**（已核实，两支吞、一支不吞）：
- supervision：`service/hazard_direct/bulletin.py:415-426 deliver_bulletin` — `digest_enabled()` 为真时**无视 chat_id 直接投总卡格子**，仅 digest 关闭才 `send_group_card(chat_id=...)`。
- alarm：`service/central_alarm/service.py:505-510 generate_daily_report` — 同构：digest 开启走 `_upsert_digest_cell`，显式 chat_id 被忽略（fire_alarm/service.py 同族需同查）。
- daily_op：`service/special_operation_daily_report.py:2009` — `target_list = target_chats if ... else [DAILY_REPORT_CHAT_ID]`，**尊重显式目标**（无需修）。

**修复**：两个 deliver 分支改为「**显式 chat_id 优先直发**」：`if chat_id: send_group_card(chat_id=...)`（跳过总卡）；无 chat_id 才走 digest 常态。语义 = 用户点名群就只发点名的群，不双写总卡（值守轮询比对逻辑不受影响——轮询调用不带 chat_id）。
**验收**：白名单测试群 oc_726a990558082daafa08acd2452099dd 重做 B05c 真确认：测试群收到卡片、速递总卡**无**当日新格子/内容不变；定时链路（无 chat_id）行为逐字节不变。
**风险**：低-中。需确认总卡值守轮询（周四比对）与手动推送互不踩踏；fire_alarm service 同步排查。
**估时**：0.5-1d。

## P1-4 query_oh_exams / query_oh_persons `AttributeError: exam_no`

**根因**（已核实）：直读模式 `oh_direct/ledger.py:27 OhRowView.__getattr__` 对 mapped 缺键抛 AttributeError（设计给 Pydantic from_attributes 兜默认值用）；`oh_bitable_handler.py:381-383 map_exam_registry_fields` 仅当 Bitable「体检号」非空才写 `mapped["exam_no"]` → 无体检号的行缺键 → 工具层 `business_agent/tools/read_tools.py:981 e.exam_no`（及 persons 工具的 employee_no 等）直接崩。API 端点走 Pydantic schema 所以从未暴露。

**修复**：read_tools 两个工具的行序列化改 `e.mapped.get("exam_no")` 式取值（或给 OhRowView 加 `get(field, default)` 助手统一用）；顺带核对两个工具全部字段对 mapped 键的覆盖。
**验收**：A26 问法返回体检批次统计/人员台账（或如实 0 条），审计不再 failed；用带体检号与不带体检号的行各验一次。
**风险**：极低。
**估时**：0.5h。

## P1-5 「推送日报/处置报警」路由误配到 generate_alarm_report

**根因**（已核实，模型语义选择问题而非规则层漏词）：B05a「推送…到群」同时挂载 hazard(alarm 域含 push 工具 via tool_selector.py:31,175)与 alarm 域；B07「处置中控报警」同时挂 alarm+telemetry（"处置"词 tool_selector.py:255）。两例都是模型在**多域工具齐备时选错**：generate_alarm_report 的 docstring（"生成并推送日报"）对这两类意图比 push_report_to_chat / 澄清更"像"。

**修复**：
1. 工具描述消歧（主修）：`generate_alarm_report` docstring 首行加「仅用于生成/投递**报警日报卡片**；用户要求『推送到指定群/发到某群』时必须改用 push_report_to_chat(chat_id=…)；『处置/销警/确认报警』与本工具无关，遥测报警用 resolve_telemetry_alarm/ack_telemetry_alarm，中控群消息报警无处置工具时应先澄清」。
2. `push_report_to_chat` docstring 强化「用户显式给出群名/chat_id 时必选本工具」。
3. agent.md 增一条行为准则「意图无对应工具时先澄清，不用近似写工具替代」——注意 agent.md 已 8136B 近 8KB 红线，需同步压缩它处一行。
**验收**：B05a 一轮即出 push_report_to_chat 卡（chat_id 入卡）；B07 首轮要么出 resolve/ack 卡要么出澄清问题，不再出 generate_alarm_report；generate_alarm_report 正常问法（"生成今天的中控报警日报"）不受影响。
**风险**：低。描述改动会全角色生效，回归 alarm 域正常问法 3 条。
**估时**：0.5d。

## P1-6 query_overview 交互聚合 >4min 无产出

**根因**（已核实）：`service/overview.py:553 build_overview` 15 个采集器 `asyncio.gather` 并行、单域异常可降级（`_run` 已有 try/except），但**无单域超时**——慢域（隐患直读全量 2402 条/5 页，实测单拉取 4 分钟）拖死整轮；工具层亦无超时（与 #2 工具层同点）。

**修复**：`_run` 内 `asyncio.wait_for(fn(), timeout=30)`，超时按既有降级路径记 errors（框架现成，只包一层）；叠加 #2 的 execute_tool 超时（120s）双保险；可选：重域直读缓存 TTL 由 60s 提到 300s（驾驶舱与 agent 共享预热）。
**验收**：A09 问法 ≤60s 出总览（个别域降级为 error 注记属正常）；驾驶舱页面无回归。
**风险**：低。注意 collectors 里 DB 采集器共用 session 的约束（overview.py:539 注释）——wait_for 取消时不留半途 session 状态，超时后该 session 不可复用，需走降级而非继续。
**估时**：0.5d。

## P1-7 写确认两套模式并存 + 裸「确认」路由脱轨

**根因**（已核实）：
- 裸「确认」零关键词 → `tool_selector.py:296 route_message` 规则层 miss → 嵌入层对两字噪声分类到 facilities 域 → 只挂 4+1 工具；叠加跨会话记忆注入（B06 旧数字）→ 意图脱轨（B08b）。
- 文本征集确认 vs 系统卡：模型行为不稳定（B02 复述短语后出卡、B06/B08 首轮纯文本征集），无 prompt 约束。

**修复**：
1. **粘性路由**：`executor.py:142` 路由决策处，消息为纯肯定/否定短词（确认|好的|是的|取消|不用|继续…白名单）且会话历史存在上一轮用户消息时，**沿用上一轮的挂载工具集**（上一轮 domains 可从 ai_call_audits.extra.routing 或 session 事件流取），避免重新嵌入分类。
2. **确认交互统一**：agent.md 加一条「凡预判需要用户确认的写操作，直接发起工具调用触发系统确认卡，不要用文本征求确认」（同样受 8KB 约束需对冲压缩）。
3. 前端可选：pendingAction 存在时输入框 placeholder 提示「有待确认操作，先处理上方卡片」。
**验收**：B08 首轮直接出 submit_hazard_identification 卡；裸「确认」能命中上一轮提议的写工具并出卡；B06 出 send_hazard_supervision_bulletin 系统卡；B02 既有流程不回归。
**风险**：中。粘性路由需防「上一轮无工具」与多轮后语境漂移；建议白名单词表从严。
**估时**：1d。

## P1-8 确认卡未处理时发新消息 → UserError 会话报废

**根因**（已核实，触发条件修正）：**不是取消路径**（取消后追问已验证正常），而是**新用户消息到达时会话历史里仍有未回包的写 ToolCall**（pending 卡未点按钮）→ pydantic-ai `UserError: Cannot provide a new user prompt when the message history contains unprocessed tool calls`（B05d 首试实证）。当前唯一出路 /new。

**修复**：`api/business_agent.py _execute_turn_and_persist`（或 executor.run_turn 入口）在跑新轮前用现成 `_find_deferred_in_history(history)` 探测：命中则**不进模型**，直接返回话术「您有一项写操作待确认（见上方卡片），请先点击【确认执行】或【取消】再继续提问」，session 不落死。可选加固：resume 已有流程不动，仅挡新消息。
**验收**：复现 B05d 序列（出卡→不点→发新消息）得到友好提示而非 UserError；点掉卡后新消息恢复正常；取消后追问（B05b→c）不回归。
**风险**：低。
**估时**：0.5h。

## P2-9 /new 只清会话、跨会话记忆仍回放

**根因**（设计行为）：记忆提取（`executor.py:1306` saved N facts）每轮落 `safety.agent_memories`，新会话注入（`core/memory.py` 每轮 ≤5 条）——D1 暗号回放、B08b 串扰皆由此。**无用户级开关/清除入口**。

**修复**（建议三件套，可分期）：
1. `/forget` 快捷指令：删除当前用户全部记忆（agent_memories delete by user）+ 回复确认——前端 AgentChat executeCommand 加分支 + 后端小端点。
2. 确认卡/敏感场景话术提示「对话内容可能进入长期记忆」或记忆注入加来源标签已有（agent 坦承过），补 /help 文案。
3. 可选：记忆提取侧加敏感词跳过（身份证/电话/暗号类 pattern 不入库）。
**验收**：D1 序列 /new → 问暗号不知 → 告知暗号 → /forget → /new → 再问不知。
**风险**：低。/forget 是删除操作，需二次确认文案。
**估时**：1d（含前端）。

## P2-10 RAG 引用呈现双缺陷

**根因**（部分核实）：
- A19 sources 空：`executor.py:1001 _extract_knowledge_sources` 依赖 `part.structured_content()` 解析出 `sources` 键，A19 轮 knowledge_search 调了 2 次但最终 sources=None——推断该轮返回 payload 无 sources 键或 structured_content 解析失败被静默 continue（需一次复现定论）。
- B06 原始 HTML 倒灌：knowledge_search 返回的来源 snippet 含整段文档 HTML（数据交换规范的表格），前端 renderSources 原样展示（React 转义了，无 XSS，纯观感问题）；且该轮检索串台（督办通报场景检索到无关规范文档）。

**修复**：
1. 提取健壮化：structured_content 失败时回退解析 `part.content` JSON；sources 为空时打 debug 日志（便于定位 RAG 侧）。
2. snippet 清洗：knowledge_search 返回前 strip HTML 标签 + 截断 ~120 字（后端做，前端免改）；或前端 renderSources 渲染前清洗。
3. 检索串台：观察项——知识库对「督办通报」类业务词的召回混入平台对接文档，可在 ragplus 侧调参或给 knowledge_search 加业务域过滤，暂不阻塞。
**验收**：A19 出「引用来源（N）」区块且链接可达；B06 类问题不再出现整段 HTML。
**估时**：0.5d。

## P2-11 仓储库存工具单次仅返 10 条、无聚合

**根因**（已核实）：`tools/warehouse_query_tools.py query_stock` 透传 `warehouse_query.query_stock`，无 summary 参数、底层固定小页返回；「库存还有多少」类总量问题无法回答（agent 只能诚实说不能汇总）。

**修复**：query_stock 加 `summary: bool = False` 参数——true 时底层按 物料×单位 聚合返回总量行数+条数（SQL/直读聚合均可），answer 路径让模型在用户问"总量/还有多少"时置 true。
**验收**：A14 问法返回全仓总量概览（物料数、批次 1500、按单位分列），明细仍可keyword查。
**估时**：0.5d。

---

## 数据质量注记处置（业务动作，非代码）

| 项 | 建议动作 | 责任侧 |
|---|---|---|
| 锅炉遥测 0 条 | 按设施二期遗留：拿到锅炉群 chat_id+消息样例后开采集 | 业务+运维 |
| OH 监测台账 0 条 | 检测机构报告出来后按 A11 建议字段补录 | 业务 |
| 培训计划 1 条未开始 | 安排 2026 培训计划与岗前三级教育学时登记 | 业务 |
| 违章档案 42 条无人员 | 三违回流时把违章人/定性字段补全（回流映射改造或人工补录） | 业务+小改造 |
| MSDS 乙醇重复 2 条 | 去重保留 1 条 | 业务 |
| 平台报备单 0 条 | 报备流上线推广或明确以多维表格为准（口径拍板） | 拍板 |
| 外来人员保险覆盖 12% | 推进 81% 未填报备补保险有效期（既有预警已上线） | 业务 |
| 特种设备/安全附件未接入 | 补两表 Bitable 接入（设施模块既有缺口） | 运维 |
| 辨识草稿积压 323 条 | 推动各部门提交进 AI 流转（creator 可批量触发） | 业务 |

## 环境注记处置
- IAB webview 重载后 ~1min 事件不可达：不动产品代码；自动化验收脚本沿用「页内 JS .click()」配方（已写入本验收方法学）；真实用户不受影响。

## 需用户拍板的决策点
1. **#1 匿名 web**：建议「登录未绑定→viewer，匿名→全拒」（本计划口径）；若内网信任域足够也可匿名 viewer，风险自担。
2. **#3 显式群与总卡关系**：建议「点名群只发点名群，不双写总卡」。
3. **#2 超时值**：单次 LLM 120s / 轮次 150s / 工具 120s / overview 单域 30s 起步，按审计分位调整。
4. **#9 记忆**：默认保留 + /forget（本计划口径）；或默认关闭记忆注入待合规确认后开。

## 批次与排序

| 批次 | 内容 | 预计 |
|---|---|---|
| ①稳定性 | #2（超时三层）+ #6（采集器超时）+ #8（pending 守门） | 2d |
| ②权限面 | #1（viewer 兜底，含匿名口径拍板） | 0.5d |
| ③推送正确性 | #3（chat_id 直发）+ #5（描述消歧+prompt 约束） | 1-1.5d |
| ④数据正确性 | #4（OH 工具取值） | 0.5d |
| ⑤体验 | #7（粘性路由+确认统一）→ #10（引用清洗）→ #9（/forget）→ #11（库存聚合） | 2.5-3d |

## 统一回归清单（修完按此复测，对照验收基线）
A05/A09/A10/A13/A15/A29（挂死六问法必出终态）· B05c（白名单真确认直发测试群）· B07（处置误配）· B08+b/B08b（裸确认与文本确认）· B05d 序列（pending 守门）· C3/C1v（viewer 兜底转绿）· A26（OH 工具）· A19/B06（引用呈现）· D1（/new+/forget）· A14（库存总量）· B01-B03/B09（确认卡主流程防回归）· 定时链路（日报/督办/总卡值守）逐字节比对。

---

*侦查与计划：ZCode，2026-10-29。所有 file:line 均已在当前工作区核实；实施窗口需另开，动代码前按批次逐项过拍板点。*
