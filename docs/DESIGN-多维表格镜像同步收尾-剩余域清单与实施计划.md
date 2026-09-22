# 多维表格「平台镜像同步」收尾 — 剩余功能清单与改造计划

> 日期：2026-09-21
> 状态：**决策点已拍板（2026-09-21：Q1=B / Q2=A / Q3=B / Q4=A，仅 Q6 待盘点），可按批次一开票**
> 前置文档：docs/DESIGN-安全模块多维表格直读改造-清单与计划.md（2026-09-17，本文承接其未完成部分并做三处分类修正）
> 代码基线：fuxing-dazah @ 11caec2（feature/warehouse-module）
> 依据：bitable_config/registry.py（14 域 24 表）+ event_hooks.py（14 个 drive 订阅域）+ scheduler.py（SCHEDULED_JOBS）+ 逐 handler/service/api 源码核实

---

## 0. 一句话结论

「取消平台镜像同步」改造已完成 **隐患（hazard）、特殊作业（special_op）、消防报警（fire_alarm）3 域 + 公共直读底座 bitable_direct**。
剩余涉及 Bitable 镜像同步的功能共 **安全模块 11 个域**（P1 定时任务域 3 个、P2 查询为主域 6 个、P3 重双向大域 2 个），
另有 **6 项边界外/无需改造**（含仓储模块——其架构方向本就是 Base 权威反向镜像，不属于本次取消范围）。

推进顺序：

1. **批次一 P1**：中控报警、持证到期、危化品库存 —— 与消防完全同构的定点日报域，收益最高；
2. **批次二 P2**：关键风险作业报备（最轻试点）→ 相关方准入 → 应急演练 → 法规标准（只切清单查询）→ MSDS；
3. **批次三**：EHS 变更 —— 平台侧有完整审批状态机且 URS 功能正在活跃开发，等收尾后按「先只切 Agent 查询」口径做；
4. **批次四 P3 一期**：职业健康（7 个 Agent 工具切直读）、危险源辨识（Agent 查询切直读，事件流转保留）。

每域沿用既有 **8 票据模板 + 4 开关 + 双路径逐字比对 + 零回写探针** 验收口径（见第 6、7 节）。

**已拍板口径（2026-09-21）**：

- **Q1=B**：批次一/二各域的 **API 列表/统计/详情端点一并切直读**（Agent + 定时任务 + API），前端页经 API 天然拿到实时数据，**无「存量冻结」问题，票据 09 取消**。代价是 API 直读需全量拉取 + 应用侧分页/过滤/排序/统计，接受（见风险表）。
- **Q2=A**：ehs_change 等 URS 合并后开工，第一期只切 Agent 查询。
- **Q3=B**：事件镜像停用的域，drive 订阅在**收尾票统一退订**（含 hazard / special_op / fire_alarm 三域存量订阅核对）。**退订前置铁律**：逐域确认事件只喂镜像、无业务流转消费者（emergency_drill 采集归集链路须盘点确认）；knowledge / msds / oh / ehs_change / hazard_id **不退订**（RAG 入库与流程驱动仍依赖事件）。
- **Q4=A**：生产逐域独立开 DIRECT 开关 + 观察 1 天，不一次性全开。

---

## 1. 已完成基线（模板与底座，不再重复改造）

| 项 | 状态 | 证据 |
|---|---|---|
| P0 公共底座 service/bitable_direct/ | 已完成 | fields / filters / reader / writer / locks / gates / errors / attachments 八模块（提交 44b7ba3）；hazard 三处残留已收敛（f21506e） |
| hazard 隐患 | 已完成 | service/hazard_direct/；事件同步/补漏/AI 轮询全关（SAFETY_HAZARD_EVENT_SYNC_ENABLED=false 等 7 开关） |
| special_op 特殊作业 | 已完成 | service/special_op_direct/；4 开关全关待生产切换 |
| fire_alarm 消防报警 | 已完成（底座首个试点域） | service/fire_alarm/ 直读 13 文件 + writeback + contract；Agent query_fire_alarms 已切 query_fire_alarms_direct；4 开关全关；真机票据 08/09/10 收口（479d3aa / 1d37ce8 / f8837d5 / b167f03） |

