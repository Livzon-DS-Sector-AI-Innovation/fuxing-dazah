# 安全模块「多维表格直读」改造清单与实施计划

> 日期：2026-09-17
> 状态：清单与分批计划（待用户拍板第 8 节决策点）
> 进展（2026-09-21）：P0 公共底座与 P1-1 fire_alarm 已完成（44b7ba3 及后续票据 08/09/10），
> 并对 knowledge/msds/ehs_change/hazard_id 四域做了分类修正。剩余 11 域的执行以
> docs/DESIGN-多维表格镜像同步收尾-剩余域清单与实施计划.md 为准，本文作盘点依据保留。
> 对标：docs/DESIGN-特殊作业系统直读多维表格改造-设计方案.md、.scratch/special-op-direct/HANDOFF.md（隐患域与特殊作业域均已实施）
> 依据：backend/app/modules/safety/bitable_config/registry.py（14 域 24 张表注册表）+ 事件处理器 + 调度任务 + 镜像模型 + Agent 工具 + 前端页面
> 代码基线：fuxing-dazah @ ead173a（feature/warehouse-module）

---

## 0. 一句话结论

安全模块共注册 14 个多维表格域、24 张 Bitable 表，其中 **隐患（hazard）与特殊作业（special_op）已完成直读改造**。
**剩余 12 个域、22 张表仍在走「Bitable 事件 -> 平台库镜像 -> 消费方」链路。**

建议推进顺序：

1. **P0 先抽公共直读底座**（目前 hazard_direct 与 special_op_direct 各造了一套轮子，第三个域再复制就会失控）；
2. **P1 四个「有定时任务的定点日报域」**（消防报警、中控报警、持证到期、危化品库存）与特殊作业完全同构，收益最高；
3. **P2 六个「Agent 查询为主」的域**（关键风险作业报备、法规标准、相关方准入、EHS 变更、应急演练、MSDS）；
4. **P3 两个「重双向 / 多表大域」**（职业健康 6 表、隐患识别脚本流转），本期先只改 Agent 查询入口。

每个域沿用特殊作业那套 **8 票据模板 + 4 个开关 + 双路径逐字比对 + 零回写探针** 的验收口径。

---

## 1. 基线：已完成的两个域（作为模板）

| 域 | 直读包 | 旧链路残留（默认关闭） | 开关 |
|---|---|---|---|
| hazard 隐患 | service/hazard_direct/（bitable_repo / loop / bulletin / progress_dunning / progress_track / review / supervision / ai_analysis / alert / config） | 事件镜像、catch_up、平台回写 3 处 | SAFETY_HAZARD_DIRECT_POLL_ENABLED / _EVENT_SYNC_ENABLED / _CATCHUP_ENABLED / _AI_POLL_ENABLED / _REVIEW_POLL_ENABLED / _SUPERVISION_POLL_ENABLED |
| special_op 特殊作业 | service/special_op_direct/（bitable_repo / daily / query / contract / config + tests） | 事件镜像、08:00 全量对账、17:00 增量同步 | SAFETY_SPECIAL_OP_DIRECT_ENABLED / _EVENT_SYNC_ENABLED / _SYNC_JOB_ENABLED / _WRITEBACK_RISK_ENABLED |

### 1.1 已经跑通、值得固化的 10 条手法

1. 新增 service/<domain>_direct/ 包：config / bitable_repo / 视图对象 / 编排入口 / query，单测放同包 tests/。
2. **视图对象字段名与 ORM 模型完全同名**，原判定引擎、渲染器、AI 分析代码零改动。
3. **旧链路不删代码，只在入口前置闸门**（事件 handler / catch-up / 调度任务 / API sync 四处）。
4. **开关全默认关闭**，打开才切换，改回开关 + 重启即回滚，无数据副作用。
5. **定点拉取**（任务执行时拉一次）+ Agent 查询实时直读，**不加常驻轮询**。
6. **派生字段内存计算**，只有业务要求在飞书侧可见的才回写（特殊作业只回写 1 列）。
7. **一律批量查询接口，禁止逐条 get_record**（单条读实测 4.4 至 5.6 秒，1254607 Data not ready 高发）。
8. **回写串行 + 条目间 0.5 秒**（Bitable 同表不支持并发写）+ _set_sync_ignore 防回环。
9. 验收三件套：**双路径逐字比对**、**零回写探针**、**ORM 与视图对象等价断言**。
10. 静态检查用 **ruff 改动行 clean + mypy 对照基线新增为 0**（全仓基线不干净，只认零新增）。

