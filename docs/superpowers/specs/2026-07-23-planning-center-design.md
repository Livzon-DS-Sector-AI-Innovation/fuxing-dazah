# 生产计划中枢设计文档

**日期：** 2026-07-23
**版本：** v1.0
**状态：** 已确认

---

## 一、概述

### 1.1 目标

在生产管理模块中新增"计划中枢"功能，实现生产计划与执行解耦。包含三个 Tab：需求池、计划单、计划排程。

### 1.2 核心设计理念

**合约式（Contract）解耦 + 分层承诺模型：**

- 计划层负责决定"生产什么、生产多少、何时生产"
- 执行层（Batch）负责兑现生产承诺
- Batch 在 `draft/scheduled` 阶段受计划控制；一旦 `released`（下达），控制权移交制造单元，计划变更不再影响已下达的 Batch
- 通过调整未下达 PlanItem、重新分配 Allocation 或新增 Batch 来消化计划变更

**五层模型：**

```
Demand → PlanOrder → PlanItem → Allocation → Batch
```

| 层 | 职责 | 生命周期 |
|---|---|---|
| Demand | 描述需要什么、多急、何时要 | pending → confirmed → partial → fulfilled → closed |
| PlanOrder | 规划决策：谁来生产、大致何时 | draft → confirmed → released → completed → closed |
| PlanItem | 排程最小单元，AI 优化核心 | draft → scheduled → allocated → in_progress → completed |
| Allocation | 纯映射：PlanItem ↔ Batch 兑现关系 | 无生命周期（插入/删除即分配/取消） |
| Batch | 生产执行载体 | draft → scheduled → released → pending → in_progress → completed/cancelled |

### 1.3 本期范围

- 需求池：手动录入需求，总览需求状态，追溯链路
- 计划单：创建/确认/下达计划单，管理计划项
- 计划排程：设备维度甘特图，拖拽排程
- **不做 AI 功能**（需求预测、自动排产、设备负载均衡、延期预警、交期模拟等为后期扩展）

---

## 二、数据模型

所有表在 `production` schema，继承 `BaseModel`（id, created_at, updated_at, created_by, updated_by, is_deleted）。无外键约束（项目规范）。

### 2.1 新增表

#### `demands` — 需求条目

| 字段 | 类型 | 说明 |
|---|---|---|
| demand_no | String(30) | 需求编号，如 DM-20260723-0001 |
| source_type | String(20) | manual / sales_order / forecast / internal |
| source_ref | String(100) | 外部来源引用号，手动录入时为空 |
| product_id | UUID | 产品 ID |
| product_name | String(200) | 产品名快照 |
| demanded_quantity | Float | 原始需求量 |
| allocated_quantity | Float | 已分配量，default 0 |
| fulfilled_quantity | Float | 已完成量，default 0 |
| unit | String(20) | 单位 |
| demand_date | Date | 需求日期 |
| priority | String(10) | urgent / high / medium / low |
| status | String(20) | pending → confirmed → partial → fulfilled → closed / cancelled |
| customer_name | String(100) | 客户（临时，销售订单上线后迁移） |
| remark | Text | 备注 |

唯一约束：`(demand_no) WHERE is_deleted = false`

状态流转：
- `confirmed`：需求确认有效
- `partial`：allocated_quantity > 0 且 fulfilled < demanded
- `fulfilled`：fulfilled_quantity >= demanded_quantity
- 履约量：remaining = demanded - allocated

#### `plan_orders` — 计划单

| 字段 | 类型 | 说明 |
|---|---|---|
| order_no | String(30) | 计划单号，如 PO-20260723-0001 |
| title | String(200) | 计划标题 |
| plan_version | Integer | 版本号，default 1，每次变更递增 |
| status | String(20) | draft → confirmed → released → completed → closed |
| scheduled_start | Date | 计划开始日期 |
| scheduled_end | Date | 计划结束日期 |
| priority | String(10) | urgent / high / medium / low |
| remark | Text | 备注 |

唯一约束：`(order_no) WHERE is_deleted = false`

#### `plan_items` — 计划项（排程核心）