**可复用资产**：fire_alarm 是第一个完全跑在 bitable_direct 底座上的域，其
config.py（开关四件套）、reader.py（视图对象 + 注入式读取协议）、query.py（Agent 直读查询）、
writeback.py（串行回写 + 防回环）、service.py（双路径编排）即为后续各域的直接模板。

---

## 2. 剩余功能全景清单

### 2.1 安全模块剩余 11 域（本次改造范围）

| 批次 | 域 key | 业务 | Bitable 表 | 事件处理器 | 镜像模型 | 定时任务 | Agent 工具 | 前端页 | 平台回写列 | 复杂度 |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 | central_alarm | 中控报警 | 1 + 15 表白名单 | feishu/central_alarm_bitable_handler.py | CentralAlarmRecord（models/msds.py） | 中控报警日报 17:00 | query_central_alarms | /safety/central-alarms | AI 汇总分析 | 中高 |
| P1 | cert | 持证到期预警 | 3（特种作业证 wiki 挂载 + 监护人 A/B 证同 Base 分表） | feishu/cert_bitable_handler.py + cert_bitable.py | PersonCertificate（models/msds.py） | 持证到期预警 08:00 | query_cert_warnings | /safety/cert-warnings | 证件编号/预警状态 | 中 |
| P1 | chemical_inventory | 危化品库存 | 1 | feishu/chemical_inventory_bitable_handler.py | ChemicalInventoryRecord | 日报 19:30 + 周报周五 15:30 | query_chemical_inventory、analyze_chemical_risk | /safety/chemical-inventory | 风险标记/风险说明 + Excel→Bitable 全量写 | 中高 |
| P2 | key_risk_op | 关键风险作业报备 | 1（每日关键风险预报表） | feishu/key_risk_op_bitable_handler.py | KeyRiskOperationReport（models/special_operations.py） | 无 | query_key_risk_ops | /safety/risk-reporting | **无（纯只读，最轻）** | 低 |
| P2 | contractor_admission | 相关方准入 | 1 | feishu/contractor_admission_bitable_handler.py + contractor_admission_bitable.py | ContractorAdmission（models/contractors.py） | 无 | query_contractor_admissions | /safety/contractor-admission | AI 三维度审核结论 3 列 | 中 |
| P2 | emergency_drill | 应急演练 | 2（主表 + 采集表） | feishu/emergency_drill_bitable_handler.py + emergency_drill_collection_handler.py | EmergencyDrillRecord 等（models/contractors.py） | 无 | query_drill_plans、query_drill_records | /safety/emergency-drill | 演练评估 AI 文件（附件）回写 | 高 |
| P2 | knowledge | 法规标准清单 | 2（安全法规 + 环保法规，共用 app_token） | feishu/knowledge_bitable_handler.py | SafetyKnowledgeArticle（models/knowledge.py） | 无 | knowledge_search、query_latest_regulations | /safety/knowledge-base ×2 | 法规编号回写 | 中（见 2.2 修正①） |
| P2 | msds | MSDS 台账 | 2（采集入口表 + 收录台账表） | feishu/msds_bitable_handler.py + msds_collection_handler.py | MsdsCollection、MsdsEntry（models/msds.py） | 无 | query_msds_documents、query_msds_collections | /safety/msds | 1:N 创建收录台账行 + AI 解析字段 | 高（见 2.2 修正②） |
| 批次三 | ehs_change | EHS 变更 | 2（变更审批 + 变更验收） | feishu/ehs_change_bitable_handler.py + ehs_change_bitable.py | models/ehs_changes.py | 无 | query_ehs_changes | /safety/ehs-change 3 页 | 4 维度 AI 审核结论 + URS 预审意见 | 高（见 2.2 修正③） |
| P3 | oh | 职业健康 | 6（人员汇总/体检/岗位/危害因素/转岗离岗/新员工） | feishu/oh_bitable_handler.py（63KB） | models/occupational_health.py | 无 | 7 个 query_oh_* | /safety/occupational-health | 人员总表回填、体检登记回写、差异分析、转岗结论 | 很高 |
| P3 | hazard_id | 危险源辨识（AI 脚本流转） | 1-2 | feishu/hazard_identification_bitable_handler.py | HazardIdentification（models/hazard_identifications.py） | 无 | query_hazard_identifications | /safety/hazard-identification 3 页 | 8 个脚本 AI 字段多列回写 | 很高（见 2.2 修正②'） |

