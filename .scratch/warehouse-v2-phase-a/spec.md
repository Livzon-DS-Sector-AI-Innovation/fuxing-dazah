# Spec：仓储 V2.0 分期A「可视化基座」（两阶段）

> 来源：`docs/仓储V2.0设计方案.md`（分期A）+ 本质询确认（2026-09-15，两轮 7 项决策，见文末质询记录）
> 分支：feature/warehouse-module
> 功能目录：.scratch/warehouse-v2-phase-a/

## Problem Statement

仓储 V1.0 已完成事务闭环（物料/库位/库存/出入库/盘点五组 CRUD + 系统配置中心 + 飞书侧 Agent），但产品形态仍是"记账系统"：前端只有 5 页，首页仅是一个跳转，可视化只有 5 张静态统计卡加一条低库存提示。仓库管理员回答不了"库存趋势怎么样、结构是否健康、今天该干什么"；管理者没有一屏总览。同时前端工程质量欠账明显：零测试、无类型检查脚本、组件层手写数据获取（loading/fetchData 三件套复制 19 处）、React Query 已装但未使用。在此地基上继续堆页面会复制旧债。

## Solution

分期A 分两个阶段交付"可视化基座"：

**阶段一（看清）**：建立工程前置（vitest+testing-library+typecheck 脚本、React Query 迁移 4 个旧表格、OpenAPI 生成类型脚本）；新增库存日快照表与每日快照任务（趋势数据底座）；交付驾驶舱页——KPI 环比卡、出入库 30 天趋势、库存分布（分类/库区）、低库存/呆滞 Top10（可下钻）、待办流（低库存+进行中盘点+最近出入库三类实时数据）、规则文案摘要条（不调 LLM）。快照从上线起积累，历史不足时图表诚实显示已有区间。

**阶段二（用顺）**：库存中心升级（列扩展含批次效期列、行详情 Drawer 含流水时间线、两层筛选）；引入**出入库计划单**新概念（入库到货计划/出库领料计划，状态机 planned→in_progress→completed/cancelled），交付今日作业看板（待收/待发/已完成三列），计划单完成时一键生成出入库登记（复用既有 movements 创建逻辑）。

## User Stories

工程前置（阶段一）

1. As a 开发者, I want 运行 `pnpm test` 执行 vitest 组件测试、`pnpm typecheck` 执行类型检查, so that 前端改动有回归保障且类型错误在编译期暴露
2. As a 开发者, I want 运行 `pnpm generate:api` 从后端 openapi.json 生成 TypeScript 类型, so that 前后端契约机器同步
3. As a 开发者, I want 4 个既有仓库表格组件迁移到 React Query（useQuery/useMutation + invalidate）, so that 新旧页面数据获取模式统一、缓存与自动刷新一致

驾驶舱（阶段一）

4. As a 仓库管理员, I want 仓储首页默认进入驾驶舱而非跳转库存页, so that 打开系统即见全局
5. As a 仓库管理员, I want KPI 卡显示库存总量（SKU 数/物料数）、今日入库量、今日出库量并带昨日对比箭头, so that 直觉感知当日变化
6. As a 仓库管理员, I want 库存总量环比基于每日快照计算, so that 环比是真实历史而非当次拼算
7. As a 仓库管理员, I want 近 30 天出入库趋势图（入/出双序列、悬浮显示单日明细）, so that 掌握业务节奏
8. As a 仓库管理员, I want 库存分布图（按物料分类饼图 + 按库区柱图）, so that 结构一目了然
9. As a 仓库管理员, I want 低库存 Top10 与呆滞物料 Top10（90 天无入库流水）柱图, so that 优先处理最紧急的
10. As a 仓库管理员, I want 点击图表条目下钻到带对应筛选条件的库存列表, so that 从发现到处理一步到位
11. As a 仓库管理员, I want 待办流显示低库存物料、进行中（draft）盘点单、最近出入库摘要三类卡片且可点击跳转, so that 知道接下来该干什么
12. As a 仓库管理员, I want 页面顶部一句规则模板生成的当日摘要（含入库笔数、低库存数、盘点数）, so that 3 秒了解现状且不依赖 LLM
13. As a 仓库管理员, I want 快照历史不足 30 天时趋势图只显示已有区间并标注起始日, so that 不被缺数据的图表误导