| 字段 | 类型 | 说明 |
|---|---|---|
| plan_order_id | UUID | 所属计划单 |
| item_no | Integer | 计划单内序号 |
| product_id | UUID | 产品 |
| product_name | String(200) | 产品快照 |
| route_id | UUID | 工艺路线（可空，排程时指定） |
| equipment_id | String(100) | 目标设备/产线（可空） |
| planned_quantity | Float | 计划产量 |
| unit | String(20) | 单位 |
| planned_start | DateTime | 计划开始时间（排程字段） |
| planned_end | DateTime | 计划结束时间（排程字段） |
| status | String(20) | draft → scheduled → allocated → in_progress → completed / cancelled |
| priority | String(10) | urgent / high / medium / low |
| sort_order | Integer | 排程序号 |
| remark | Text | 备注 |

- 唯一约束：`(plan_order_id, item_no) WHERE is_deleted = false`
- 索引：`(equipment_id, planned_start, planned_end)` — 设备时间线查询加速

#### `plan_allocations` — 分配关系（纯映射）

| 字段 | 类型 | 说明 |
|---|---|---|
| plan_item_id | UUID | 计划项 |
| batch_id | UUID | 批次 |
| allocated_quantity | Float | 本批次承担数量 |

仅此三列（加 BaseModel 基础字段）。唯一约束：`(plan_item_id, batch_id) WHERE is_deleted = false`。插入 = 分配生效，删除/软删 = 分配取消。无状态字段。

#### `demand_allocations` — 需求到计划项关联

| 字段 | 类型 | 说明 |
|---|---|---|
| demand_id | UUID | 需求 |
| plan_item_id | UUID | 计划项 |
| allocated_quantity | Float | 该计划项为此需求承担的数量 |

唯一约束：`(demand_id, plan_item_id) WHERE is_deleted = false`

### 2.2 Batch 表变更

| 变更 | 内容 |
|---|---|
| 新增 `creation_type` | String(20)，default `direct`。枚举值：`plan` / `rework` / `outsource` / `trial` / `direct` |
| 新增 `plan_version` | Integer，nullable。由计划生成时记录所依据的 plan_orders.version |
| CHECK 约束扩展 | 原 `pending / in_progress / completed / cancelled`，前插三态：`draft → scheduled → released → pending → in_progress → completed → cancelled` |

### 2.3 追溯链路

```
Demand ←→ demand_allocations ←→ PlanItem ←→ plan_allocations ←→ Batch
   ↓                                                              ↓
demanded_quantity                                             plan_version
allocated_quantity ← Sum(demand_allocations)
fulfilled_quantity ← Sum(plan_allocations.allocated_qty WHERE batch.status >= released)
```

任意节点可双向追溯。

---

## 三、API 设计

前缀 `/api/v1/production`，RESTful + 动作端点。权限沿用 `production:batch:read` / `production:batch:submit` / `production:process:manage`。

### 3.1 需求池

| Method | Path | 说明 | 权限 |
|---|---|---|---|
| GET | `/demands` | 需求列表（分页，支持 status/priority/source_type/date_range/keyword 过滤） | batch:read |
| POST | `/demands` | 创建需求 | batch:submit |
| GET | `/demands/{demand_id}` | 需求详情（含履约进度） | batch:read |
| PUT | `/demands/{demand_id}` | 更新需求（仅 pending/confirmed） | batch:submit |
| DELETE | `/demands/{demand_id}` | 删除（仅 pending） | batch:submit |
| POST | `/demands/{demand_id}/confirm` | 确认需求 | batch:submit |
| POST | `/demands/{demand_id}/cancel` | 取消需求 | batch:submit |
| GET | `/demands/{demand_id}/trace` | 全链路追溯 | batch:read |

### 3.2 计划单

