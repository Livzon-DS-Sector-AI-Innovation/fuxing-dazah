# 安全模块 3.0 四期 · 四新域表结构与页面口径蓝本（goals / training-behavior / facilities / incidents）

> 日期：2026-10-14
> 状态：**蓝本（未接入）**。四域已在 registry 注册为占位域（`default_connection=None`：不播种/不订阅/不建 DB 行），页面与端点按本文口径实现三态骨架；将来接入=按本文建表 → bitable 配置页补连接 → 页面零改码出数。
> 上游口径：`DESIGN-安全模块Web退役与新面板-实施方案-20261012.md`（§2 菜单↔体系模块映射：goals=S1/4.5.6 体系治理段、training-behavior=S6/9.2.9.3、facilities=S8/10.2、incidents=S16/13.1）；`DESIGN-安环Agent业务层体系-dazah现状拼图与改造思路-20261012.md` §3 各域现状/缺口（本文不重复，只做字段级蓝本）。
> 代码基线：feature/warehouse-module @ 3b5c9685
> 字段类型词表对齐 `registry.py` `FieldType`：text / person / multi_select / single_select / enum / attachment / datetime / combined_text

## 0. 一句话定位

四域「先立设计与骨架」：本文定义 4 域 9 张 Bitable 表的字段结构与统计/健康度口径，是**将来建表的蓝本**与**本轮页面/端点的字段口径依据**；表未建之前一切按「未接入」三态呈现。

## 1. 总则（四域通用）

- **页面形态**（3.0 口径，四页同构）：PageHeader（面包屑+一句话定位，extra=StatusTag 三态）→ StatCard 统计行（口径见各域 §统计）→ SectionCard 本域健康度（状态+指标口径说明）→ SectionCard 主台账 + antd Table（列=各域§主台账列，分页控件就绪，空表 EmptyGuide 引导建表接入）。
- **端点信封**：`GET /api/v1/safety/{domain}?page=&page_size=` → `{status: not_connected|live|degraded, stats|null, ledger{data,meta}, errors}`。`stats` 字段名=各域§统计的英文字段；`ledger` 行字段=各域主台账英文目标字段。
- **主台账原则**：每域一张主台账进分页表（goals=目标指标、training-behavior=培训实施、facilities=设备台账、incidents=事件登记）；其余表在蓝本中定义、接入后作为附加 SectionCard 扩展（本轮不实现）。
- **接入步骤**（将来）：飞书按§表结构建表 → bitable 配置页为对应 kind 配 app_token/table_id（或补 registry `default_connection`）→ 端点自动转 live、页面零改码出数 → 需要事件同步的域再补 `default_mappings` 与 handler（本轮不做）。
- **registry kind 对照**：域 key/kind 与表名一一对应（见各域节标题）；`subscribe="record"`（纯只读起步，不订阅）。

## 2. goals 目标责任与绩效（S1）

> 体系定位：安全生产目标的制定、分解与达成跟踪；各级人员安全责任制清单；安全投入与保险台账；管理者履职评价与绩效评定。域现状=全缺（最接近资产=ai_call_audits/scheduler 留痕/分域日报，见上游 §3 S1）。

### 2.1 表清单（3 张）

| kind | 表名 | 用途 |
|---|---|---|
| `goal_indicator` | 目标指标表 | 年度安全目标的制定/分解/达成跟踪（**主台账**） |
| `responsibility` | 责任制清单表 | 各级人员安全责任制与责任书签订状态 |
| `investment` | 安全投入台账 | 安全费用投入登记（金额/类别/凭证） |

### 2.2 目标指标表（主台账）字段

| Bitable 列名 | 目标字段 | 类型 | 枚举值 / 说明 |
|---|---|---|---|
| 年度 | year | single_select | 如 2026 |
| 目标名称 | name | text | 如「重伤及以上事故为零」 |
| 指标类型 | indicator_type | enum | 绝对指标 / 相对指标 |
| 指标值 | target_value | text | 目标值（含单位语义，如 0、≤2‰） |
| 统计口径说明 | metric_note | text | 达成判定口径（如按千人负伤率） |
| 分解层级 | level | enum | 公司 / 部门 / 班组 |
| 责任部门 | department | multi_select | |
| 责任人 | owner | person | |
| 完成值 | actual_value | text | 当期实际值 |
| 达成状态 | status | enum | 进行中 / 已达成 / 未达成 |
| 备注 | note | text | |

### 2.3 责任制清单表字段

