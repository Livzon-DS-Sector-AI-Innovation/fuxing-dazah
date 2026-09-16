# Spec：仓储 V2.0 分期B「智能上线」（两阶段）

> 来源：`docs/仓储V2.0设计方案.md` Phase B + 本质询确认（2026-09-16）。
> 分支：feature/warehouse-module；功能目录：.scratch/warehouse-v2-phase-b/
> 前置：分期A 已交付并真机验收（commits 3690054 / 0831a2b / 3517bf1）。

## 需求质询记录（两轮，均按推荐项执行并在此留档）

1. 阶段切分 = **先规则后智能**：阶段一智能中心（规则引擎为主）；阶段二 AI 助手 Web 化 + 快速登记
2. AI 助手深度 = **完整体验**（SSE 流式 + 确认卡 + 卡片化回复，对标宁夏 Livzon 助手）
3. 快速登记入口 = **独立页面**（复用 V1.0 识别 pipeline，不并入助手对话）
4. 补货建议 = **不联动采购模块**（仅展示 + 状态管理，跨模块联动留待后续）
5. 流程范围 = 一次流程覆盖两阶段（沿用分期A 模式）；每阶段末审查 + 提交
6. 测试接缝 = 沿用分期A 已确认模式（后端路由层 AsyncClient + 前端 vitest 组件层）
7. LLM 供给 = 复用 ai_config 体系（AiModelProfile agent / AiScenarioConfig 场景熔断 / ai_call_audits 审计），所有 AI 输出走白名单校验 + 规则文案降级，测试不依赖真实 LLM

## Problem Statement

分期A 让仓库"看得清、管得住"，但仓储管理仍是被动式的：异常（低库存、呆滞、临期）要靠人去发现，补货凭经验，预警阈值硬编码在驾驶舱逻辑里无法调整；AI 能力（对话助手、单据识别）只存在于飞书侧，Web 端用户（仓管员日常主战场）完全用不到。V1.0 的 agent 子系统（Runner/工具/HITL 确认门/识别 pipeline/技能）已验证但被锁死在飞书 IM 入口上。

## Solution

分两阶段交付"智能上线"：

**阶段一（智能中心）**：新增智能中心一级菜单，含三个页面——①异常检测：规则引擎扫描（低于安全库存/零库存/负库存/呆滞 90 天无入库/效期临期 30 天）生成异常记录，每类异常顶部 LLM 解读条（白名单校验+降级），异常可标记已处理；②补货建议：基于近 30 天出库消耗速率 + 安全库存 + 可支撑天数计算建议采购量，建议可"已处理/忽略"；③效期与呆滞：临期批次倒计时列表与呆滞物料排行（复用分期A 呆滞口径）。预警阈值（安全库存天数、呆滞天数、临期天数）可在配置页调整，扫描任务定时执行。

**阶段二（AI 上线）**：①AI 助手 Web 化——agent 网关新增 HTTP/SSE 入口（复用 Runner、工具、HITL 确认门、技能、记忆），仓储页右下角悬浮助手：流式输出、写操作确认卡（风险分级/有效期/回读验证）、Markdown 表格卡片化；②快速登记页——上传单据图片 → 复用识别 pipeline（recognizer→aligner→draft）→ 草稿确认页（低置信度标黄）→ 提交。

## User Stories

阶段一 · 智能中心

1. As a 仓库管理员, I want 打开"智能中心-异常检测"看到按类型分组的全部异常, so that 不用翻多个页面就知道哪里有问题
2. As a 仓库管理员, I want 异常列表按 低库存/零库存/呆滞/临期 分 Tab 展示且每条可标记已处理, so that 处理进度可追踪
3. As a 仓库管理员, I want 每类异常顶部有一句 AI 解读, so that 快速理解异常的严重程度和原因
4. As a 仓库管理员, I want AI 解读不可用时看到规则文案降级而非报错, so that 功能永远可用
5. As a 仓库管理员, I want 定时扫描自动生成异常记录, so that 第二天来就能看到昨夜新产生的异常
6. As a 仓库管理员, I want 在配置页调整 呆滞天数/临期天数/安全库存覆盖天数 等阈值, so that 预警口径贴合本厂实际
7. As a 仓库管理员, I want 阈值变更留审计（操作人/前后值）, so that 口径变化可追溯
8. As a 仓库管理员, I want 补货建议页看到 每个物料的日均消耗/可支撑天数/建议采购量, so that 补货有依据
9. As a 仓库管理员, I want 对补货建议标记 已处理/忽略, so that 建议列表保持干净
10. As a 仓库管理员, I want 效期与呆滞页看到 30 天内临期批次倒计时与呆滞排行, so that 提前处置
11. As a 系统, I want 异常扫描任务每日定时执行且可手动触发, so that 数据及时且可补跑

阶段二 · AI 助手与快速登记

12. As a 仓库管理员, I want 在仓储页面右下角打开 AI 助手对话窗, so that 随时用自然语言查库存/查异常
13. As a 仓库管理员, I want 助手回复流式输出并显示"正在调用 xxx"阶段标签, so that 等待时可感知进度
14. As a 仓库管理员, I want 助手的写操作弹出确认卡（风险分级/有效期）, so that 高危操作不误触
15. As a 仓库管理员, I want 确认执行后系统回读验证, so that 不会被"假完成"误导重复操作
16. As a 仓库管理员, I want 助手回复中的表格渲染为卡片, so that 结果一目了然
17. As a 仓库管理员, I want 上传单据图片到快速登记页, so that 不开飞书也能录入
18. As a 仓库管理员, I want 识别结果草稿页左图右表、低置信度标黄, so that 核对高效
19. As a 仓库管理员, I want 确认草稿后提交, so that 完成登记且飞书 Bitable 同步写入
20. As a 系统, I want Web 端助手调用与飞书侧共用同一套审计/场景熔断/确认门, so that 治理标准一致