### 2.2 相对 09-17 清单的三处分类修正（本次源码核实发现）

**修正① knowledge / msds：镜像的一部分是 RAG 入库链路（ETL），不能全停。**
knowledge_bitable_handler 在同步文章时做附件下载 → 切片 → 向量化（knowledge/chunk_service.py），
msds 同理（knowledge/msds_indexer.py 把 MSDS 台账映射为 knowledge_articles + chunk）。
这部分镜像不是「展示镜像」而是「加工入库」，停掉 = 知识库检索断粮。
**修正后口径**：事件入库 + 向量化链路整体保留；只把 **query_latest_regulations 等「清单类查询」切直读**；
法规爬虫写 Bitable（regulation_crawler/writer/bitable_writer.py）与编号回写均保留。

**修正② ehs_change：平台侧有完整审批状态机，且正在活跃开发，从 P2 后移。**
api/ehs_changes.py 暴露 create→submit→approve/reject→start_implementation→commission 完整生命周期，
服务层在镜像上驱动状态流转并多列回写——实际是「重双向域」。
且当前工作区有未提交的 URS 开发（service/ehs_change/urs.py、feishu/urs_card.py、urs_upload_context.py 等 14 文件），
同期改造必然冲突。**修正后口径**：等 URS 收尾提交后，第一期只切 Agent 查询入口（P3 同口径），整域直读另评估。

**修正③ hazard_id：事件是 AI 流程的驱动器，不是镜像消费者。**
handler 收到 record 事件后执行 advance_record（判定 + AI 执行 + 回写映射 + 镜像更新），
事件订阅是流程引擎的触发器。**修正后口径**：事件流转与 8 脚本回写整体保留，只把 Agent 查询（query_hazard_identifications）切直读。

### 2.3 边界外 / 无需改造清单（不属于本次「取消平台镜像同步」）

| 项 | 现状 | 处置 |
|---|---|---|
| warehouse 仓储模块 | **方向一致的反向架构**：V3.0 定案 2B「Base 权威 + 本地派生镜像」——qc_flow 每小时拉 material_receipt、先 Base 后镜像写路径（base_mirror.py）、对账中心裁决 Base 胜出（reconciliation.py）。Bitable 本就是唯一数据源，无「平台镜像」可取消 | **不改**。回写总开关 bitable_writeback_enabled 治理归仓储 V3.0 主线 |
| hr/title_review 职称评审 | Bitable 事件 → 平台库镜像（走 platform/integrations/feishu/event_handler.py 注册表，申报表/投票表） | **不在用户职责边界**（safety + warehouse）。可把本清单同步给 HR 模块负责人参考同一模式 |
| toolbox/tools/attendance_check | 考勤工具把结果直写 Bitable 结果表（batch_create + 先清后写），无镜像 | 不在取消语义内，不在边界 |
| fire_inspection 点检 PDF 归档 | 直连 Bitable 读记录/下载附件/回填附件（bitable.py），无镜像 | 无需改 |
| audit 安全台账审计 | 直读 Bitable（audit/reader.py），无镜像 | 无需改 |
| regulation_crawler 法规爬虫 | 爬取结果写 Bitable「法规标准清单」（写面） | 保留（knowledge 域改造只动读面） |

---

## 3. 分批实施计划

