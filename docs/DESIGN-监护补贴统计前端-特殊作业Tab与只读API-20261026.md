# DESIGN — 监护补贴统计前端（特殊作业 Tab 与只读 API）

- 日期：2026-10-26
- 状态：R1 已交付；**当日更正：补贴已迁出独立页**（见下方迁移记录）
- 前置：监护补贴后端能力已全部就绪（`service/subsidy.py` 计算引擎、
  `service/subsidy_dept_ledgers.py` 四/五/六部台账三源、`subsidy_tools.py` Agent
  双源路由、`subsidy_dispatch.py` 每月 1 日 08:30 月报私发），前端零开发。

> **迁移记录（2026-10-26 晚，用户拍板）**：本文 §2 的「挂载 special-ops Tab」
> 方案执行后，用户澄清数据语义——**特殊作业台账=全厂特殊作业一览表（Bitable
> 报备审批数据）**；**平台作业票+提炼四/五/六部多维表格=监护补贴申报数据**，
> 二者不是一回事。据此补贴迁出为独立页：菜单「现场管理→监护补贴申报」，
> 路由 `/safety/subsidy`（a6f7954a）；special-ops 页恢复单组件原貌。
> 后端只读 API（§3）不受影响。特殊作业数据质量纠正后续另做（用户口径）。

## 1. 背景与目标

监护补贴统计目前唯一入口是安全 Agent 对话（预览 →「确认计算」→ Excel 回传会话），
另有每月 1 日自动私发台账三部门业务负责人（林锴彬/蔡嘉旺/孙长宽）。Web 侧无常驻
页面，安全员/管理层想翻历史月份只能翻聊天记录或等月报。

**目标**：在安全 Web 提供一个只读的补贴查询视图——选部门+年月，看到当月补贴
明细、按监护人汇总与待核对/跳过名单，口径与 Agent/月报完全一致。

**非目标**（3.0 安全 Web 只读监控口径延续）：

- 不做「生成 Excel / 确认计算」写动作——生成仍走 Agent 对话，月报已自动化私发；
- 不做补贴费率配置界面（费率属薪酬制度，改码内常量）；
- 不做移动端适配以外的额外视觉投入。

## 2. 信息架构（沿用 2026-10-26 会话已定方向）

**挂载点：安全管理 → 现场管理 → 特殊作业管理页（`/safety/special-ops`）加 Tab**，
不新增菜单项、不动 `menu-config.ts`。

页面从单表改造为 Tabs 骨架（照抄危化品页 `chemicals/page-client.tsx` 模式）：

```
/safety/special-ops
├─ page.tsx          服务端壳（force-dynamic，预取台账 stats 后透传）
├─ page-client.tsx   新增：PageHeader + <Tabs>
│   ├─ Tab1 特殊作业台账   → 现有 SpecialOpsManagement（内部 PageHeader 上提页级后移除）
│   └─ Tab2 监护补贴       → 新 SubsidyPanel
└─ 菜单/路由不变
```

理由（已在会话中确认）：补贴输入就是特殊作业票/台账，`SpecialOpsManagement`
本就有监护人列，数据血缘与受众（安全员）连续；现场管理组已有 8 项，独立菜单
导航噪音大于收益；后端 service 全在 safety 模块内复用成本最低。

## 3. 后端：只读 API（新 router，复用既有服务，不写业务逻辑）

新文件 `app/modules/safety/api/subsidy.py`，挂载到 `api/__init__.py`：

### 3.1 `GET /api/v1/safety/subsidy/sources`

返回可查询部门元数据（前端选择器数据源，避免前后端硬编码漂移）：

```json
{ "code": 200, "data": [
    { "department": "提炼工程四部", "source": "dept_ledger" },
    { "department": "提炼工程五部", "source": "dept_ledger" },
    { "department": "提炼工程六部", "source": "dept_ledger" }
] }
```

实现：遍历 `LEDGER_SOURCES`，零 IO。

### 3.2 `GET /api/v1/safety/subsidy/guardian-summary?department=&year=&month=`