---

## 2. 待改造清单（全景）

分批标记：P1 = 有定时任务的定点域；P2 = Agent/查询为主的域；P3 = 重双向/多表大域。
「回写」列指平台侧已经存在的 Bitable 写入动作（改造后只保留写入面，摘掉的是读取用的镜像）。

### 2.1 图纸（域 key -> 表 -> 镜像 -> 消费方）

| 批次 | 域 key | 业务 | Bitable 表数 | 事件处理器 | 镜像模型（文件） | 定时任务消费 | Agent 工具 | 前端页 | 平台回写 Bitable |
|---|---|---|---|---|---|---|---|---|---|
| P1 | fire_alarm | 消防报警 | 1 | feishu/fire_alarm_bitable_handler.py | models/msds.py（FireAlarmRecord） | 消防报警日报、消防报警日报私发 | query_fire_alarms | /safety/fire-alarms | AI 原因分析/整改建议 |
| P1 | central_alarm | 中控报警 | 1 + 15 表白名单 | feishu/central_alarm_bitable_handler.py | models/msds.py（CentralAlarmRecord） | 中控报警日报 | query_central_alarms | /safety/central-alarms | AI 汇总分析 |
| P1 | cert | 持证到期预警 | 3（特种作业证 + 监护人 A/B 证） | feishu/cert_bitable_handler.py、feishu/cert_bitable.py | models/msds.py（PersonCertificate） | 持证到期预警（每日 08:00） | query_cert_warnings | /safety/cert-warnings | 证件编号/预警状态回写（_is_sync_ignored 已就位） |
| P1 | chemical_inventory | 危化品库存 | 1 | feishu/chemical_inventory_bitable_handler.py | models/chemical_inventory.py | 危化品库存日报（19:30）、库存周报（周五） | query_chemical_inventory、analyze_chemical_risk | /safety/chemical-inventory | Excel -> Bitable 全量写入 + 风险标记/风险说明回填 |
| P2 | key_risk_op | 关键风险作业报备 | 1 | feishu/key_risk_op_bitable_handler.py | models/special_operations.py（KeyRiskOperationReport） | 无 | query_key_risk_ops | /safety/risk-reporting | 无（纯只读镜像，改造最轻） |
| P2 | knowledge | 法规标准清单（并入知识库文章表） | 2（安全法规 + 环保法规） | feishu/knowledge_bitable_handler.py | models/knowledge.py（SafetyKnowledgeArticle） | 无（法规爬虫独立） | knowledge_search、query_latest_regulations | /safety/knowledge-base | 法规编号回写 |
| P2 | contractor_admission | 相关方准入 | 1 | feishu/contractor_admission_bitable_handler.py、feishu/contractor_admission_bitable.py | models/contractors.py（ContractorAdmission） | 无 | query_contractor_admissions | /safety/contractor-admission | AI 三维度审核结论回写 |
| P2 | ehs_change | EHS 变更 | 2（变更审批表 + 变更验收表） | feishu/ehs_change_bitable_handler.py、feishu/ehs_change_bitable.py | models/ehs_changes.py | 无 | query_ehs_changes | /safety/ehs-change（apply、acceptance） | 4 维度 AI 审核结论 + AI 预审意见回写 |
| P2 | emergency_drill | 应急演练 | 2（主表 + 采集表） | feishu/emergency_drill_bitable_handler.py、feishu/emergency_drill_collection_handler.py | models/contractors.py（EmergencyDrillRecord） | 无 | query_drill_plans、query_drill_records | /safety/emergency-drill | 演练评估 AI 文件回写 |
| P2 | msds | MSDS 台账 | 2（采集入口表 + 收录台账表） | feishu/msds_bitable_handler.py、feishu/msds_collection_handler.py | models/msds.py（MsdsCollection、MsdsEntry） | 无 | query_msds_documents、query_msds_collections | /safety/msds | 1:N 创建收录台账行 + AI 解析字段 |
| P3 | oh | 职业健康 | 6（人员汇总/体检记录/岗位/危害因素/转岗离岗申请/新员工登记） | feishu/oh_bitable_handler.py（63KB，全模块最大） | models/occupational_health.py | 无 | query_oh_persons、query_oh_exams、query_oh_positions、query_oh_hazard_factors、query_oh_followups、query_oh_applications、query_oh_hazard_enums | /safety/occupational-health | 人员总表回填、体检登记表回写、差异分析结论、转岗结论回写（_set_sync_ignore 已就位） |
| P3 | hazard_id | 隐患识别（AI 脚本流转） | 1 至 2 | feishu/hazard_identification_bitable_handler.py | models/hazard_identifications.py | 无 | query_hazard_identifications | /safety/hazard-identification（含 ledger、[id]） | 8 个脚本 AI 字段多列回写 |