| 批次 | 内容 | 域 | 依赖 | 出口标准 | 粗估 |
|---|---|---|---|---|---|
| 一-1 | central_alarm 中控报警 | central_alarm | 无（底座已就绪）；**前置：15 表白名单探针盘点** | 双路径日报逐字相同 ≥3 天；API 列表/统计直读交叉核对；开关默认关；真机 dry-run | 1.5-2 天 |
| 一-2 | cert 持证到期 | cert | 无；**前置：3 表全量行数量级盘点** | 同上（预警卡片三轮收件人内容一致；API 直读核对） | 1-1.5 天 |
| 一-3 | chemical_inventory 危化品库存 | chemical_inventory | 无；Excel 写入路径零改动 | 日报/周报双路径逐字相同；风险回写探针；API 直读核对 | 2 天 |
| 二-1 | key_risk_op（Agent+API 模板试点） | key_risk_op | 无 | Agent 与 API 直读均与镜像全量交叉核对零差异 | 0.5-1 天 |
| 二-2 | contractor_admission | contractor_admission | 二-1 | 同上（AI 回写列保留） | 1 天 |
| 二-3 | emergency_drill | emergency_drill | 二-1；**前置：采集表→主表归集链路是否依赖事件的盘点** | 同上（附件回写保留；归集链路结论落档） | 1-1.5 天 |
| 二-4 | knowledge（只切清单查询+清单 API） | knowledge | 二-1 | query_latest_regulations 与清单 API 直读；入库向量化链路零改动 | 0.5-1 天 |
| 二-5 | msds | msds | 二-1、二-4 | 查询 Agent+API 直读；采集→收录写面与 msds_indexer 零改动 | 1.5 天 |
| 三 | ehs_change（URS 收尾后，只切 Agent 查询） | ehs_change | URS 功能合并 | Agent 直读零差异；状态机与回写不动 | 1 天 |
| 四-1 | oh（一期：7 个 Agent 工具切直读） | oh | 二 | 7 工具直读零差异；事件/回写/API 不动 | 1.5-2 天 |
| 四-2 | hazard_id（一期：Agent 查询切直读） | hazard_id | 二 | 同上；事件流转不动 | 1 天 |
| 收尾 | drive 订阅统一退订 + 镜像表归档说明 + 生产逐域开启演练 | 全部 | 各域完成后且生产直读稳定 | 见第 7 节 DoD 与 Q3 执行铁律 | 1 天 |

并行度：批次一 3 域可两两并行（central_alarm 有盘点前置）；批次二串行推进（模板相同）。
生产切换（Q4=A）：每域独立开 DIRECT 开关 + 观察 1 天，不搞一次性全开。

---

## 4. 每域改造细节

通用手法（10 条）与 8 票据 SOP 见第 5、6 节；此处只列各域特有内容。
开关命名统一 `SAFETY_<DOMAIN>_*`，闸门安放 4 处（事件 handler 入口 / 同步兜底 / 调度任务入口 / API 端点）。
**Q1=B 口径**：批次一/二各域的 API 列表/统计/详情端点与 Agent 同批切直读（全量拉取 + 应用侧分页/过滤/排序/统计）；批次三/四一期域 API 不动（镜像仍由事件更新，天然新鲜）。

### 4.1 central_alarm 中控报警（批次一-1）

- **现状链路**：drive 事件（15 表白名单：file_token == 中控 Base AND table_id ∈ 白名单）→ upsert/软删 CentralAlarmRecord → 日报 17:00 读镜像 → AI 汇总分析回写 → 渲染推送。workshop/line 由表名推导（bitable_mapper.derive_workshop_line，有缓存）。
- **改造后**：任务执行时对 15 表逐表做「报警时间」日期窗口查询（倒序分页 + 提前终止，参照消防票据 09 的窗口取数优化）→ 视图对象内存聚合 → AI 汇总 → 渲染推送；回写面不变。Agent query_central_alarms 切直读；**API**（api/central_alarm.py 列表/统计）切直读（全量窗口 + 应用侧过滤）。
- **新增开关**：SAFETY_CENTRAL_ALARM_DIRECT_ENABLED / _EVENT_SYNC_ENABLED / _SYNC_JOB_ENABLED / _WRITEBACK_AI_ENABLED。
- **触点文件**：service/central_alarm/（新增 query.py + direct reader，复用 bitable_mapper 映射纯函数）、feishu/central_alarm_bitable_handler.py（闸门）、scheduler.py 入口、business_agent/tools/read_tools.py、api/central_alarm.py。
- **特别注意**：①15 表字段同构但可能漂移，开工第一步跑 registry 全量 list_fields 盘点探针；②OR 条件不可与日期 AND 组合，多表取并集用「逐表 flat-AND + record_id 去重」（底座 filters.day_queries / union_by_record_id 已支持）；③窗口外事件晚到（夜间报警次日凌晨填报）时窗口放宽至 48h 并按应用侧过滤兜底；④API 列表全量拉 15 表性能需在盘点时测（响应时间验收 <2s）。

### 4.2 cert 持证到期（批次一-2）