## Implementation Decisions

- **模块边界**：全部改动限于 warehouse 模块 + 前端 warehouse 组件/页面 + 菜单；平台层仅注册定时任务（既有 scheduler 模式）
- **阶段一 schema（唯一）**：三张新表——`alert_rules`（rule_key 唯一/threshold JSONB/enabled/note + 审计表 `alert_rule_audits`）、`alert_records`（rule_key/level: warning|critical/status: open|resolved/material/location 冗余/detail JSONB/resolved_by/resolved_at）、`replenishment_suggestions`（material 冗余/avg_daily_outbound/days_cover/suggested_qty/status: pending|handled|ignored/handled_by）。均沿用 BaseModel 惯例与部分唯一索引模式（无重复唯一键的表用普通索引）
- **规则引擎**：`warehouse/intelligence.py`（纯函数规则集 + 扫描编排）：低库存（total < safety）、零库存（total=0 且有物料）、呆滞（复用分期A 口径，阈值读 alert_rules）、临期（expiry within N 天）。扫描产出 upsert 到 alert_records（同 key 同 material 幂等覆盖，已 resolved 的不复活）；手动触发端点复用同一编排
- **补货建议计算**：近 30 天 outbound movements 按物料求和 → 日均消耗；days_cover = 当前库存/日均；suggested_qty = max(0, 日均 × 覆盖天数阈值(默认 14, 可配) − 当前库存 − 在途? 无在途概念按 0)；日均消耗为 0 且有库存 → 呆滞不生成建议。任务每日随扫描一起刷新建议
- **AI 解读**：`llm_client`（ai_config 场景 `warehouse_anomaly_summary`，缺省回落 agent profile）传入规则统计事实，输出白名单校验（长度截断/敏感词拦除）失败或异常时用规则模板文案。场景 key 在 ai_config scenario_registry 注册，DB 播种由既有迁移模式承担
- **预警规则配置页**：挂在智能中心内 Tab（复用 system-config 的 store/审计模式，语义对齐 runtime_configs）
- **权限**：新增 warehouse:intelligence:read / warehouse:intelligence:update（异常处理与阈值调整）/ warehouse:replenishment:read / warehouse:replenishment:update；助手与快速登记复用既有 movement/material 权限 + agent 会话身份（登录用户）
- **阶段二 agent 网关**：`warehouse/agent/web_gateway.py` 新增 `POST /api/v1/warehouse/agent/chat/stream`（SSE）——入参 {message, session_id?}，身份取登录用户（RequireUser），subject 映射 tenant/user；内部复用 Runner 与 confirm 门（确认执行复用既有 confirm 接口）；SSE 事件对齐宁夏范式：stage/delta/tool_call/confirmation/finished/error，心跳与 sequence；飞书入口不动，双入口共享审计与会话
- **悬浮助手**：`components/warehouse/AgentAssistant.tsx` 挂仓储模块 layout（仅 /warehouse 路由组），fetch POST + ReadReader 解析 SSE；确认卡组件含风险 Tag/有效期/确认与取消
- **快速登记**：`POST /warehouse/agent/uploads`（图片上传，存 uploads/MinIO，返回引用）→ `POST /warehouse/agent/recognition`（调既有 pipeline recognizer+aligner 建 draft，status aligned）→ 草稿确认页读 draft（左图右表）→ 提交复用既有 submit 流程
- **schema 变更（阶段二）**：无新表；WarehouseAgentDraft 增加 `source: 'feishu'|'web'` 可空列（默认 feishu）以区分来源（Alembic 迁移）
- **浏览器兼容**：SSE 使用 fetch 流读取（与分期A 验收的宁夏范式一致），不做 EventSource（需 GET + 无法带 Header）

## Testing Decisions

- 接缝沿用分期A：后端 `tests/warehouse/`（conftest auth_client + AsyncClient 真实路由）；前端 vitest + testing-library（mock lib/api 与 actions）
- 规则引擎测试：纯函数 + 路由层（造数→扫描→断言 alert_records 与分类）；AI 解读测试用假 llm（monkeypatch chat 函数）断言降级路径，不依赖真实 LLM
- 补货建议测试：固定 movements 造数 → 断言日均/可支撑天数/建议量与状态流转
- 助手 SSE 测试：路由层断言事件序列（stage/delta/finished）与鉴权；写确认流程复用既有 confirm 测试模式
- 验收口径：mypy/ruff 对照基线零新增；pytest 走 .venv

## Out of Scope

- 采购模块自动联动（补货建议仅状态管理）
- 每日晨报、同步对账中心、报表中心、NL 导出（分期C）
- 助手长期记忆 Web 管理界面（/memory 治理留后）
- 助手多轮会话历史管理 UI（仅保留 session_id 续聊）
- 移动端适配、PDA、图片拍照直摄（仅文件上传）
- 库位地图、库存状态列（分期A 遗留决策点，仍挂起）

## Further Notes

- 环境约束沿用 CLAUDE.local.md：uv 不可用用 .venv；mypy junit 落盘；命令禁反引号
- React Compiler 已在分期A 验收中关闭（3517bf1），本分期新组件沿用普通写法
- 每阶段末审查 + 提交一次；schema 变更集中在阶段一首个迁移，阶段二仅 one-column 迁移