主查询。参数校验复用 `subsidy_tools._validate_params` 口径；部门必须命中
`match_ledger_source`（**一期只接台账三部门**，未命中返回 404 风格错误并附
`hint: "该部门补贴统计请使用 AI 助手"`，见 §8 拍板点 A）。

实现链（全部既有代码，端点只做编排）：

```
fetch_ledger_rows(source)                        # Bitable 拉全表（五部 ~700 行，实测 <2s）
build_ledger_plan(source, rows, year, month)     # 纯函数：级别只认台账/未登按A证/同日去重
SubsidyService.calculate(plan.records, year, month)   # 纯函数：明细+按监护人汇总+统计
b_cert_adjusted_total(details)                   # B证 0.5 折算后实发合计（Excel K 列口径）
```

响应（`ApiResponse` 信封，明细 ≤ ~80 条/部门/月，不分页）：

```json
{ "code": 200, "data": {
    "department": "提炼工程四部", "year": 2026, "month": 9, "source": "dept_ledger",
    "stats": { "matched": 69, "guardians": 19, "total_amount": 7380.0,
               "adjusted_total": 7380.0, "unmatched": 0, "unmatched_people": 0, "skipped": 4 },
    "summaries": [ { "guardian_name": "吴家达", "guardian_level": "A证",
                     "hot_work": 848.0, "...": 0, "total": 848.0 } ],
    "details": [ { "guardian_name": "吴家达", "operation_type": "动火作业",
                   "operation_level": "一级", "ticket_no": "09-03 吴家达",
                   "start_time": "...", "end_time": "...", "adjusted_hours": 6.25,
                   "billing_units": 13, "billing_unit_label": "半小时",
                   "unit_price": 10.0, "subsidy_amount": 130.0, "remark": "扣除间隔1.67小时" } ],
    "unmatched": [ { "name": "罗利梅", "ticket_count": 2, "operation_types": ["受限空间"] } ],
    "skipped": [ { "ticket_no": "09-20 胡蕊", "ticket_type": "动火作业", "reason": "时间段无法解析" } ]
} }
```

- `total_amount` 为折算前合计、`adjusted_total` 为 B 证 0.5 折算后实发合计
  （与月报摘要卡/Excel K 列同口径），两个都给，前端并列展示；
- B 证明细金额按 Excel 口径在**前端不折**、汇总区展示折算值（与 Agent 生成
  结果一致性优先：明细=折算前，卡片区=折算后）；
- 依赖注入照抄 `special_operation_reports.py`：`db: AsyncSession = Depends(get_db)`
  + `current_user: CurrentUser | None = Depends(get_current_user)`（台账路径实际
  不用 db，签名保持一致性便于二期平台源接入）。

### 3.3 测试

- `test_subsidy_api.py`：sources 顺序稳定；guardian-summary 台账路径（mock
  `fetch_ledger_rows`）校验 stats/明细/待核对结构；非法年月/未命中部门错误分支；
  与 `build_ledger_plan` 的口径回归锚（用 §4 同一批断言值）。

## 4. 前端组件设计

### 4.1 文件落点

| 文件 | 动作 | 说明 |
|---|---|---|
| `app/(dashboard)/safety/special-ops/page-client.tsx` | 新增 | Tabs 骨架（抄 chemicals 模式） |
| `app/(dashboard)/safety/special-ops/page.tsx` | 改造 | 渲染 page-client，预取逻辑不变 |
| `components/safety/SpecialOpsManagement.tsx` | 微调 | 移除内部 PageHeader（上提页级），其余不动 |
| `components/safety/SubsidyPanel.tsx` | 新增 | 补贴查询面板 |
| `lib/api/safety/subsidy.ts` | 新增 | 两个 API 客户端函数（`apiGet` 模式） |
| `types/safety/subsidy.ts` | 新增 | 响应类型 |

### 4.2 SubsidyPanel 布局（ui-kit，本地 state + fetch，不迁 react-query）

