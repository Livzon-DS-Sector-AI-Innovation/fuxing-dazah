# Spec：仓储 V2.0 分期C「对账与报表」（两阶段）

> 来源：`docs/仓储V2.0设计方案.md` Phase C + 本质询确认（2026-09-16，两轮 8 项决策，见文末质询记录）。
> 分支：feature/warehouse-module；功能目录：.scratch/warehouse-v2-phase-c/
> 前置：分期A（3690054/0831a2b/3517bf1）与分期B（da0028c/16b9f38）已交付。

## 需求质询记录（两轮 8 项决策）

1. 阶段切分 = **先报表后对账**：阶段一报表中心（纯本地数据）+ NL 导出 + 晨报（仅 Web）；阶段二同步对账中心（真实 Bitable 比对）
2. 对账深度 = **真实 Bitable 比对**（用户明确选重方案）
3. 对账对象 = **库存台账比对**（本地三张库存表 ↔ 飞书 material_stock 台账）
4. 冲突裁决 = **仅展示不覆盖**（本地为事实源，系统不做覆盖动作）
5. 对账触发 = **仅手动**（不做定时任务）
6. NL 导出 = **LLM 解析 + 降级**（解析失败降级当前筛选条件导出）
7. 报表范围 = **四块全做**（出入库月报/库存周转率排行/物料消耗排名/当前库存报表）
8. 晨报渠道 = **仅 Web**（不接飞书推送）

## Problem Statement

分期 A/B 之后，仓储数据的主链路（登记→库存→飞书写回）与智能能力已闭环，但三个"看清全局"的能力缺失：①本地库存与飞书台账之间的同步一致性靠人肉抽查，写回失败/人工改表无从发现；②管理者没有固定口径的月度报表，每次都要现场拼查询；③导出依赖手工筛选，不会用系统的人拿不到数据。

## Solution

**阶段一（报表中心）**：新增"报表中心"一级菜单，四个报表——①出入库月报（按月聚合入库/出库汇总与物料明细，月份切换）；②库存周转率排行（出库量/平均库存，升序降序切换）；③物料消耗排名（近 30 天出库 Top）；④当前库存报表（全量库存快照表）。每个报表支持导出 Excel（openpyxl）。AI 自然语言导出：输入"导出 9 月出库大于 100 的物料"→ LLM 解析为筛选条件 JSON（回显解释）→ 按条件导出；解析失败降级为当前页面筛选条件导出。每日晨报：08:00 任务聚合（异常 open 数/补货建议 pending 数/昨日出入库/低库存 Top）存入晨报表，报表中心晨报 Tab 查看历史。

**阶段二（对账中心）**：新增"对账中心"菜单——手动触发库存台账对账：本地三张库存表（按物料编码+批次聚合）与飞书 `material_stock` 台账（Bitable 分页拉全量，复用既有 adapter 限流）逐条比对，结果四态（match/missing_in_feishu/mismatch/missing_local）落库，页面展示比对运行历史与结果明细（mismatch 双边值并排），**仅展示不覆盖**。对账运行记录与明细持久化，支持按运行批次与状态筛选。

## User Stories

阶段一 · 报表中心

1. As a 仓库管理员, I want 打开报表中心选择月份查看出入库月报（汇总+物料明细）, so that 月度盘点与汇报有现成数据
2. As a 仓库管理员, I want 月报可导出 Excel, so that 离线归档与上报
3. As a 管理者, I want 查看库存周转率排行（升序/降序切换）, so that 识别积压与高频物料
4. As a 仓库管理员, I want 查看近 30 天物料消耗排名, so that 掌握主耗物料
5. As a 仓库管理员, I want 查看当前库存全量报表并导出, so that 随时提供完整台账
6. As a 仓库管理员, I want 在导出框输入自然语言（"导出 9 月出库大于 100 的物料"）并看到解析回显, so that 不学筛选器也能拿数据
7. As a 仓库管理员, I want LLM 解析失败时自动降级为当前筛选条件导出, so that 功能永远可用
8. As a 仓库管理员, I want 每天早上看到晨报（异常/建议/昨日出入库汇总）, so that 上班即掌握全局
9. As a 系统, I want 晨报每日 08:00 定时生成, so that 历史可回溯

阶段二 · 对账中心

10. As a 仓库管理员, I want 手动触发一次库存台账对账（本地 ↔ 飞书 material_stock）, so that 主动校验两边一致性
11. As a 仓库管理员, I want 对账结果按四态分类（一致/飞书缺失/数值不一致/本地缺失）, so that 快速定位问题
12. As a 仓库管理员, I want mismatch 行并排展示本地值与飞书值, so that 人工核对差异
13. As a 仓库管理员, I want 查看历次对账运行记录（时间/总数/各态数量）并回看明细, so that 追踪一致性趋势
14. As a 系统, I want 对账拉取飞书数据时复用既有 Bitable 适配器限流, so that 不触发飞书频控
15. As a 仓库管理员, I want 对账过程中飞书 API 失败时看到明确错误且结果不落半截, so that 不被脏数据误导