### 2.2 明确不在本次范围

| 项 | 原因 |
|---|---|
| 作业票审核（workticket_review/） | 数据源是外部工业互联网平台 HTTP API（client.py 只读），**本来就没有 Bitable 镜像**，无需改造 |
| 事故 accidents、安全检查 checks、每日风险作业报备 daily_risk_reports、培训 trainings、职业危害因素监测 oh_hazard_monitors、操作规程 regulations（法规生成器及其修订） | 平台自建业务，模型上无 feishu_record_id，**不与多维表格同步** |
| 特殊作业人员/作业票台账（special_ops_personnel、special_ops_permits）、承包商台账（Contractor） | 平台自建台账，无 Bitable 镜像 |
| SpecialOperationReport(source=manual) 等平台自有业务字段 | 随所属域保留在平台库，与镜像无关 |

---

## 3. 可行性分层（决定先做谁、做到哪一步）

### A 层：定点任务域（与特殊作业完全同构，收益最高）

适用：fire_alarm、central_alarm、cert、chemical_inventory。

共同特征：
- 有**定时任务**读镜像表（日报/预警），是「算完就发」的闭环，天然适合定点直读；
- 镜像基本只读展示 + AI/编号回写，没有平台侧人工发起的状态流转；
- 单表或少表，字段映射集中在一个 mapper 里。

改造语义：任务执行时按日期窗口直读 Bitable -> 内存判定 -> 渲染 -> 推送；回写面保持不变。
预期收益：不再受事件丢失影响（日报少报）、不再读旧值、省掉全量对账/补漏。

### B 层：Agent/查询为主的域

适用：key_risk_op、knowledge、contractor_admission、ehs_change、emergency_drill、msds。

共同特征：
- 没有定时任务，实时性诉求来自 **Agent 问答**与 Web 列表；
- 镜像由事件驱动，存在「事件丢失 -> 问答答不出/答旧值」问题；
- 部分域有平台侧回写（AI 审核结论），但读路径简单。

改造语义（默认口径）：**Agent 工具 + API 查询直读；Web 前端维持读镜像（存量冻结）**，与隐患/特殊作业的既有决策一致。
预期收益：助手问答拿到的是表格当前数据；事件镜像可以停。

### C 层：重双向 / 多表大域（先只改读入口）

适用：oh（6 表）、hazard_id（AI 脚本流转）。

共同特征：
- 多表联动、平台侧大量回写与状态流转、AI 流水线；
- 牵一发动全身，整域摘镜像风险高。

改造语义（建议）：第一期只把 **Agent 查询入口**（必要时加定时任务入口）改成直读；事件镜像、镜像表、多条回写链路**整体保留**，后续再分小步收敛。
预期收益：先把助手问答口径拉正，验证读路径，不动写路径。

### 3.1 逐域复杂度与风险评级