> **2026-09-22 实施修正**（源码核实 + 探针后拍板，见 .scratch/cert-direct/spec.md）：
> 本节原「回写证件编号/预警状态保留」与源码不符——cert 现状对 Bitable **零写入**
> （handler 纯镜像、renew 只写平台 DB）。拍板改纯只读口径：renew 直读模式下禁用
> （API 400 / Agent error，提示改在飞书表格更新），无 WRITEBACK 开关、不建列。
> 注意①勘误：Bitable **读** API 直接接受 wiki token，直读路径无需 wiki→base 解析
> （该解析仅 drive 订阅需要）；探针实证 cert 连接配置存的已是底层 Base token。

- **现状链路**：3 表事件 → PersonCertificate 镜像 → 预警任务 08:00 全量扫描（repo.get_all_active）→ CertWarningEngine 纯规则计算 → 本人/部门负责人/安管人员三级卡片推送；renew 回填闭环只写平台 DB。
- **改造后（按修正口径已实施）**：任务执行时全量直读 3 表（探针 559 行、并发 ~1.4s，Q6=A 全量）→ 视图对象（字段与 PersonCertificate 同名）→ CertWarningEngine **零改动**（纯函数）→ 三级推送不变；renew 直读下禁用。Agent query_cert_warnings 与**持证列表/汇总 API** 切直读（renew 端点直读短路）。
- **新增开关**：SAFETY_CERT_DIRECT_ENABLED / _EVENT_SYNC_ENABLED（两开关，纯只读域）。
- **触点文件**：service/cert_direct/（新增包：config/reader/query + tests）、scheduler.py 入口、feishu/cert_bitable_handler.py（闸门）、read_tools.py + write_tools.py、api/cert_warnings.py、schemas/cert_warnings.py（Detail.id 放宽 UUID|str）、bitable_direct/gates.py（DOMAIN_CERT）、.env.example。
- **特别注意（保留给后续域参考）**：①原 wiki 解析需求勘误见上；②全量行数量级探针已做（559 行 << 3000，Q6=A）；③监护人 A/B 证同 Base 不同 table_id，cert_category 由 table_id 决定的映射要保持（已保持）；④guardian_b 表无「已换证日期」列（镜像该字段恒 None，直读同口径；若未来恢复 renew 回写 Bitable 需先建列）。

### 4.3 chemical_inventory 危化品库存（批次一-3）

- **现状链路**：19:30 日报 = 拉危险品日报群当日 Excel → apply_daily_workbook **写 Bitable**（匹配键 部门+存放部位+物料名称，新增自动建行）→ sync_inventory_records_from_bitable 拉回镜像 → run_full_scan 重算风险并回写风险标记/说明 → 对比昨日快照 → 推送分析日报。周报周五 15:30 读镜像落快照 + 环比 + AI 小结。事件镜像另有 drive 订阅。
- **改造后**：Excel→Bitable **写入路径零改动**；写完后不再回拉镜像，直接**直读 Bitable 全量**（单表、千行级）→ 内存风险重算（规则改吃视图对象）→ 风险列回写（写面保留）→ 再直读一次取回写后值做分析日报；周报同样直读。Agent query_chemical_inventory / analyze_chemical_risk 与**库存列表 API** 切直读。
- **新增开关**：SAFETY_CHEMICAL_INVENTORY_DIRECT_ENABLED / _EVENT_SYNC_ENABLED / _WRITEBACK_RISK_ENABLED。
- **触点文件**：chemical_inventory/daily_job.py（编排）、service/chemical_inventory.py（run_full_scan 改可注入数据源）、feishu/chemical_inventory_bitable_handler.py（闸门）、chemical_inventory/weekly_report.py、read_tools.py、api/chemical_inventory 相关端点。
- **特别注意**：①快照表（snapshots）是平台派生数据，**保留**；②部门/单位枚举映射 _DEPT_ENUM_TO_LABEL/_UNIT_ENUM_TO_LABEL 在直读侧同样要用（从 handler 抽到映射纯函数）；③「写完再读」的间隔要考虑 Bitable 写入可见性延迟，读失败重试 1 次。

### 4.4 key_risk_op 关键风险作业报备（批次二-1，最轻试点）

- 纯只读镜像，无任何回写、无定时任务。改造 = Agent query_key_risk_ops 与**API**（api/key_risk_operation_reports.py 列表/详情）切直读（按日期窗口），事件闸门关掉。开关 2 个（DIRECT / EVENT_SYNC）。作为 P2 六域「Agent + API」双切模板试点。