## Implementation Decisions

- **模块边界**：warehouse 模块内新增 `reports.py`（报表聚合）、`reconciliation.py`（对账引擎）、`morning_report.py`（晨报）服务文件 + `web_report_router`；前端新增报表中心/对账中心页面与组件
- **阶段一 schema**：两张新表——`daily_briefings`（brief_date 唯一/content JSONB/created_at）与无报表落表（报表实时聚合，不落库）；对账相关表在阶段二（`sync_check_runs` + `sync_check_results`）
- **报表口径**：月报=按北京时间自然月聚合 movements（inbound/outbound 分组：笔数/数量/按物料明细）；周转率=近 30 天出库量 ÷ 平均库存（期初+期末/2，期初用最近日快照，无快照回退当前库存），排行取周转率或出库量 Top N；消耗排名=近 30 天 outbound 按物料 Top N；当前库存报表=stocks 全量（含批次/库位/效期列）
- **Excel 导出**：openpyxl（已有依赖）后端生成 StreamingResponse（xlsx），文件名 UTF-8 编码；NL 解析复用 agent LLM 客户端（场景 `warehouse_nl_export` 注册 ai_config），输出 JSON 筛选条件（material keyword/category/direction/month/qty 比较符+值），白名单字段校验，解析失败→400 带降级标记，前端回退当前筛选
- **晨报**：`daily_briefings` 表 + 08:00 FIXED_TIME 任务（窗口守卫同既有模式）+ GET 端点（列表/详情）；内容聚合：昨日出入库（量/笔数）、异常 open 分类计数、补货建议 pending 数、低库存 Top5、临期 Top5；仅 Web 展示
- **对账引擎（阶段二）**：`reconciliation.py`——`run_stock_reconciliation(db, user)`：①本地侧 stocks 按 (material_code, batch_no) 聚合；②飞书侧 `WarehouseBitableAdapter.query_records("material_stock")` 分页拉全量（复用 adapter 限流与字段映射，飞书字段名从 bitable_schema fields 取）；③按键匹配分四态；④写 sync_check_runs（总数/各态计数/耗时）+ sync_check_results 明细（仅差异行：missing_in_feishu/missing_local/mismatch 存双边值 JSONB）；⑤失败（飞书 API 异常）整体抛出不落半截，run 记 failed
- **对账权限**：warehouse:reports:read（报表）、warehouse:reconciliation:read（查看）/ warehouse:reconciliation:run（触发对账），注册 PermissionDef
- **对账前端**：对账中心页（运行历史表 + "发起对账"按钮 + 运行详情抽屉按状态分组展示，mismatch 双边并排）；仅手动触发（无定时任务）
- **NL 导出入口**：报表中心页顶部导出卡片；报表各表格自带"导出 Excel"按钮（常规导出走后端同端口带筛选参数）

## Testing Decisions

- 接缝沿用：后端 `tests/warehouse/`（auth_client 路由层）；前端 vitest 组件层（mock lib/api 与 actions）
- 报表测试：固定 movements/stocks 造数 → 断言月报聚合/周转率/消耗排名；Excel 导出断言响应头与状态（内容抽查）
- NL 解析测试：monkeypatch LLM 解析函数 → 断言筛选条件应用；解析抛错 → 断言降级路径
- 晨报测试：造数 → 触发生成 → 断言 content 各字段与幂等（同日重生成覆盖）
- 对账测试：monkeypatch adapter.query_records 返回构造的飞书行 → 断言四态分类与落库；adapter 抛错 → 断言 run=failed 且无半截 results
- 验收口径：mypy/ruff 对照基线零新增

## Out of Scope

- 对账覆盖飞书写回（不覆盖飞书数据）；movement 流水级对账与库存台账对账（仅做库存台账，用户选定）
- 对账定时任务（仅手动）
- 晨报飞书推送（仅 Web）
- 周转率的多口径切换（固定近 30 天出库/平均库存）
- 报表订阅、PDF 导出、跨年对比

## Further Notes

- 环境约束沿用 CLAUDE.local.md；迁移集中在阶段一首票（daily_briefings）与阶段二首票（sync_check_runs/results）
- 飞书 material_stock 字段映射在实现时从 bitable_schema.py 的 fields 定义确认（spec 不锁定字段名）
- 工作区他人 safety 改动不触碰；每阶段末审查 + 提交