```
PageHeader（页级，page-client 提供）
└─ SectionCard「监护补贴查询」
   ├─ 筛选行：部门 Select（来自 /sources）＋ 月份 DatePicker.MonthPicker（默认上月）
   │          ＋ 查询按钮（自动触发，切换即查）
   ├─ StatCard 行 ×5：计入条数 / 监护人数 / 补贴总额(折算后) / 待核对 / 跳过
   │   （折算前合计放 StatCard 副标题小字：A/B证混合时两数不同）
   ├─ Table「按监护人汇总」：姓名 / 级别 / 动火 / 登高 / 受限 / 临时用电 /
   │   抽堵盲板 / 动土 / 断路 / 吊装 / 合计（列头短文案，空列隐藏）
   ├─ Table「明细记录」：监护人 / 级别 / 作业类型 / 作业级别 / 票号(台账行标识) /
   │   开始 / 结束 / 实算时长 / 计费(13×半小时) / 金额 / 备注 —— 默认分页 20
   └─ SectionCard「待核对与跳过」（有数据才渲染）
       ├─ 未登级别名单：StatusTag(warning) + 姓名 + 行数 + 类型
       └─ 跳过清单：StatusTag(default) + 行标识 + 类型 + 原因
加载失败/空数据 → EmptyGuide（文案注明「台账当月无登记或生成失败，生成 Excel
请使用 AI 助手」）
```

视觉 token 对齐 `SpecialOpsManagement` 的 `UI` 常量（ink/charcoal/slate/steel），
金额列 `fontVariantNumeric: 'tabular-nums'`。

### 4.3 交互细节

- 部门/月份切换即查询（防抖 300ms），loading 用 Table 自带 spin；
- 月份上限：不早于 2026-07（三台账最早数据），不晚于当月；
- 无新增权限码：页面在 `safety:*:read` 下自然可见，API 沿用 `get_current_user`。

## 5. 数据流与性能

- 每次查询实时拉 Bitable（与 Agent/月报同一数据面，**不落库不加缓存**——月度
  低频查询，台账行级实时性即所见即所得，缓存反而引入口径陈旧风险）；
- 五部 704 行全表拉取实测 <2s，`build_ledger_plan` + `calculate` 毫秒级纯函数；
- 二期若接平台源部门（窗口拉平台票较慢），再考虑结果缓存。

## 6. 权限与安全

- 页面/API 均在既有 `safety:*:read` 体系内，无新权限码、无写面；
- 补贴金额属敏感人事数据，页面不加导出/打印按钮（打印走浏览器原生），
  分享靠月报私发链路（收件人名单 `SUBSIDY_DM_OVERRIDES` 已收口）。

## 7. 分期

| 期 | 内容 | 状态 |
|---|---|---|
| R1（本设计） | Tabs 骨架 + 台账三部门只读查询（§3-§4 全量） | 待拍板后实施 |
| R2（可选） | 平台源部门接入 Web（±1 月窗口拉票+按监护人部门归集+结果缓存）；月度趋势小图；「去 AI 助手生成」深链 | 未排期 |

## 8. 拍板点（默认值可反驳）

- **A. 一期只接台账三部门？** 默认：是。平台源部门 Web 查询慢（整月窗口拉
  8 类票）且按监护人部门归集语义复杂，一期在错误提示里引导用 AI 助手。
- **B. 金额展示口径？** 默认：明细折算前、汇总卡并列展示折算前/后（B 证 0.5），
  与 Excel/月报一致。
- **C. 默认查询参数？** 默认：上次访问部门（localStorage）→ 无记录时提炼四部；
  月份默认上一完整自然月。
- **D. SpecialOpsManagement 内部 PageHeader 上提页级？** 默认：是（Tab 页内
  出现两行大标题不成立）。若想零侵入，可保留 Tab1 组件页头、页级只放面包屑。

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| Bitable 凭据失效/网络抖动 → 查询失败 | 端点异常转 `ApiResponse(code=502, message="监护台账拉取失败…")`，前端 EmptyGuide 引导重试 |
| 台账登记笔误（如 2056 年）被用户当 bug 报 | 明细/跳过原因透传引擎 remark，待核对区文案注明「以台账登记为准，修正请改台账」 |
| 三部门口径差异引发理解偏差 | 面板顶部一行说明：级别以台账登记为准；六部无级别列全员按 A 证暂计 |
| SpecialOpsManagement 改动引入回归 | 只动 PageHeader 一处；现页面无组件测试，靠手工回归 + 现有数据流不变 |