### 4.5 contractor_admission 相关方准入（批次二-2）

- 查询切直读（Agent + **API 列表/统计**，分页过滤改直读全量 + 应用侧过滤）；AI 三维度审核结论回写 3 列保留（ai_contractor_review 触发点在 API/Agent 手动，改为从直读数据触发）。开关：DIRECT / EVENT_SYNC / WRITEBACK_AI。

### 4.6 emergency_drill 应急演练（批次二-3）

- 2 表（主表 + 采集表）查询切直读（Agent + API）；演练评估 AI 文件回写是**附件上传**（build_attachment_extra + 串行写），保留。
- **退订前置盘点（Q3=B 铁律）**：确认「采集表事件 → 主表归集」链路是否依赖事件驱动；若依赖，该域事件闸门与订阅**保留**，只停镜像写入面。盘点结论写入 issue 后才能进收尾退订清单。

### 4.7 knowledge 法规标准（批次二-4，修正后口径）

- **只切清单查询**：query_latest_regulations 与**法规清单页 API** 改直读（2 表按 table_id 区分）。
- **保留**：事件入库 + 附件下载 + 切片向量化（chunk_service）、法规编号回写、爬虫 bitable_writer。
- 开关：SAFETY_KNOWLEDGE_DIRECT_ENABLED / _EVENT_SYNC_ENABLED（默认关但**本期不开**——入库链路要继续跑，事件同步开关语义改为「仅镜像字段写入」，向量化入口不受闸门影响；实现时把 handler 内「写镜像」与「建 chunk」两段拆开，闸门只罩前者）。

### 4.8 msds MSDS 台账（批次二-5，修正后口径）

- 查询（query_msds_documents / query_msds_collections 与**台账查询 API**）切直读。
- **保留**：采集→收录 1:N 建行 + AI 解析回写（写面）；msds_indexer → knowledge_articles + chunk 的 RAG 入库链路（依赖镜像触发，事件闸门不动或仅收敛镜像写入面）。
- 排在批次二最后：1:N 写入与「采集表事件 → 自动建收录行」的时序最复杂，先用前四域练手；收录台账行数大时 API 直读加内存分页限流（见风险表）。

### 4.9 ehs_change EHS 变更（批次三，URS 收尾后）

- 第一期只切 query_ehs_changes 直读；create→commission 状态机、4 维度 AI 审核、URS 预审回写、**API 与前端**全部不动（镜像仍由事件更新，页面天然新鲜）。
- 前置条件：当前工作区 URS 开发（14 文件）合并进 main 后再开工，避免同文件冲突。

### 4.10 oh 职业健康（批次四-1，一期只切查询）

- 7 个 Agent 工具（query_oh_persons / oh_exams / oh_positions / oh_hazard_factors / oh_followups / oh_applications / oh_hazard_enums）切直读；6 表事件镜像、人员总表回填、体检登记回写、差异分析、转岗结论回写、**API 与前端**全部保留。
- 注意 oh_hazard_enums 读的是危害因素枚举（可缓存），直读时按表结构盘点确认。

### 4.11 hazard_id 危险源辨识（批次四-2，一期只切查询）

- 只切 query_hazard_identifications；事件驱动的 advance_record（判定 + 8 脚本 AI 执行 + 回写）整体保留——事件是流程引擎触发器（修正③）。
- Agent 直读只读「人工字段 + 已回写的 AI 字段」，与镜像口径交叉核对。

### 4.12 收尾票（新增，Q3=B 的落点）

1. **退订清单核定**：hazard / special_op / fire_alarm（三域存量订阅核对，确认无事件消费者残留）+ 批次一/二中已关事件镜像的域（central_alarm、cert、chemical_inventory、key_risk_op、contractor_admission、emergency_drill——最后一域以 4.6 盘点结论为准）。
2. **不退订清单固化**：knowledge、msds（RAG 入库 + 1:N 建行）、oh、ehs_change、hazard_id（镜像/流程仍靠事件）。
3. 执行退订（feishu/subscribe.py 既有能力），逐域记录退订结果；退订后观察 1 天无告警。
4. 镜像表归档说明（各域镜像表停止写入的时间点与数据冻结口径，供审计回溯，不改表不删数据）。

