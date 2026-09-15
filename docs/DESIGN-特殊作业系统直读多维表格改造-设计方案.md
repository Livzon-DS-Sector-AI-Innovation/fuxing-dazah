# 特殊作业系统「直读多维表格」改造 - 设计方案

> 日期：2026-09-11
> 状态：草案，3 个决策点待拍板（见第 3 节）
> 对标：DESIGN-隐患系统直读多维表格改造-实施记录.md（隐患域，已实施）
> 前序：DESIGN-多维表格作为唯一数据库可行性评估.md 第 4 节 分域矩阵
> 代码基线：fuxing-dazah @ 47c0b89（feature/warehouse-module）

---

## 0. 一句话结论

特殊作业日报现在是「Bitable 事件 -> 平台库镜像 -> 日报读镜像」，与隐患改造前的结构完全同构。
按隐患的办法摘掉镜像后：日报改为执行时直读「全厂特殊作业一览表」，结果只推飞书群，
不再维护 SpecialOperationReport 的 Bitable 镜像行。

与隐患的差异集中在 3 处，需先拍板：派生字段归宿、定点拉取 vs 轮询、created_at 兜底语义。

---

## 1. 背景

### 1.1 隐患那次改造摘掉了什么

改造前（双向写 + DB 镜像）：

    飞书 Bitable --事件--> 平台库镜像(DB) --> Web页/定时任务/Agent
         ^                        |
         +-- 平台回写(AI字段/督办等级/编号) --+   <- 两个写者打架

改造后（引自实施记录 3.6 / 3.7 最终态）：

    飞书 Bitable（唯一数据源）
      |-- 读：轮询 + Agent 工具 + 通报/催办
      |-- 写：只回写 Bitable（AI字段/督办等级/编号/催办进展）
      +-- 不写：平台库 -- 全部由 event_sync_enabled() 闸门关闭

    平台库：独立运行，只服务 Web 隐患页面自己，不与多维表格同步

四个被摘掉的步骤：事件驱动镜像 upsert、每日差异对账（bitable_diff_sync.py 整体删除）、
漏单恢复（catch_up.py 闸门）、平台到 Bitable 回写（service/hazard.py 三处收口）。

回滚手段：SAFETY_HAZARD_EVENT_SYNC_ENABLED / SAFETY_HAZARD_CATCHUP_ENABLED 置 true 重启。

### 1.2 特殊作业的同构链路（证据）

    飞书「全厂特殊作业一览表」
      app_token=Lxn3bKHo9aVc7fsSp6YcLBgdnKh  table=tblgcMQZ1mzsEolK
      （bitable_config/registry.py:957  key="special_op"）
            |
            | 1. WS 事件 feishu/special_op_bitable_handler.py:94 _handle_upsert
            |    +- client.get_record(record_id)  <- 单条读 4.4-5.6 秒，1254607 高发点
            v
    平台库 SpecialOperationReport (source='bitable')   <- 镜像表
            | + RiskAssessmentEngine.assess() 派生字段落库
            v
    日报(08:00/17:00) / Agent 查询 / API / 台账页面

关键判断：_handle_upsert 里「事件到了再 get_record 单条重拉」的写法，与隐患
bitable_handler._download_and_save_attachments 是同一个反面模式。可行性评估实测该接口
4.4-5.6 秒/次、1254607 Data not ready 出现 3,005 次。这条路径本身就该拆。

---

## 2. 现状盘点

### 2.1 镜像链路：8 个环节

| # | 环节 | 位置 |
|---|---|---|
| 1 | WS 事件，upsert 镜像 + 软删 | feishu/special_op_bitable_handler.py:94 / :150 |
| 2 | 08:00 全量对账 | scheduler.py:521 -> service/special_operation_daily_report.py:1222 sync_from_bitable() |
| 3 | 17:00 增量补漏 | scheduler.py:528 -> :1349 check_and_sync_incremental() |
| 4 | API 手动同步 / 手动生成 | api/special_operation_daily_report.py:33 /sync、:50 /generate |
| 5 | 日报取数（读镜像） | :1323 get_reports_by_date() |
| 6 | Agent 查询（读镜像） | business_agent/tools/read_tools.py:1588 query_special_op_records |
| 7 | API 查询（读镜像） | /special-operation-daily-report/stats、/records |
| 8 | 前端（读镜像） | SpecialOpsLedger.tsx 等 4 个组件 |

