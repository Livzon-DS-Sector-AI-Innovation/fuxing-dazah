# DESIGN-安全业务Agent优化-减法优先-20261016

> 目标：对齐仓储 agent 的体感（回复快、执行准），核心手段是**做减法**——工具面从 76 个砍到常驻 ~38 个，砍掉每轮 3 万+ tokens 的固定开销。
> 范围：`backend/app/modules/safety/business_agent/` 内部改造，不碰平台层、不动写确认门与权限体系。

## 一、实测基线（2026-10-16，本机 mock transport 捕获 pydantic-ai 真实请求体）

| 指标 | 安全 business_agent | 仓储 agent | 差距 |
|---|---|---|---|
| 注册工具数 | **76**（44 读 + 32 写） | 18 | 4.2x |
| 工具 schema 总量 | **88.7KB ≈ 31,700 tokens** | ~3,500 tokens | 9x |
| 采样参数 | temp 0.3 / max_tokens 2048 | temp 0.1 / max_tokens 16384 | — |
| 系统提示词 | agent.md 26.7KB 全文每轮注入 | 组装式，历史按轮裁剪 | — |
| 工具结果 | 无截断 | 每条 4KB 截断 | — |
| 长对话压缩 | >24k token 内联 AI 摘要（偶发多一整轮延迟） | 无此机制 | — |

测量脚本：`backend/scripts/tmp/measure_tool_schema.py`（mock httpx transport 拦截 `chat/completions` 请求体）。

**关键发现：**
1. `tool_selector.py:4` 注释写着"18 个工具、~3,500 tokens 固定开销"——早已过时，实际是 76 个、31.7k tokens，膨胀 9 倍。
2. 意图命中时子集只占全量 6-9%（实测"未整改隐患"→7 工具 2,950 tokens），**说明路由方向正确，问题在漏匹配时回退全量**。
3. 最大单工具 `query_special_op_records` 2.8KB（参数过多）、`preview_guardian_subsidy` 2.7KB。
4. 本地开发库 agent_chat 仅 4 次调用记录，**无可用使用频率数据**——减法需生产审计数据兜底（见 P1 步骤 0）。
5. 两个"最新法规"工具职责重叠且名字近乎相同：`query_latest_regulations`（爬取视角）vs `query_regulation_latest`（收录管线视角）。

## 二、76 个工具盘点与处置建议

### M 类：管理/调试工具（5 个）→ 建议删除
| 工具 | 理由 |
|---|---|
| query_ai_audits | Web 后台 AI 审计页已有 |
| query_ai_config | 系统配置页已有 |
| query_bitable_config | 系统配置页已有 |
| query_scheduler_tasks | 任务运行中心已有 |
| query_regulation_crawl_status | 知识库采集监控 Tab 已有 |

这些是开发调试期顺手加的，目标用户（安全员/部门负责人）不会在飞书对话里查配置。**先查生产 90 天审计，确无调用再删**；若 admin 角色确有需求，二期收进"admin 域"按需挂载。

### C 类：同域合并（17 个 → 6 个，净减 11）
| 现状 | 合并后 |
|---|---|
| query_latest_regulations + query_regulation_latest | query_latest_regulations（收录/爬取视角合一，`view` 参数区分） |
| query_oh_* 7 个读（persons/exams/positions/hazard_factors/followups/applications/hazard_enums） | query_oh(entity=...) 1 个（人员/体检高频可保留独立 2 个） |
| query_msds_documents + query_msds_collections | query_msds 1 个 |
| query_drill_plans + query_drill_records | query_drills(kind=...) 1 个 |
| generate_fire_alarm_daily_report + generate_fire_alarm_monthly_report + generate_central_alarm_daily_report | generate_alarm_report(scope=fire\|central, period=daily\|monthly) 1 个 |

合并对 token 的节省不是线性（单工具参数变多），真正收益是**模型选择面减半** + agent.md 引导文案减半 + 维护面收敛。

### D 类：整域拆出常驻（URS 9 个）
query_urs_records、query_urs_review_detail、create_urs_review、parse_urs_document、run_urs_assessment、update_urs_item、confirm_urs_assessment、submit_urs_appeal、generate_urs_report_pdf——本质是多步表单工作流，不适合聊天界面挂 9 个工具。**intent 命中 urs 时才挂载**，不删功能。

### E 类：办公域（14 个）→ 常驻 10 个 + 按需 4 个
- 常驻读 5：office_search_files/read_docx/read_sheet/read_base/read_drive_file（通用高频能力）
- 常驻写 5：office_create_docx/create_sheet/write_sheet/generate_docx_pdf/upload_file
- 按需写 4：office_create_base、office_create_slides、office_set_permission、rollback_office_file

### A/B/F~L 类：保留（核心业务域，共 ~35 个）
隐患 4（query_hazards/hazard_stats/hazard_identifications/generate_supervision_bulletin）、知识 3（knowledge_search/web_search/合并后法规查询）、职健写 5、消防中控读 2、演练生成 2、特作 3（query_special_op_records 需精简参数 schema）、化学品 2、证照 2、相关方/EHS/作业票审查/人员筛查 4、补贴 2、URS 外的操规审核 1、运维触发 2（见拍板点 2）。

### 减法结果
| | 现状 | 优化后 |
|---|---|---|
| 常驻注册 | 76 | **~38** |
| 全量回退 schema | 31,700 tokens | **~13,000 tokens** |
| 意图命中 schema | 2,000-3,000 tokens | 不变（路由重做后命中率提升） |

## 三、优化方案（P1-P5）