| 域 | 表数 | 回写列数（估） | 消费面 | 复杂度 | 建议批次 |
|---|---|---|---|---|---|
| key_risk_op | 1 | 0 | Agent + API + 1 页 | 低 | P2 首个（练手 Agent 模板） |
| fire_alarm | 1 | 2 至 4 | 2 个定时任务 + Agent + 1 页 | 低中 | P1 首个（底座试点） |
| cert | 3 | 1 至 2 | 1 个定时任务 + Agent + 1 页 | 中 | P1 |
| central_alarm | 1 + 15 白名单 | 2 至 4 | 1 个定时任务 + Agent + 1 页 | 中高 | P1 |
| chemical_inventory | 1 | 2 至 3 | 2 个定时任务 + Agent 2 个 + 1 页 + Excel 写入 | 中高 | P1 |
| knowledge | 2 | 1 | Agent 2 个 + 2 页 | 中 | P2 |
| contractor_admission | 1 | 3 | Agent + 1 页 | 中 | P2 |
| ehs_change | 2 | 5 至 8 | Agent + 3 页 | 中高 | P2 |
| emergency_drill | 2 | 1 至 2（附件） | Agent 2 个 + 1 页 | 高 | P2 |
| msds | 2 | 1:N 新建行 | Agent 2 个 + 1 页 | 高 | P2 末 |
| oh | 6 | 多 | Agent 7 个 + 1 页 | 很高 | P3 |
| hazard_id | 1 至 2 | 多（8 脚本） | Agent + 3 页 + 多条 API 写 | 很高 | P3 |

---

## 4. 公共前置工作（P0，必须先做）

### 4.1 抽公共直读底座 service/bitable_direct/

现状：hazard_direct/bitable_repo.py（30KB）与 special_op_direct/bitable_repo.py（14KB）各自实现了字段取值、过滤器构造、per-record 锁等重复逻辑。
第三个域如果再抄一份，维护成本会失控。

建议新包 `backend/app/modules/safety/service/bitable_direct/`：

| 文件 | 职责 | 复用来源 |
|---|---|---|
| fields.py | f_text / f_select / f_multi / f_person / f_datetime / f_attachments（含 search 返回 {type:1,value:[...]} 与单条 GET 返回 [...] 两种形态） | hazard_direct 的 f_* + special_op 的 _text 修复 |
| filters.py | flat AND / flat OR 构造、日期窗口（北京时间切天）、下推能力矩阵 | hazard_direct._and/_or/_flat、special_op.day_filter |
| reader.py | 分页批量查询封装、View 协议基类、client 解析（resolve_client） | 两包的 repo |
| writer.py | 串行写 + 条目间隔 0.5s + 幂等建列 + 防回环标记 | special_op.writeback_risk_levels、special_op contract.py |
| locks.py | per-record Redis 锁 | hazard_direct.record_lock |
| gates.py | 开关基类 + legacy_event_sync_active / legacy_sync_job_active 判定 | 两包 config.py |
| verify.py | 双路径逐字比对、零回写探针、ORM/View 等价断言等测试夹具 | special_op tests/factories.py + .scratch 探针脚本 |

**迁移策略（重要）**：hazard_direct 与 special_op_direct **本次不回改**，新域直接用新底座；
等 P1 四个域跑通、底座稳定后，再单开一张票把两个旧包收敛过来（避免动已上线代码）。

### 4.2 Bitable 能力基线表（把已实测的坑固化成文档 + 单测）

前两次改造实测到的 API 约束，必须写进底座单测，避免每个域重新踩：

1. filter **只支持单层 conjunction**，嵌套条件组返回 field validation failed；
2. 顶层 or 可用，但**不能与日期 AND 组合**（需要 OR 的筛选拆成多条 flat-AND 查询后按 record_id 取并集）；
3. 单选字段**不支持 contains**，只支持 is / isNot / isEmpty / isNotEmpty；文本字段支持 contains；
4. 日期过滤用 ExactDate，**按天粒度、以北京时间切天**，不是毫秒比较；
5. search 接口**只返回有值的字段**（空字段不出现在 fields 里），不能靠「字段缺失」判断映射失败，必须 list_fields；
6. search 返回 {"type":1,"value":[{"text":...}]}，单条 GET 返回 [{"text":...}]，文本解析要兼容两种；
7. 同一张表**不支持并发写**，必须串行 + 间隔；
8. 单条 get_record 实测 4.4 至 5.6 秒且高频 1254607 Data not ready，**禁止逐条读**。

### 4.3 统一开关命名与闸门位置