### 2.2 字段分层（决定改造难点）

| 层 | 字段 | 去向 |
|---|---|---|
| A. Bitable 原始字段（约 35 列） | operation_type / operation_level / department / location / work_description / planned_start_time / planned_end_time / work_duration_hours / personnel_type / fire_work_method / height_work_method / work_height / lifting_weight / contractor_name / has_other_operations / other_operation_types / is_weekend_holiday / is_national_holiday / holiday_period / report_type / initiator_department / initiator_name / approver_type / safety_approver_name / approver_name / approval_no / work_plan_url / work_scheme_url / approved_permit_url / submitted_at / completed_at / approval_node | 直读时内存映射，来源不变（map_bitable_fields 可整体复用） |
| B. 平台派生字段（7 列） | daily_risk_level / daily_risk_reason / inferred_operation_types / inferred_operation_detail / is_excluded / exclusion_reason（来自 RiskAssessmentEngine）、daily_report_date（来自 generate_and_push:1544） | 见第 3 节决策点 1 |
| C. 平台自有业务字段 | status / risk_level / is_critical / 各 is_critical_* 字段 / 手动报备（source='manual'） | 不动，与镜像无关 |

好消息：RiskAssessmentEngine.assess()（:166）是纯属性读取的 classmethod，
只读 operation_type / work_description / location / department / personnel_type /
work_duration_hours 等，不碰 id、不查库。换成视图对象即可，规则一行不用改。

### 2.3 派生字段的消费方

| 消费方 | 位置 | 用法 |
|---|---|---|
| 日报 | special_operation_daily_report.py（20 处） | 按 daily_risk_level 分 high/medium/low、按 is_excluded 排除 |
| API | api/special_operation_daily_report.py（3 处） | /stats、/records 序列化 |
| Agent | read_tools.py（7 处） | query_special_op_records 按 daily_risk_level 等筛选 |
| 台账 | service/special_operation_report.py（6 处） | 手动报备也跑同一引擎（:210），与镜像无关 |
| Schema | schemas/risk_reports.py、schemas/special_op_daily.py | 出参定义 |

---

## 3. 三个决策点（待拍板）

### 决策点 1：派生字段（B 层 7 列）的归宿

镜像摘掉后，这 7 列没有地方落。三个选项：

| 选项 | 做法 | 优点 | 代价 |
|---|---|---|---|
| A. 全程内存计算（推荐） | 直读后在视图对象上现调 assess()，只用于本次日报/查询，不落库 | 与隐患「平台库不再落镜像」一致；零 schema 变更；引擎纯函数、开销可忽略 | Agent 与 /records 按 daily_risk_level 筛选时需拉当日全量加内存过滤；daily_report_date（去重标记）失去落点 |
| B. 回写 Bitable 新列 | 在 Bitable 加「日报风险等级(AI)」等列，直读路径回写 | 风险等级在飞书侧可见可筛；不再依赖平台库 | 需业务同意加列；受单表不可并发写约束（需串行 + 0.5s 间隔） |
| C. 混合 | 日报内存算；台账/API 保留 DB 存量只读 | 改动面最小 | 新旧数据口径分裂，长期要还技术债 |

推荐 A。理由：日报场景天然是「算完就发」，不需要持久化；查询场景按日期范围拉取
（当日通常几十条），内存过滤成本可接受。若业务后续要在飞书里看到风险等级，再增量做 B。

需确认：daily_report_date（日报去重标记）失去落点后，「同一日报不重复推送」靠什么保证？
建议由调度器的 scheduler_job_runs（已持久化去重/重试/补发）承接，它本来就是唯一来源。

### 决策点 2：定点拉取 vs 5 分钟轮询