| Method | Path | 说明 | 权限 |
|---|---|---|---|
| GET | `/plan-orders` | 计划单列表（分页，支持 status/priority/date_range/keyword） | batch:read |
| POST | `/plan-orders` | 创建计划单 | batch:submit |
| GET | `/plan-orders/{order_id}` | 计划单详情（含计划项列表 + 需求关联） | batch:read |
| PUT | `/plan-orders/{order_id}` | 更新（仅 draft） | batch:submit |
| DELETE | `/plan-orders/{order_id}` | 删除（仅 draft） | batch:submit |
| POST | `/plan-orders/{order_id}/confirm` | 确认计划单 | batch:submit |
| POST | `/plan-orders/{order_id}/release` | 下达：所有 PlanItem 生成 Batch + Allocation | batch:submit |
| POST | `/plan-orders/{order_id}/close` | 关闭 | batch:submit |

### 3.3 计划项

| Method | Path | 说明 | 权限 |
|---|---|---|---|
| GET | `/plan-orders/{order_id}/items` | 计划项列表 | batch:read |
| POST | `/plan-orders/{order_id}/items` | 添加计划项 | batch:submit |
| PUT | `/plan-items/{item_id}` | 更新（仅 draft/scheduled） | batch:submit |
| DELETE | `/plan-items/{item_id}` | 删除（仅 draft/scheduled） | batch:submit |
| PUT | `/plan-items/{item_id}/schedule` | 排程：设置时间 + 设备 | batch:submit |
| POST | `/plan-items/{item_id}/allocate` | 生成 Batch + Allocation | batch:submit |
| GET | `/plan-items/schedule-view` | 排程视图查询（按设备/时间，甘特图用） | batch:read |

### 3.4 需求分配

| Method | Path | 说明 | 权限 |
|---|---|---|---|
| GET | `/demands/{demand_id}/allocations` | 查看需求关联的计划项 | batch:read |
| POST | `/demands/{demand_id}/allocations` | 关联需求到计划项 | batch:submit |
| DELETE | `/demand-allocations/{allocation_id}` | 解除关联 | batch:submit |

### 3.5 关键流程

**下达流程：**

1. 校验所有 PlanItem 状态为 scheduled
2. 事务内遍历 PlanItem：创建 Batch（creation_type=plan, plan_version, status=scheduled），创建 Allocation，PlanItem → allocated
3. PlanOrder.status → released，plan_version += 1
4. Demand 重算 allocated_quantity / remaining_quantity

**设备冲突检测：**

- Service 层保存前显式查询同设备时间重叠，有冲突时告警但允许保存
- 不做 PostgreSQL exclusion constraint，硬约束留待后期 AI 排产

---

## 四、前端设计

### 4.1 路由与菜单

- 页面路径：`/production/planning-center`
- 菜单：生产管理下新增"计划中枢"分组，与"制造单元"平级
- 单页三 Tab：需求池 / 计划单 / 计划排程
- 使用 `segmented-tab` 样式（项目 DESIGN.md 规范）

### 4.2 页面布局

#### Tab 1：需求池

- 表格列表，支持筛选（source_type/status/priority/date_range/keyword）
- 新建/编辑：Modal 表单
- 操作：确认、取消、追溯
- 追溯抽屉：显示完整链路树

#### Tab 2：计划单

- 卡片网格展示
- 详情 Drawer（70% 宽）：基本信息 + 计划项内联表格
- 下达操作：带 Batch 预览的确认 Modal

#### Tab 3：计划排程

**两级甘特图（计划单 → 计划项）：**

```
  计划单/设备   │ 7/23  │ 7/24  │ 7/25  │ 7/26  │ 7/27  │ 7/28  │
 ──────────────┼───────┼───────┼───────┼───────┼───────┼───────│
 PO-001        │████████████████████████████████████████████████│ ← 计划单 bar
 阿托伐他汀    │▓▓ PO-001-1 反应釜 R201 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← 计划项 bars
 v2 · 已下达   │       │▓▓ PO-001-2 结晶 S301 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓│   点击查看详情
 ──────────────┼───────┼───────┼───────┼───────┼───────┼───────│
 PO-002        │       │███████████████████████████████████████│ ← 计划单 bar
 瑞舒伐他汀    │       │▓▓ PO-002-1 氢化 R101 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← 计划项 bars
 v1 · 已确认   │       │       │▓▓ PO-002-2 离心 S101 ▓▓▓▓▓▓│   点击查看详情
```