---

## 5. 通用改造手法（沿用已固化的 10 条，不再展开）

1. 新增 service/<domain>_direct/（或在既有域包内加 query.py + reader）：config / 视图对象 / 编排 / query，单测同包 tests/；
2. 视图对象字段名与 ORM 模型完全同名，判定/渲染/AI 代码零改动；
3. 旧链路不删代码，只在入口前置闸门（事件 handler / 同步兜底 / 调度任务 / API 四处）；
4. 开关全默认关闭，打开才切换，改回开关 + 重启即回滚；
5. 定点拉取 + Agent 查询实时直读，不加常驻轮询；
6. 派生字段内存计算，只有飞书侧可见的才回写；
7. 一律批量查询接口（search_records_page 分页），禁止逐条 get_record；
8. 回写串行 + 条目间 0.5s + _set_sync_ignore 防回环；
9. 验收三件套：双路径逐字比对、零回写探针、ORM/视图对象等价断言；
10. 静态检查 ruff 改动行 clean + mypy 对照基线零新增（junit-xml 落盘比对）。

底座能力清单（bitable_direct 已全部就绪）：f_text/f_select/f_multi/f_person/f_datetime/f_attachments 双形态解析、flat-AND/OR 构造与下推能力矩阵、北京时间切天窗口、分页批量 reader、串行 writer + 幂等建列、per-record Redis 锁、开关闸门 gates、附件 extra 构造。

## 6. 单域票据模板（8 张，issue 文件放 .scratch/<domain>-direct/issues/）

| # | 票据 | 交付物 | 验收标准 |
|---|---|---|---|
| 01 | 类型接缝预重构 | 视图对象（字段与 ORM 同名）+ 判定/渲染代码类型标注 | ruff clean、mypy 零新增、冒烟 |
| 02 | 新列契约与建列（如需回写） | contract.py + 幂等建列脚本（dry-run → 人工确认 --apply） | 重复执行「跳过」 |
| 03 | 直读仓库 | 批量窗口查询 + 字段映射 + 视图对象 | 单测 + 生产只读比对（record_id 集合相同、逐字段差异 0） |
| 04 | 消费入口直读编排 | 定时任务 / Agent 直读编排 | 双路径渲染逐字相同 ≥3 天 |
| 05 | 回写（如需） | 只写目标列，串行 + 间隔 + 防回环 | 真机抽样 0 不一致；零回写探针 |
| 06 | 闸门与开关接线 | config.py + 4 处闸门 + .env.example | 全关 = 改造前行为；打开走直读；改回即回滚 |
| 07 | 其余消费方切直读 | **Agent 工具 + API 列表/统计/详情端点（Q1=B）**：全量拉取 + 应用侧分页/过滤/排序/统计 | Agent 与 API 各自与镜像口径交叉核对，差异可解释；常规列表响应 <2s |
| 08 | 验证套件与真机冒烟 | 比对脚本 + 探针 + 真机 dry-run | 第 7 节 DoD 全勾 |

不需要回写的域（key_risk_op）跳过 02/05；票据 09（存量冻结页面提示）随 Q1=B **取消**——API 直读后前端天然实时，批次三/四一期域镜像仍由事件更新，均无冻结面。

## 7. 每域验收 DoD（沿用 + Q1=B 增补）

- [ ] 直读包单测全绿（字段解析、过滤器下推、视图对象等价）
- [ ] 双路径逐字比对 ≥3 天 × 全模式
- [ ] 零回写探针：查询路径 update_record / create_record / create_field 调用数 = 0
- [ ] 开回写时写请求只含目标列
- [ ] ruff 改动行 clean；mypy 对照基线新增 = 0
- [ ] 开关全关时行为与改造前逐项一致（推送内容、任务状态、API 返回）
- [ ] **API 直读交叉核对（Q1=B 增补）：列表分页/过滤/排序/统计各抽 1 组样本，与镜像口径一致；常规列表响应 <2s**
- [ ] 打开开关真机冒烟（推送/查询至少各 1 次）
- [ ] 回滚演练：开关改回 + 重启，旧链路立即恢复
- [ ] 无新增数据库表、无 alembic 迁移
- [ ] issue 文件勾选验收标准
- [ ] **退订前置结论落档（收尾票前置）：该域事件消费者清单核对完毕，明确「可退订 / 不可退订 + 原因」**