| 选项 | 做法 | 优点 | 代价 |
|---|---|---|---|
| A. 定点拉取 + Agent 直读（推荐） | 日报 08:00/17:00 各拉一次 Bitable；Agent 查询直读；不新增常驻循环 | 与特殊作业「定点任务」语义匹配；零额外读压力；无新进程 | 台账页若保留读库则数据停滞（同隐患 Web 决策） |
| B. 照抄隐患轮询 | 新增 special_op_direct/loop.py，5 分钟拉一次 | 镜像保持新鲜，台账页可继续用 | 多一个常驻循环；对 Bitable 持续读压力；日报本身不需要 |
| C. 双写过渡 | 保留事件镜像做缓存，日报改直读 | 页面不停滞 | 复杂度和读写冲突不降，等于没摘干净 |

推荐 A。隐患用轮询是因为督办计算是连续语义（每 5 分钟扫一遍）；
特殊作业日报是定点语义，没有轮询的理由。

需确认：SpecialOpsLedger 台账页是否接受数据停滞？（隐患的对应决策是「Web 页面保留、
数据库独立运行、不与多维表格联动」，用户已确认接受。）

### 决策点 3：created_at 兜底语义

现状（_new_ops_section._new_ts，:780）：

    def _new_ts(r):
        if r.submitted_at: return r.submitted_at   # <- Bitable「发起时间」
        if r.created_at:   return r.created_at     # <- DB 行创建时间 = 首次同步时刻
        return datetime.min.replace(tzinfo=UTC)

直读后没有 DB 行，created_at 不存在。三个选项：

| 选项 | 做法 | 说明 |
|---|---|---|
| A. 发起时间为空则不纳入新增（推荐兜底） | 去掉 created_at 分支 | 最保守，不臆造时间；需先实测「发起时间」空值率 |
| B. 用 Bitable 系统字段「创建时间」 | 需 automatic_fields=true 读取 | 语义最接近「首次出现」，待实测可得性 |
| C. 用进程/Redis 记录「首次见到该记录」的时刻 | 把镜像语义搬进 Redis | 等价于换个地方存镜像，不推荐 |

推荐 B 优先、退化 A：先实测 Bitable 系统字段是否可读、以及「发起时间」空值率；
不可得则用 A，并在日报里标注「N 条记录缺发起时间，未计入新增」。

需实测（只读脚本）：_dsh_so_field_nulls.py，统计「发起时间」空值率加系统字段可读性。
---

## 4. 改造方案（按推荐值起草）

以下按第 3 节的推荐值（A / A / B 退化 A）展开。若决策改动，对应小节同步调整。

### 4.1 目标链路

    飞书「全厂特殊作业一览表」（唯一数据源）
      |-- 读：日报 08:00/17:00 直读 + Agent 查询直读 + API 直读
      |-- 写：（默认不写；仅决策点 1 选 B 时回写风险等级列）
      +-- 不写：平台库镜像

    平台库：
      |-- SpecialOperationReport(source='manual')  -- 手动报备业务，照常
      +-- SpecialOperationReport(source='bitable') -- 停止写入，存量保留只读（同隐患 Web 决策）

### 4.2 新增 service/special_op_direct/

照抄 service/hazard_direct/ 的结构与手法：

| 新文件 | 对应隐患侧 | 职责 |
|---|---|---|
| __init__.py | 同 | 包入口（PEP 562 惰性加载） |
| config.py | hazard_direct/config.py | 开关与参数（全 env，默认关闭） |
| bitable_repo.py | hazard_direct/bitable_repo.py | 直读：按日期区间查询 / 复用 map_bitable_fields / SpecialOpView 视图对象 / RiskAssessmentEngine 适配 / per-record 锁 |
| daily.py | ai_analysis.py 等 | 直读、风险判定、AI 分析、渲染、推送 的新编排（复用 ReportBuilder / AIAnalyst） |

SpecialOpView：只承载 2.2 节 A 层字段加引擎派生结果，字段名与 SpecialOperationReport
同名，以便 RiskAssessmentEngine / ReportBuilder / AIAnalyst 零改动复用。需补 id
（用 feishu_record_id 兜底）和 created_at（见决策点 3）。

### 4.3 日报改造

generate_and_push（:1509）当前链路：get_reports_by_date() 读库、分组、AI、渲染、
标记 daily_report_date、commit、推送。

改为 special_op_direct.daily.run(target_date, mode)：
直读 Bitable、内存映射为 SpecialOpView、assess()、分组、AI、渲染、推送。
去掉两处 DB 写：r.daily_report_date = target_date（:1544）和前置 commit（:1556）。