| Bitable 列名 | 目标字段 | 类型 | 枚举值 / 说明 |
|---|---|---|---|
| 责任层级 | level | enum | 主要负责人 / 分管领导 / 部门负责人 / 班组长 / 岗位员工 |
| 岗位/角色 | role | text | |
| 职责条款 | duties | combined_text | 责任清单正文 |
| 签订日期 | signed_at | datetime | |
| 有效期至 | valid_until | datetime | 年度责任书有效期 |
| 签订状态 | status | enum | 已签订 / 未签订 / 已过期 |
| 责任书附件 | agreement_file | attachment | |
| 备注 | note | text | |

### 2.4 安全投入台账字段

| Bitable 列名 | 目标字段 | 类型 | 枚举值 / 说明 |
|---|---|---|---|
| 投入日期 | invested_at | datetime | |
| 投入类别 | category | enum | 安全设施 / 教育培训 / 劳保用品 / 应急演练 / 隐患整改 / 其他 |
| 项目名称 | project | text | |
| 金额（元） | amount | text | 数字文本（台账口径，万元换算在统计侧） |
| 责任部门 | department | multi_select | |
| 凭证附件 | voucher_file | attachment | 发票/合同 |
| 备注 | note | text | |

### 2.5 统计口径（StatCard 行，6 卡）

| 卡 | 英文字段 | 口径公式（未接入显示「—」） |
|---|---|---|
| 年度目标总数 | goal_total | 目标指标表 count(年度=当前年度) |
| 已达成 | goal_achieved | count(达成状态=已达成) |
| 进行中 | goal_in_progress | count(达成状态=进行中) |
| 未达成 | goal_missed | count(达成状态=未达成) |
| 责任书签订率 | agreement_rate | 已签订 / (已签订+未签订+已过期)，百分比 |
| 年度投入（万元） | investment_wan | sum(金额)/10000，当年 |

### 2.6 健康度卡指标

- **ok**：goal_missed=0 且责任书无「已过期」。
- **warn**：goal_missed>0 或 责任书已过期>0。
- **metric 文案模板**：`目标达成 {goal_achieved}/{goal_total} · 责任书签订率 {agreement_rate}% · 年投入 {investment_wan}万`；未接入=`未接入`；采集异常=无 metric（errors 标注）。

## 3. training-behavior 教育培训与行为管控（S6）

> 体系定位：培训计划、实施与签到台账；培训到期与复训追踪；违章行为档案、纠正通知与定向辅导。域现状≈35%（培训 CRUD 在 HR 模块、违章识别在隐患 AI；本域=安全侧自有台账口径，不对接 HR）。

### 3.1 表清单（2 张）

| kind | 表名 | 用途 |
|---|---|---|
| `training` | 培训计划与实施表 | 计划/实施/签到/考核一体化台账（**主台账**） |
| `violation` | 违章行为档案表 | 违章登记、处理、纠正闭环 |

### 3.2 培训计划与实施表（主台账）字段

| Bitable 列名 | 目标字段 | 类型 | 枚举值 / 说明 |
|---|---|---|---|
| 培训名称 | name | text | |
| 培训类别 | category | enum | 入厂三级教育 / 年度复训 / 专项培训 / 转岗培训 / 外来人员培训 |
| 计划日期 | planned_at | datetime | |
| 实施日期 | held_at | datetime | 未实施为空 |
| 培训形式 | form | enum | 线下 / 线上 / 实操 |
| 组织部门 | department | multi_select | |
| 讲师 | lecturer | person | |
| 应到人数 | expected_count | text | 数字文本 |
| 实到人数 | actual_count | text | |
| 签到表 | attendance_file | attachment | |
| 考核方式 | assessment | enum | 考试 / 签到 / 实操评估 / 无需考核 |
| 考核合格人数 | passed_count | text | |
| 状态 | status | enum | 未开始 / 进行中 / 已完成 / 已取消 |
| 下次复训日期 | next_retraining_at | datetime | 复训追踪锚点 |
| 备注 | note | text | |

### 3.3 违章行为档案表字段

| Bitable 列名 | 目标字段 | 类型 | 枚举值 / 说明 |
|---|---|---|---|
| 违章日期 | occurred_at | datetime | |
| 违章人员 | person_name | person | |
| 所属单位 | department | multi_select | 含承包商 |
| 违章类别 | category | enum | 操作违章 / 指挥违章 / 防护缺失 / 纪律违章 |
| 违章等级 | level | enum | 一般 / 严重 / 重大 |
| 违章描述 | description | combined_text | |
| 处理方式 | handling | enum | 批评教育 / 罚款 / 停工培训 / 待岗 |
| 纠正措施 | corrective_action | text | |
| 状态 | status | enum | 纠正中 / 已纠正 |
| 关联隐患编号 | related_hazard_no | text | |
| 定向培训 | retraining_note | text | 违章→定向培训闭环记录 |
| 备注 | note | text | |