### P1 工具减法（第二批，2 天）
- **步骤 0（前置）**：在生产库跑审计摸底 SQL，拿 90 天真实调用频率：
  ```sql
  -- 生产 ai_call_audits + agent_session_events(tool_call 事件) 按工具名聚合
  SELECT payload->>'tool' AS tool, count(*) FROM safety.agent_session_events
  WHERE event_type='tool_call' AND created_at > now() - interval '90 days'
  GROUP BY 1 ORDER BY 2 DESC;
  ```
  零调用的 M 类工具直接删；有调用的收进按需域。
- M 类删除 + C 类合并 + D 类按需挂载 + query_special_op_records 参数瘦身（2.8KB → 目标 1.5KB，枚举参数说明精简）
- **agent.md 能力清单同步改**（能力清单是自我介绍模板的来源，删工具不改文案会引导模型调不存在的工具）
- tool_selector.py 过时注释修正

### P2 工具路由重做（第三批，2-3 天）
现状：关键词匹配 21 组意图，漏匹配 → 全量回退（31.7k tokens + 决策面爆炸）。

两段式路由：
1. **规则层**（快、零成本）：现有 INTENT_KEYWORDS 保留为高置信快速路径
2. **嵌入层**（准、无 LLM 调用）：每域配 10-15 个示例问题，用户消息 embedding 后与示例向量做余弦相似度（embedding profile 已有，本地 numpy 计算），取 top 域
3. **兜底**：置信度不足时挂"核心常驻集"（~15 个高频工具），**永不回退全量**
- 域定义随 P1 合并收敛为 ~12 个业务域
- 路由决策（命中域/置信度/规则或嵌入）写入审计，供持续调优
- 远期选项：按域拆 sub-agent（pydantic-ai delegation），主 agent 只做分发——本期不做，两段式路由收益/风险比更好

### P3 采样参数（第一批，10 分钟）
`business_agent/agent.py:65`：
- temperature 0.3 → **0.1**（对齐仓储，结构化任务更稳）
- max_tokens 2048 → **8192**（2048 有长内容截断风险；日报已特判透传，其他场景无保护）

### P4 上下文瘦身（第一批+第二批）
1. **agent.md 瘦身**（26.7KB → 目标 <10KB）：删除静态"能力清单"全文（约 12KB，与 tool_catalog 节和工具 docstring 三重重复），能力描述回归工具 schema 本身；保留角色/语言习惯/输出要求/业务规则/知识库检索规则
2. **工具结果截断**：`core/pipeline.execute_tool` 统一出口加每条 4KB 截断（列表类截断时附"共 N 条，已显示前 M 条"提示），对齐仓储
3. **压缩去内联**：maybe_compact 阈值 24k → 12k，且压缩移到后台任务（本轮照常返回，压缩结果下轮生效），消除偶发的一整轮 LLM 延迟尖刺
4. **记忆注入收紧**：每轮最多 5 条 + 相似度阈值提高（现 30 天半衰期检索全量注入）

### P5 延迟链路（第四批，可选二期）
- 事件双写异步化：append_event 改事务尾部批量提交或后台队列（现每轮 4-6 次 flush）
- Web 端 SSE + 流式输出：对接 pydantic-ai run_stream，对齐仓储 accepted→stage→message→finished 事件流（前端配套改动）
- 飞书侧卡片不支持流式，不动

## 四、验收标准
数据源：生产 `safety.ai_call_audits`（scenario=agent_chat，有 latency_ms 与 token 用量）。

| 指标 | 基线 | 目标 |
|---|---|---|
| prompt_tokens P50/P95 | 优化前 7 天均值 | **-60%** |
| 首响延迟 P50/P95 | 同上 | **-40%** |
| 全量回退占比 | 待测（审计埋点后可见） | <5% |
| "工具未挂载"失败 | 偶发 | 0 |

另建 20 问回归集（golden questions 覆盖各业务域），优化前后各跑一遍对比工具选择正确率——防止减法减掉能力。

## 五、拍板点（4 个）
1. **URS 9 工具整域拆出常驻**（按需挂载）：推荐拆。聊天里做多步审核工作流本身低效，Web 页面已有完整 URS 审核界面。
2. **poll_hazard_ai_analysis / poll_hazard_rectification_review 运维触发器**：轮询每 5 分钟自动跑，聊天触发是手动补跑路径。推荐与 M 类一起收进"运维域"按需挂载（保留补跑能力，不常驻）。
3. **office 低频写 4 个**（create_base/create_slides/set_permission/rollback）：推荐按需挂载不删（office intent 已有明确关键词，命中才挂）。
4. **M 类 5 个管理工具**：推荐生产审计确无调用后直接删；若 admin 有对话查询需求，二期做角色专属域。

## 六、纪律（不动什么）
- 不动写确认门（PendingAction/DeferredToolRequests 机制是对的）
- 不动 deny-by-default 权限体系（ROLE_TOOL_POLICY）
- 不碰平台层（AIService/SchedulerEngine 均不改）
- 不做跨模块共享基建（仓储与安全 AI 基础设施的合并是另一个议题，本方案不涉及）

## 七、分期落地
| 批次 | 内容 | 工作量 | 预期收益 |
|---|---|---|---|
| 第一批 | P3 参数 + P4 结果截断 + agent.md 能力清单瘦身 | 半天 | prompt 降 ~30%，立竿见影 |
| 第二批 | P1 减法（生产摸底→删/合并/拆域）+ agent.md 同步 | 2 天 | 常驻 76→38，回退面减半 |
| 第三批 | P2 两段式路由 + 审计埋点 | 2-3 天 | 全量回退 <5%，选择准确率提升 |
| 第四批 | P5 异步化 + Web SSE（可选） | 2 天 | 首响感知进一步提升 |

每批独立可回滚（git revert 边界清晰），批间无强依赖，可随时暂停。