命名（沿用 SAFETY_<DOMAIN>_* 前缀）：

    SAFETY_<DOMAIN>_DIRECT_ENABLED         直读总开关
    SAFETY_<DOMAIN>_EVENT_SYNC_ENABLED     旧路径：Bitable 事件 -> 平台库镜像
    SAFETY_<DOMAIN>_SYNC_JOB_ENABLED       旧路径：全量对账 / 增量同步任务
    SAFETY_<DOMAIN>_WRITEBACK_<X>_ENABLED  平台 -> Bitable 回写（按域 0 至 N 个）

闸门统一安放 4 处：事件 handler 入口、catch_up（若该域有）、调度任务入口、API sync/generate 端点。
要求：任何一个域的旧链路，都必须能被「一组开关 + 重启」完整停掉。

### 4.4 盘点探针脚本（每域开工第一步）

scripts/tmp/survey_<domain>.py（只读），输出：
- 该域注册的 app_token / table_id / 字段数 / 当日或近 N 日行数；
- 关键字段空值率、系统字段（created_time）可读性；
- 读取点清单（事件 handler / 同步任务 / API / Agent / 前端）；
- 写入点清单（哪些方法会 update_record / create_record）；
- 当前开关现状。

### 4.5 单域 SOP + 票据模板（见第 5 节）

### 4.6 状态

所有新域开关默认关闭；P0 完成时部署行为与今天**完全一致**。

---

## 5. 单域标准票据模板（8 张，与特殊作业对齐）

每开一个域，就照这张表开 8 张票据（issue 文件放 .scratch/<domain>-direct/issues/NN-*.md）。
不需要回写的域跳过 02 与 05。

| # | 票据 | 交付物 | 验收标准 |
|---|---|---|---|
| 01 | 类型接缝预重构 | 视图协议（字段与 ORM 同名）、原有判定/渲染代码改类型标注 | ruff clean、mypy 对照基线新增为 0、运行时冒烟 |
| 02 | 新列契约与建列脚本（如需回写） | contract.py（列名/类型/选项/值映射）+ 幂等建列脚本（先 dry-run，再人工确认 --apply） | 重复执行「跳过」、字段数只增一次 |
| 03 | 直读仓库与视图对象 | service/<domain>_direct/bitable_repo.py（按日期窗口批量查询 + 字段映射 + 视图对象） | 单测 + 生产只读比对：镜像与直读 record_id 集合相同、逐字段差异 0 |
| 04 | 消费入口直读编排 | 定时任务 / Agent 入口的直读编排函数 | 同一份数据双路径渲染**逐字相同**（至少 3 天 x 各模式） |
| 05 | 回写（如需） | 只写目标列，串行 + 间隔 + 防回环 | 单测 + 真机回写抽样 0 不一致；零回写探针证明查询路径写调用数为 0 |
| 06 | 闸门与开关接线 | config.py + 4 处闸门 + .env.example | 开关全关时行为与改造前一致；打开后走直读；改回即回滚 |
| 07 | 其余消费方切直读 | Agent 工具 / API / 前端（按第 8 节 Q1 口径） | 与直读口径交叉核对，差异可解释 |
| 08 | 验证套件与真机冒烟 | 逐日比对脚本 + 零回写探针 + 真机 dry-run / 真实推送 | 见第 7 节 DoD 全勾 |

新增（本计划特有，可选）：

| # | 票据 | 交付物 | 验收标准 |
|---|---|---|---|
| 09 | 存量冻结说明与页面提示 | Web 页数据来源说明（如需要） | 页面不报错、口径可解释 |

---

## 6. 分批实施计划