### 3.4 统计口径（StatCard 行，6 卡）

| 卡 | 英文字段 | 口径公式 |
|---|---|---|
| 年度培训场次 | training_total | count(当年，状态≠已取消) |
| 培训完成率 | completion_rate | 已完成 / (未开始+进行中+已完成)，百分比 |
| 考核合格率 | pass_rate | sum(考核合格人数)/sum(实到人数)（考核方式=考试的场次） |
| 待复训（30天内） | retraining_due_30d | count(0≤下次复训日期-今日≤30) |
| 年度违章次数 | violation_total | count(当年) |
| 违章未纠正 | violation_open | count(状态=纠正中) |

### 3.5 健康度卡指标

- **ok**：violation_open=0 且 计划逾期未实施=0（计划日期<今日 且 状态∈{未开始,进行中}）。
- **warn**：violation_open>0 或 计划逾期未实施>0。
- **metric 文案模板**：`培训 {training_done}/{training_total} · 违章 {violation_total}（未纠正 {violation_open}）`；training_done=count(状态=已完成，当年)。

## 4. facilities 设备设施管理（S8）

> 体系定位：设备设施安全台账；检验/校验到期督办；安全设施完好性；操作规程库。域现状≈10%（全场最大空白；不对接 equipment 模块，本域=安全侧自有台账）。

### 4.1 表清单（2 张）

| kind | 表名 | 用途 |
|---|---|---|
| `equipment_ledger` | 设备设施台账表 | 设备/安全设施档案与状态（**主台账**） |
| `inspection_record` | 检验校验记录表 | 定期检验/校验/检定到期督办 |

### 4.2 设备设施台账表（主台账）字段

| Bitable 列名 | 目标字段 | 类型 | 枚举值 / 说明 |
|---|---|---|---|
| 设备编号 | equipment_no | text | 唯一 |
| 设备名称 | name | text | |
| 设备类别 | category | enum | 特种设备 / 安全设施 / 消防设施 / 监测报警 / 通用设备 / 其他 |
| 位置/区域 | location | text | |
| 责任部门 | department | multi_select | |
| 责任人 | owner | person | |
| 投用日期 | in_service_at | datetime | |
| 设备状态 | status | enum | 在用 / 停用 / 维修中 / 已报废 |
| 安全附件情况 | safety_note | text | 联锁/报警/泄放等 |
| 规程/说明书 | manual_file | attachment | 操作规程库锚点 |
| 备注 | note | text | |

### 4.3 检验校验记录表字段

| Bitable 列名 | 目标字段 | 类型 | 枚举值 / 说明 |
|---|---|---|---|
| 设备编号 | equipment_no | text | 关联台账 |
| 设备名称 | equipment_name | text | 冗余展示 |
| 检验类别 | category | enum | 定期检验 / 校验 / 检定 / 自查 |
| 上次检验日期 | last_inspected_at | datetime | |
| 检验周期（月） | cycle_months | text | 数字文本 |
| 下次检验日期 | next_inspected_at | datetime | 到期督办锚点（=上次+周期，可手改） |
| 检验机构 | agency | text | |
| 检验结果 | result | enum | 合格 / 不合格 / 限期整改 |
| 报告附件 | report_file | attachment | |
| 备注 | note | text | |

### 4.4 统计口径（StatCard 行，6 卡）

| 卡 | 英文字段 | 口径公式 |
|---|---|---|
| 设备总数 | equipment_total | count(状态≠已报废) |
| 特种设备 | special_equipment | count(类别=特种设备 且 状态≠已报废) |
| 检验逾期 | inspection_overdue | count(下次检验日期<今日) |
| 30天内到期 | inspection_due_30d | count(0≤下次检验日期-今日≤30) |
| 检验合格率 | inspection_pass_rate | 最近一次结果=合格 / 全部有记录设备 |
| 停用/维修中 | inactive_equipment | count(状态∈{停用,维修中}) |

### 4.5 健康度卡指标

