# 09: 两层筛选与三态完善

**What to build:** 库存列表筛选区改为"常驻区（关键词/分类/库位）+ 更多筛选折叠区（效期区间/库龄区间/批次）"；加载失败显示错误 Alert 与重试按钮（保留上次数据），空数据才显示 Empty；新增 QueryFilter 封装组件（常驻字段+折叠字段声明式配置），供后续模块复用。

**Blocked by:** 08 (行详情抽屉与流水时间线)

**Status:** done

- [x] QueryFilter 封装组件落地并在库存列表应用
- [x] 断开后端：错误 Alert + 重试可恢复（组件测试模拟）
- [x] 空数据与无结果两种空态文案区分
- [x] 后端新增 batch_no/expiry_from/expiry_to 筛选（路由测试覆盖；库龄区间未做——库存表无入库时间口径，呆滞口径在驾驶舱 Top 图）

> 备注：根因修复——vitest 未开 globals 导致 RTL 自动 cleanup 不生效、DOM 跨用例累积（setup.ts 显式 afterEach cleanup）。