| 批次 | 内容 | 域 | 依赖 | 出口标准 |
|---|---|---|---|---|
| P0 | 公共底座 + 能力基线 + SOP + 盘点脚本 | 无 | 无 | 底座单测全绿；一个试点域用底座跑通 |
| P1-1 | **fire_alarm 消防报警**（底座试点） | fire_alarm | P0 | 双路径日报逐字相同；开关默认关；真机 dry-run 通过 |
| P1-2 | central_alarm 中控报警 | central_alarm | P1-1 | 同 P1-1（先做 15 表白名单盘点） |
| P1-3 | cert 持证到期 | cert | P1-1 | 同 P1-1（3 表映射） |
| P1-4 | chemical_inventory 危化品库存 | chemical_inventory | P1-1 | 同 P1-1（注意 Excel 写入路径不动） |
| P2-1 | key_risk_op 关键风险作业报备（Agent 模板试点） | key_risk_op | P0 | Agent 直读查询与镜像全量交叉核对零差异 |
| P2-2 | knowledge 法规标准 | knowledge | P2-1 | 同上（含编号回写保留） |
| P2-3 | contractor_admission 相关方准入 | contractor_admission | P2-1 | 同上 |
| P2-4 | ehs_change EHS 变更 | ehs_change | P2-1 | 同上（2 表） |
| P2-5 | emergency_drill 应急演练 | emergency_drill | P2-1 | 同上（2 表 + 附件回写） |
| P2-6 | msds MSDS 台账 | msds | P2-1 | 同上（1:N 写入最复杂，放最后） |
| P3-1 | oh 职业健康（先只改 Agent 查询入口） | oh | P2 | 7 个 Agent 工具切直读；镜像与回写链路不动 |
| P3-2 | hazard_id 隐患识别（先只改 Agent 查询入口） | hazard_id | P2 | Agent 查询切直读；脚本回写链路不动 |

并行度建议：
- P1 四个域两两并行（结构同构，但 central_alarm / chemical_inventory 各有一个盘点前置）；
- P2 六个域可串行推进（模板相同、风险低），也可拆两人并行；
- P3 单独排期，不与其他批次并行。

粗估（按域，含规格/质询/实现/验收）：P1 每域 1 至 2 天；P2 每域 0.5 至 1.5 天；P3 每域 2 天以上（只做读入口则 1 天）。
P0 底座约等于一个 P1 域的 1.5 倍工作量。

---

## 7. 每域验收清单（DoD）

- [ ] 直读包单测全绿（含字段解析、过滤器下推、视图对象等价）
- [ ] 双路径逐字比对：至少 3 天 x 该域全部模式（today/afternoon 或等价）
- [ ] 零回写探针：查询路径 update_record / create_record / create_field 调用数 = 0
- [ ] 开回写时写请求只含目标列（列名单一）
- [ ] ruff：改动行 clean（既存告警不动）
- [ ] mypy：对照基线新增 = 0（用 junit-xml 落盘比对，见特殊作业 HANDOFF 第 5 节工具链约束）
- [ ] 开关全关时，行为与改造前逐项一致（回归对比：推送内容、任务状态、API 返回）
- [ ] 打开开关真机冒烟（推送 / 查询至少各 1 次）
- [ ] 回滚演练：开关改回 false + 重启，旧链路立即恢复
- [ ] 无新增数据库表、无 alembic 迁移（除非用户拍板新增列）
- [ ] 对应 issue 文件勾选验收标准

---

## 8. 需要拍板的决策点

| # | 决策点 | 选项 | 建议 |
|---|---|---|---|
| Q1 | 改造范围口径 | A) 定时任务 + Agent 直读，API/前端维持读镜像（同隐患/特殊作业） B) 定时任务 + Agent + API C) 全量含前端 | **A**。前端要分页/排序/统计，直读需拉全量内存算，性价比低；与既有决策一致 |
| Q2 | 是否先抽公共底座 | A) 先抽 bitable_direct 再做新域 B) 每个域照抄一份 | **A**。第三个域开始复制就会失控；两个旧包暂不回改 |
| Q3 | Web 页面数据停滞是否接受 | A) 接受（存量冻结、只读） B) 不接受（需另做前端直读） | **A**（同隐患 Web 决策）；若不接受，P0 需追加前端方案 |
| Q4 | 每个域要回写哪些派生量 | 逐域确认列名/类型/选项 | 默认**只回写业务要求在飞书侧可见的列**，其余内存计算 |
| Q5 | 批次优先级 | P1 四个定时任务域优先 vs 先做最简单的 key_risk_op | 建议 P0 后先做 **fire_alarm** 作底座试点，再做 key_risk_op 验证 Agent 模板 |
| Q6 | oh 与 hazard_id 是否本次纳入 | A) 只做 Agent 查询入口 B) 整域直读 C) 不做 | **A**；整域直读放到 P4 之后再评估 |
| Q7 | 开关命名是否沿用 SAFETY_<DOMAIN>_* | A) 沿用 B) 换新前缀 | **A**，与 hazard / special_op 对齐 |
| Q8 | 每域是否允许新增 Bitable 列 | A) 允许（先 dry-run + 人工确认） B) 不允许 | **A**，但只在 Q4 确认有业务诉求时 |
| Q9 | 是否统一 catch_up / 补漏策略 | A) 直读后彻底关掉 B) 保留作兜底 | **A**（直读后镜像无意义）；旧代码保留、开关关闭 |