- **ok**：inspection_overdue=0。
- **warn**：inspection_overdue>0。
- **metric 文案模板**：`设备 {equipment_total} 台 · 检验逾期 {inspection_overdue} · 30天内到期 {inspection_due_30d}`。

## 5. incidents 事故事件管理（S16）

> 体系定位：事故与事件的报告登记、分级判定、调查与原因分析；CAPA 跟踪闭环；案例警示教育。域现状≈40%（CAPA 闭环能力在系统、事故分级字段已预置——均不在本轮对接范围，本域=事故事件自有台账口径）。

### 5.1 表清单（2 张）

| kind | 表名 | 用途 |
|---|---|---|
| `incident` | 事故事件登记表 | 报告登记/分级/调查状态（**主台账**） |
| `capa` | CAPA 措施跟踪表 | 纠正预防措施闭环 |

### 5.2 事故事件登记表（主台账）字段

| Bitable 列名 | 目标字段 | 类型 | 枚举值 / 说明 |
|---|---|---|---|
| 事件编号 | incident_no | text | 唯一 |
| 发生日期 | occurred_at | datetime | |
| 事发地点 | location | text | |
| 事发部门 | department | multi_select | |
| 事件类别 | category | enum | 事故 / 未遂事件 / 异常事件 |
| 事件等级 | level | enum | 轻伤 / 重伤 / 死亡 / 财产损失 / 未分级 |
| 事件简述 | description | combined_text | |
| 伤亡人数 | casualty_count | text | 数字文本 |
| 直接损失（万元） | direct_loss | text | 数字文本 |
| 报告人 | reporter | person | |
| 报告日期 | reported_at | datetime | |
| 状态 | status | enum | 已报告 / 调查中 / 已结案 |
| 调查报告 | report_file | attachment | |
| 备注 | note | text | |

### 5.3 CAPA 措施跟踪表字段

| Bitable 列名 | 目标字段 | 类型 | 枚举值 / 说明 |
|---|---|---|---|
| 关联事件编号 | incident_no | text | 关联登记表 |
| 措施类型 | type | enum | 纠正 / 预防 |
| 措施描述 | description | combined_text | |
| 责任部门 | department | multi_select | |
| 责任人 | owner | person | |
| 完成期限 | deadline | datetime | |
| 完成日期 | completed_at | datetime | |
| 验证人 | verifier | person | |
| 验证结果 | verify_result | enum | 待验证 / 有效 / 无效 |
| 状态 | status | enum | 进行中 / 已完成 / 已逾期 |
| 备注 | note | text | |

### 5.4 统计口径（StatCard 行，6 卡）

| 卡 | 英文字段 | 口径公式 |
|---|---|---|
| 年度事件总数 | incident_total | count(当年) |
| 其中事故 | accident_count | count(类别=事故，当年) |
| 未遂事件 | near_miss_count | count(类别=未遂事件，当年) |
| 调查中 | investigating_count | count(状态=调查中) |
| CAPA 未闭环 | capa_open | count(状态∈{进行中,已逾期}) |
| CAPA 逾期 | capa_overdue | count(状态=已逾期) |

### 5.5 健康度卡指标

- **ok**：capa_overdue=0。
- **warn**：capa_overdue>0 或 investigating_count>0（存在超 30 天未结案的调查中事件时 warn 优先）。
- **metric 文案模板**：`今年事件 {incident_total} · 调查中 {investigating_count} · CAPA 未闭环 {capa_open}`。

## 6. 三态口径（四域统一，代码侧实现依据）

| 态 | 判定 | 端点 | 页面 | 健康度卡 |
|---|---|---|---|---|
| 未接入 | 域已注册但连接解析为空（DB 无活行且 `default_connection=None`） | `status="not_connected"`，stats=null、ledger=空分页 | StatusTag「未接入」+ EmptyGuide 建表引导（指向本文档表结构） | `inactive` + metric=`未接入`（可点跳页） |
| 已接入 | 连接存在且读取成功 | `status="live"`，stats/ledger 实数 | 正常出数 | `ok`/`warn` 按各域判据 + metric 模板 |
| 降级 | 连接存在但读取异常 | `status="degraded"`，errors 标注 | 降级 EmptyGuide（数据暂不可用） | `inactive` + metric=null（errors 标注） |

## 7. 明确不做（本文档范围）

- 不实际建表、不配连接、不写 handler/default_mappings（接入时另立项）。
- 责任制/投入/违章/检验/CAPA 等非主台账的页面附加区块（接入后扩展）。
- 与 equipment/HR/既有 CAPA 系统的数据对接。