数据底座（阶段一）

14. As a 系统, I want 每日凌晨自动生成按物料聚合的库存日快照, so that 趋势/环比/库龄有数据底座
15. As a 系统, I want 快照任务当日重复执行时幂等覆盖而非重复插入, so that 重启/重跑不产生脏数据
16. As a 运维, I want 快照任务逐物料独立会话处理并在物料间主动回收内存, so that 数据量增长后不重演单会话 OOM 事故
17. As a 仓库管理员, I want 阶段一可查看各物料的库龄（距最近一次入库流水的天数）, so that 初步识别呆滞（免 schema 变更，实时计算）

库存中心升级（阶段二）

18. As a 仓库管理员, I want 库存列表新增批次效期列与倒计时着色, so that 临期物料提前处置（需库存表新增 expiry_date 列）
19. As a 仓库管理员, I want 点击库存行打开详情抽屉（物料信息 + 该物料近 90 天流水时间线）, so that 不跳页完成追溯
20. As a 仓库管理员, I want 列表筛选分"常驻区 + 更多筛选折叠区"两层, so that 高级条件不占屏幕
21. As a 仓库管理员, I want 列表加载失败显示错误提示与重试而非空白表格, so that 网络抖动不误判为无货

出入库计划单（阶段二）

22. As a 仓库管理员, I want 创建入库计划单（到货预计：物料/批次/数量/库位/预计日期）, so that 收货作业有依据
23. As a 仓库管理员, I want 创建出库计划单（领料/发货预计）, so that 发料有序可控
24. As a 仓库管理员, I want 今日作业看板按待收/待发/已完成三列展示计划单, so that 今日工作一目了然
25. As a 仓库管理员, I want 计划单开始执行（planned→in_progress）与取消（填原因）, so that 状态闭环
26. As a 仓库管理员, I want 从执行中计划单一键生成出入库登记（预填物料/批次/库位/数量，可修改）, so that 不重复录单且计划自动完成
27. As a 仓库管理员, I want 计划单的创建/执行/取消记录操作人与时间, so that 可追溯

## Implementation Decisions

- **模块边界**：全部改动限于 warehouse 模块（backend/app/modules/warehouse + frontend/src 对应 warehouse 文件）+ 前端菜单配置；不改 core/shared/platform（仅可能注册定时任务与权限定义，按既有模式）。
- **阶段一 schema（唯一）**：新增 `warehouse_stock_daily_snapshots`（snapshot_date、material_id、material_code/name 冗余、total_quantity、stock_rows 行数；唯一索引 snapshot_date+material_id where is_deleted=false）。软删除与审计列沿用 BaseModel 惯例。
- **快照任务**：每日 00:30 Asia/Shanghai FIXED_TIME + 00:00-06:00 窗口守卫 + 运行互斥标志；逐物料独立 session + gc 间隔（宁夏 OOM 教训）；按当前 stocks（is_deleted=false）求和，当日重跑 upsert 幂等。经 platform/scheduler TaskDefinition 注册，模式对齐既有 scheduler 注册代码。
- **驾驶舱聚合端点**（新增 5 个，权限沿用既有 warehouse:stocks:read 等读取权限键）：`GET /dashboard/summary`（KPI+昨日对比+摘要文本）、`GET /dashboard/movement-trend?days=30`（movements 按天聚合，无需快照）、`GET /dashboard/stock-distribution`（分类+库区）、`GET /dashboard/low-stock-top`（低库存+呆滞）、`GET /dashboard/todos`（三类实时数据）。响应信封沿用统一 `{code,message,data,meta}`。
- **环比口径**：总量环比 = 今日快照 vs 最近一个有快照的昨日；快照缺失返回 null，前端显示"—"（诚实降级，用户已确认不回溯历史）。
- **呆滞口径**：该物料名下最近一次 inbound movement 的 occurred_at 距今 ≥90 天且当前有库存；90 天为常量，阶段二不做配置化。
- **前端架构**：驾驶舱页面 = Server Component 骨架 + 客户端图表组件（React Query 取数）；echarts 统一经 `ChartCard` 封装（标题/时间范围/下钻回调）；所有图表悬浮显示明细。旧 4 表格迁移 React Query 后，读数据走 `lib/api/warehouse.ts` 既有 client 变体（相对路径），写操作仍走 Server Actions。
- **工程前置落地项**：vitest+@testing-library+happy-dom 与 scripts（test/typecheck/generate:api）；`src/types/generated/schema.ts` 生成目录（openapi-typescript），新类型一律从 generated 导入；不涉及改造清单 P2 项（浏览器直连清理另行处理）。
- **阶段二 schema**：`warehouse_stocks` 新增 `expiry_date` 列（Alembic 迁移，可空）；新增 `warehouse_movement_plans` 表（plan_no 唯一、direction: inbound/outbound、source_type 沿用 movement 枚举、material/batch/location 冗余字段对齐 stocks 惯例、planned_quantity、planned_date、status: planned/in_progress/completed/cancelled、cancel_reason、movement_id 回填、remark）。状态机 planned→in_progress→completed；任意非完成态可取消（必填原因）；completed 时回填 movement_id。生成登记复用既有 createMovement 事务逻辑，成功后置 completed；计划单不做自动库存变更。
- **页面三件套**：阶段二新页面统一使用 `PageHeader`/`QueryFilter`/`DataTable` 封装（吸取宁夏 200 台账页无封装教训）；阶段一驾驶舱不强制。
- **权限**：阶段二计划单新增权限键 warehouse:plans:list/create/update/cancel（PermissionDef 注册对齐既有 17 个权限的声明模式）；作业看板页面读取权限复用 plans:list。
- **菜单**：warehouse 菜单增加"驾驶舱"（阶段一）与"作业看板"（阶段二）入口，对齐 menu-config 既有结构。