### 4.4 旧路径闸门（对齐隐患 event_sync_enabled()）

| 位置 | 改动 |
|---|---|
| feishu/special_op_bitable_handler.py | handle_special_ops_record_changed 开头加 if not event_sync_enabled(): return |
| scheduler.py:521 | sync_from_bitable() 前置闸门 |
| scheduler.py:528 | check_and_sync_incremental() 前置闸门 |
| api/special_operation_daily_report.py:33 /sync | 前置闸门（返回「已关闭」而非静默） |
| api/special_operation_daily_report.py:50 /generate | 去掉「先 sync_from_bitable」；改调 direct 路径 |

### 4.5 Agent / API / 前端归属

| 面 | 处理 |
|---|---|
| Agent 工具 query_special_op_records | 切直读 Bitable（对齐隐患 query_hazards）；筛选/分页在应用侧实现 |
| API /stats、/records | 切直读；/records 需保留分页语义（应用侧切片） |
| 前端 4 个组件 | 决策点 2 确认后定：接受停滞（推荐）或另开直读接口 |
| 作业票审核 | 不在范围：走外部平台 API（192.168.5.7:9550），与 Bitable 无关 |
| 台账/报备 CRUD（api/special_operation_reports.py） | 不动：source='manual'，平台自有业务 |

### 4.6 开关与回滚

    SAFETY_SPECIAL_OP_DIRECT_ENABLED=false        # 总开关
    SAFETY_SPECIAL_OP_EVENT_SYNC_ENABLED=false    # 旧事件镜像（对齐隐患命名）
    SAFETY_SPECIAL_OP_SYNC_JOB_ENABLED=false      # 08:00 全量 / 17:00 增量
    SAFETY_SPECIAL_OP_WRITEBACK_RISK=false        # 决策点 1 选 B 时才需要

回滚：任一开关改回 false/true 重启即可，无数据副作用（镜像表存量不删）。
---

## 5. 不在本次范围

| 项 | 说明 |
|---|---|
| SpecialOperationPermit / SpecialOperationPersonnel | 平台自有表，非 Bitable 镜像 |
| 手动报备 CRUD + 审批流（api/special_operation_reports.py） | source='manual'，平台业务 |
| 作业票审核（workticket_review/） | 外部平台 API |
| 关键风险作业报备（key_risk_operation_report.py） | 独立域，另有设计文档 |
| 镜像表存量数据 | 保留只读，不删、不回填 |

---

## 6. 验收清单（初稿）

| # | 项 | 判据 |
|---|---|---|
| 1 | 直读日报与镜像日报同输入同输出 | 取历史某日，两条路径生成的 Markdown 逐字比对 |
| 2 | 派生字段口径一致 | daily_risk_level / is_excluded 双路径全量比对，零差异 |
| 3 | 附件处理 | 不调 get_record，直接用 records/search 结果里的元数据（照抄隐患 3.3） |
| 4 | 零回写验证 | 探针桩替换 SafetyBitableClient.update_record，跑直读路径后非写入路径调用数为 0（照抄 verify_web_path_no_bitable_write.py） |
| 5 | Agent 查询直读 | query_special_op_records 与镜像表全量交叉核对 |
| 6 | 旧路径闸门 | 关闭后事件处理器 / 同步任务 / /sync 均不产生 Bitable 调用 |
| 7 | 推送幂等 | 重启/重试不重复推群（依赖 scheduler_job_runs） |
| 8 | 回滚演练 | 开关切回后旧链路恢复，镜像表正常写入 |

---

## 7. 风险与遗留

| 风险 | 说明 | 缓解 |
|---|---|---|
| 飞书不可用等于日报发不出 | 隐患 2.3 已警示：直读把 Bitable 的不可用搬进任务路径 | 调度器补发窗口（08:00-16:30 / 17:00-23:30）已覆盖；失败告警 |
| 「发起时间」空值率未知 | 决策点 3 的兜底依赖它 | 先跑只读实测脚本 |
| 台账页数据停滞 | 同隐患 Web 决策 | 需用户确认接受 |
| Bitable 单条读 4.4-5.6 秒 | 直读若逐条取会慢 | 一律走 records/search 批量（隐患 3.3 的结论） |
| 单表 20,000 条上限 | 当前约 2,033 条，安全 | 加监控，接近时归档 |