- **外层（计划单级）：** 每个已确认/已下达的计划单显示为一行，bar 范围 = `PlanOrder.scheduled_start` → `scheduled_end`
- **内层（计划项级）：** 计划单行内嵌套显示所有 PlanItem，位置 = `planned_start` → `planned_end`，颜色按设备区分
- **点击计划项 bar：** 弹出 Drawer/Modal，展示该 PlanItem 详情（产品、设备、路线、关联需求、批次兑现状态、`planned_start/end`）
- **拖拽交互：** 拖拽 PlanItem bar 的水平位置改变时间、边缘拉拽改变时长、垂直拖到其他计划单行改变归属
- **冲突视觉：** 同设备时间重叠的 PlanItem 红色边框警示
- **过滤与缩放：** 顶部切换日/周/月视图；按计划单、设备、时间范围筛选

### 4.3 文件结构

```
frontend/src/
├── app/(dashboard)/production/planning-center/
│   └── page.tsx                            # Server Component
├── components/production/planning-center/
│   ├── index.ts
│   ├── PlanningCenterPage.tsx              # Tab 容器
│   ├── DemandPool.tsx                      # Tab 1
│   ├── DemandFormModal.tsx
│   ├── DemandTraceDrawer.tsx
│   ├── PlanOrderList.tsx                   # Tab 2
│   ├── PlanOrderDetailDrawer.tsx
│   ├── PlanItemTable.tsx
│   ├── ReleaseConfirmModal.tsx
│   ├── ScheduleView.tsx                    # Tab 3
│   └── ScheduleGantt.tsx                   # 甘特图核心
├── actions/production/
│   └── planning.ts
└── types/production/
    └── planning.ts
```

### 4.4 技术方案

- 甘特图：自研 CSS Grid + @dnd-kit/core
- 状态管理：React Query + URL searchParams
- 遵循现有组件模式（ProductionQueryProvider 包裹，actionFetch 调用 Server Actions）

---

## 五、扩展性预留

### 5.1 已预留扩展点

| 未来模块 | 接入点 | 当前处理 |
|---|---|---|
| 销售订单管理 | Demand.source_type='sales_order', source_ref, customer_name | 手动录入 |
| 设备产能管理 | PlanItem.equipment_id + 设备时间线索引 | 人工指定设备 |
| 物料库存管理 | PlanItem 可扩展 material_requirements 字段 | 本期不做 |
| 委外/返工/试制 | Batch.creation_type='outsource/rework/trial' | 预留枚举值 |
| 质量追溯 | Batch.plan_version 反向查找计划上下文 | 字段已就绪 |

### 5.2 AI 能力扩展矩阵（后期）

| AI 能力 | 操作用层 | 输入 | 输出 | 不触碰 |
|---|---|---|---|---|
| 需求预测 | Demand 层 | 历史 Demand + 外部信号 | 新增 forecast Demand | PlanItem/Batch |
| 自动排产 | PlanItem 层 | PlanItem 列表 + 设备窗口 | planned_start/end/equipment_id | Batch |
| 设备负载均衡 | PlanItem 层 | 设备时间线 + PlanItem 队列 | 重排设备和时间 | Batch |
| 延期预警 | PlanItem↔Allocation↔Batch | 计划 vs 实际进度 | 预警事件 | 不修改数据 |
| 交期模拟 | PlanItem（临时副本） | 假设参数 | 模拟结果 | 正式 PlanItem |
| 插单建议 | Demand→PlanItem | 新 Demand + 排程快照 | 插入位置 + 影响列表 | 人工确认后写入 |

所有 AI 能力只能写 PlanItem 层及以下，Batch 已执行数据不可修改。plan_version 提供变更审计追溯。

---

## 六、实现优先级

1. **Phase 1（本期）：** 完整五层模型 + 三个 Tab 基本功能
2. **Phase 2（短期）：** 销售订单接入、排程冲突可视化
3. **Phase 3（中期）：** 需求预测、自动排产建议
4. **Phase 4（长期）：** 有限产能自动排产、交期模拟、插单自动化