## 8. 决策点（已拍板，2026-09-21）

| # | 决策点 | 选项 | 结果 |
|---|---|---|---|
| Q1 | API/前端口径 | A) Agent + 定时任务直读，API/前端维持镜像冻结 B) **Agent + API 都切直读**（前端经 API 天然实时） C) 全量含前端改造 | **B**。票据 07 范围扩大（含 API），票据 09 取消；API 直读全量 + 应用侧分页过滤，性能验收 <2s |
| Q2 | ehs_change 时机 | A) **URS 合并后第一期只切 Agent 查询** B) 并入当前 URS 开发 C) 现在整域直读 | **A**（批次三） |
| Q3 | 停用域的 drive 订阅 | A) 保留订阅、闸门短路 B) **统一退订省事件量** | **B**。收尾票统一执行（4.12 节）；退订前置铁律：逐域确认事件只喂镜像；knowledge / msds / oh / ehs_change / hazard_id 不退 |
| Q4 | 生产切换节奏 | A) **每域独立开 DIRECT + 观察 1 天** B) 全部完成后统一开 | **A** |
| Q6 | cert 全量拉取量级 | 盘点后若 >3000 行：A) 仍全量（每日一次可承受） B) 增量窗口 + 到期月份预筛 | **A**（2026-09-22 探针：3 表 559 行、并发 ~1.4s，远低于阈值）；同日拍板 cert 纯只读（renew 直读下禁用，见 §4.2 修正） |

## 9. 风险与对策（增量，通用风险见 09-17 清单第 9 节）

| 风险 | 说明 | 对策 |
|---|---|---|
| 与活跃开发冲突 | ehs_change/URS 14 文件未提交 | 批次三硬性前置「URS 合并」，其余批次不碰 ehs_change 文件 |
| RAG 断粮 | knowledge/msds 若误停事件入库，知识库检索停止更新 | 修正①②口径固化：「入库向量化」与「清单查询」分开闸门；验收项加「chunk 重建仍被触发」 |
| **API 直读性能（Q1=B 新增）** | 全量拉取 + 应用侧分页/过滤，大表列表响应可能超 2s；Bitable 限流 | 每域盘点行数量级先行；常规列表响应验收 <2s；超限时单域例外决策（保留该端点读镜像或加短 TTL 缓存），例外须记录在案 |
| **退订误伤业务事件（Q3=B 新增）** | emergency_drill 采集归集等隐性事件消费者若被退订，业务流程静默中断 | 退订前置铁律：逐域事件消费者清单核对（DoD 增补项）；hazard/special_op/fire_alarm 三域存量订阅同样核对后统一退；退订后观察 1 天无告警 |
| 15 表字段漂移 | central_alarm 白名单后期加表导致映射漏配 | 开工探针 list_fields 全量核对；加表需同步 registry + 映射 |
| 全量拉取限流 | cert 全量、chemical 全量、msds 收录表可能上千行 | 分页批量 + 倒序提前终止；单域盘点先行（Q6） |
| 镜像表语义残留 | 批次三/四一期域镜像仍由事件更新（事件闸门**不关**），与批次一/二「关事件」口径不同，易混淆 | 第 0 节已拍板口径 + 各域 issue 首行注明本域事件闸门去向；收尾票 4.12 固化两份清单 |
| 时序晚到事件 | central_alarm 夜间报警次日凌晨补录 | 窗口放宽 48h + 应用侧过滤兜底 |

---

## 附：开工即可做的三件事（决策已定，不再有前置疑问）

1. 只读探针脚本：central_alarm 15 表 list_fields + 行数盘点、cert 3 表全量行数、msds 收录表行数（回填 Q6 与各域量级）；emergency_drill「采集表事件 → 主表归集」链路代码走读，落退订前置结论；
2. 起 service/<domain>_direct/ 接口签名草案（按 fire_alarm 模板复制 config / reader / query 三件，Q1=B 口径下 query 层同时覆盖 Agent 与 API 两种调用方）；
3. 把本清单同步给 HR 模块负责人（title_review 是平台侧最后一个未纳入直读治理的 Bitable 镜像域，越界仅知会）。