---

## 9. 风险与对策

| 风险 | 说明 | 对策 |
|---|---|---|
| Web/API 数据停滞 | 镜像不再更新后，页面上看到的是历史快照 | 明确冻结策略 + 页面提示（第 5 节票据 09）；按 Q1 口径执行 |
| 事件回环 | 平台回写 Bitable 会触发 changed 事件，若镜像还在写会打架 | 复用 _set_sync_ignore 模式；直读后镜像停止写入，回环面进一步缩小 |
| 开关散落 | 一个域的旧链路散在 handler / catch_up / scheduler / API 四处，容易漏关 | P0 统一 gates.py；每域验收必查「四处闸门」 |
| 生产 Bitable 结构变更 | 建列属黄色操作，改的是生产表结构 | 幂等脚本 + 先 dry-run 输出 + 人工确认后 --apply；重复执行必须「跳过」 |
| 大表全量拉取限流 | 部分域（如中控 15 表白名单、法规全量）行数可能上千 | 日期窗口下推 + 分页 + 批量接口；禁止逐条 get_record |
| 多表域字段漂移 | oh 6 表、central 15 表，后期加表会导致映射漏配 | 盘点脚本按 registry 全量 list_fields 核对；加表需同步 registry |
| 模型文件与域不一致 | 镜像模型按文件归类（fire_alarm/central_alarm/cert 都在 models/msds.py；emergency_drill 在 models/contractors.py） | 开工第一步先用探针输出「域 -> 模型类 -> 表」映射，避免找错文件 |
| 既存缺陷被顺带暴露 | 特殊作业那次就发现「动火方式」列名对不上（5 条规则从未生效） | 每域盘点时做一次「映射字段 vs list_fields」核对，发现的缺陷单独开票，不在改造里顺手改 |
| 全仓质量基线不干净 | mypy 约 150+ 错误、ruff 有既存告警 | 统一「对照基线零新增」口径；不动无关文件 |

---

## 10. 参考证据（本次盘点依据）

| 证据 | 位置 |
|---|---|
| 14 域 24 张表注册表（含 purpose / app_token / table_id / 字段映射） | backend/app/modules/safety/bitable_config/registry.py |
| drive 订阅域清单（13 个 handler） | backend/app/modules/safety/bitable_config/event_hooks.py |
| 定时任务清单 | backend/app/modules/safety/scheduler.py（SCHEDULED_JOBS） |
| 事件处理器 | backend/app/modules/safety/feishu/*_bitable_handler.py |
| 镜像模型 | backend/app/modules/safety/models/（msds.py / contractors.py / occupational_health.py / ehs_changes.py / chemical_inventory.py / knowledge.py / special_operations.py / hazard_identifications.py） |
| Agent 读取工具 | backend/app/modules/safety/business_agent/tools/read_tools.py（26 个 query_* 工具） |
| 前端页面 | frontend/src/app/(dashboard)/safety/ |
| 已完成模板 | backend/app/modules/safety/service/hazard_direct/、service/special_op_direct/ |
| 已完成实施记录 | .scratch/special-op-direct/HANDOFF.md、docs/DESIGN-特殊作业系统直读多维表格改造-设计方案.md |
| 开关现状 | backend/.env.example（SAFETY_HAZARD_* / SAFETY_SPECIAL_OP_* 段） |

---

## 附：建议的下一步（不待拍板即可做的部分）

1. 用只读探针把 12 个域的「表数 / 字段数 / 行数 / 读点 / 写点」跑出来，回填第 2 节表格的空白项；
2. 起草 service/bitable_direct/ 的接口签名（fields / filters / reader / writer / gates）供评审；
3. 待第 8 节 Q1 至 Q9 拍板后，按 P0 -> P1-1 顺序开票。