## Testing Decisions

- **接缝（用户已确认）**：后端沿用现有最高接缝——`tests/conftest.py` 的 `client`（AsyncClient 真实调路由）+ `db_session` fixture；聚合端点测试 = 经 API 造数（或 db_session 直插）→ 真实 GET 路由 → 断言聚合结果与权限；快照任务测试 = service 函数 + db_session 验证口径/幂等/窗口守卫。前端接缝 = 阶段一前置票新建的 vitest + testing-library 组件测试（mock lib/api 层），覆盖驾驶舱各块与迁移后表格的加载/错误/空态三态及写操作 invalidate 行为；只测外部行为不测实现细节。
- **先例**：backend/tests/conftest.py 既有 fixture 即先例；前端无先例（本 spec 建立并作为后续模块模板）。
- **验收口径**：mypy/ruff 对照 .scratch 既有基线零新增（CLAUDE.local.md 约定）；后端测试经 .venv/Scripts/pytest.exe 运行（uv 不可用）。

## Out of Scope

- 分期B 全部内容：智能中心（异常检测/补货建议/效期呆滞中心）、AI 助手 Web 化、同步对账、报表中心、每日晨报、LLM 摘要。
- 库位地图（库位表无区/排/位结构，schema 不在本次）。
- 库存状态列（正常/待检/冻结）与状态机。
- 计划单与采购模块（procurement）的自动联动。
- PDA/扫码、移动端适配、库存预测。
- 改造清单 P2 项（NEXT_PUBLIC_API_BASE_URL 清理、确认文案核查另行处理）。
- 历史数据回溯快照（用户已明确从上线起积累）。

## Further Notes

- 部署约束（根 CLAUDE.md）：Alembic 迁移必须可在生产空库与异构数据上执行；快照任务按服务器 2C4G 内存档设计。
- 工作区有他人未提交改动（safety fire_alarm 相关），本功能提交时只 add 本功能文件。
- 质询记录（2026-09-15，两轮）：① 阶段切分=先看清后用顺；② 阶段一 schema=仅日快照表；③ 工程前置纳入阶段一；④ 趋势口径=上线起积累；⑤ AI 摘要不纳入（规则文案）；⑥ 待办流=三类实时数据；⑦ 流程范围=一次流程覆盖两阶段；⑧ 测试接缝=路由层+组件层；⑨ 出入库看板=引入计划单概念（用户主动升级范围，已并入阶段二）。