---

## 附：与隐患改造的对照速查

| 维度 | 隐患（已实施） | 特殊作业（本方案） |
|---|---|---|
| 数据源 | 「隐患登记表」Bitable | 「全厂特殊作业一览表」Bitable |
| 摘掉的镜像 | hazard_reports + hazard_identifications | SpecialOperationReport(source='bitable') |
| 平台派生字段 | AI 字段回写 Bitable（Bitable 有对应列） | 风险等级内存算（Bitable 无对应列），差异点 |
| 触发方式 | 5 分钟轮询（连续语义） | 定点 08:00/17:00，差异点 |
| Agent 工具 | query_hazards / query_hazard_stats 直读 | query_special_op_records 直读 |
| Web 页面 | 保留读库、数据停滞 | 同（待确认） |
| 回滚开关 | SAFETY_HAZARD_EVENT_SYNC_ENABLED | SAFETY_SPECIAL_OP_EVENT_SYNC_ENABLED |
| 新增包 | service/hazard_direct/ | service/special_op_direct/ |
---

## 8. 决策落定（2026-09-11 质询后更新）

本节记录质询后确定的决策，与第 3 节的「推荐值」有出入时**以本节为准**。完整规格见 `.scratch/special-op-direct/spec.md`。

| # | 决策点 | 最终取值 | 与第 3 节推荐 |
|---|---|---|---|
| 1 | 改造范围 | 日报链路 + Agent 查询工具切直读；后端 API 与前端 4 个组件继续读镜像表（存量冻结） | 同推荐 A |
| 2 | 派生字段归宿 | **新增 1 列「日报风险等级（AI）」并回写**；其余 6 个派生量纯内存计算 | **改为 B（部分）**，原推荐 A |
| 3 | 拉取方式 | 定点拉取（08:00 / 17:00）+ Agent 查询实时直读；不加常驻轮询 | 同推荐 A |
| 4 | 灰度与回滚 | 开关默认关闭，旧路径保留并加闸门，一键回滚 | 同推荐 A |
| 5 | created_at 兜底 | 回退 Bitable 系统字段「创建时间」；取不到则不计入新增并标注条数 | 同推荐 B 退化 A |
| 6 | 验收标准 | 纯函数单测 + 双路径逐日比对 + 零回写探针 + ruff/mypy/pytest + dry-run 冒烟 | 同推荐 B |
| 7 | 回写列数 | 只 1 列（日报风险等级） | 原推荐 4 列，已收窄 |
| 8 | 建列方式 | 幂等脚本，dry-run 先确认，缺失才建 | 同推荐 A |
| 9 | 回写失败 | 不阻塞日报推送；warning + 告警；下轮补写 | 同推荐 A |
| 10 | 新列规格 | 列名「日报风险等级（AI）」，单选，选项 高风险 / 中风险 / 低风险 | 新增决策 |
| 11 | Agent 取值 | 有值读列；为空则查询时现算，不回写 | Q11 选项 B |

### 新增列规格

| 项 | 值 |
|---|---|
| 列名 | 日报风险等级（AI） |
| 类型 | 单选（Bitable 字段类型 3） |
| 选项 | 高风险 / 中风险 / 低风险 |
| 值映射 | high 对应 高风险，medium 对应 中风险，low 对应 低风险 |

### 开关命名

    SAFETY_SPECIAL_OP_DIRECT_ENABLED=false
    SAFETY_SPECIAL_OP_EVENT_SYNC_ENABLED=false
    SAFETY_SPECIAL_OP_SYNC_JOB_ENABLED=false
    SAFETY_SPECIAL_OP_WRITEBACK_RISK_ENABLED=false

### 已知行为

- 新增列每天只刷新两次（08:00 / 17:00），记录被编辑后列内可能保留旧判定，陈旧窗口最长约 9 小时；空值记录走现场判定
- 直读把飞书可用性引入日报任务路径，由调度器补发窗口（08:00 至 16:30、17:00 至 23:30）与失败告警承接
