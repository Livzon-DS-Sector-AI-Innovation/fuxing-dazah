# 06: 驾驶舱前端页

**What to build:** 仓储首页从"跳转库存页"变为真驾驶舱：KPI 环比卡（快照缺失显示 —）、30 天出入库趋势（echarts 双序列悬浮明细）、库存分布（分类饼图+库区柱图）、低库存/呆滞 Top10（点击下钻到带筛选的库存列表）、待办流三类卡片（可点击跳转）、顶部规则模板摘要条。菜单增加"驾驶舱"入口。数据用 React Query 从 lib/api 新增的 dashboard 读取函数获取。

**Blocked by:** 01 (前端测试设施与脚本), 05 (驾驶舱聚合端点)

**Status:** done

- [x] 六个区块齐全且空数据/错误态不白屏（组件测试覆盖）
- [x] Top10 图表条目点击跳转 /warehouse/inventory 并带上对应筛选（inventory 页解析 searchParams → InventoryPanels → StockTable 初始筛选）
- [x] 快照缺失时 KPI 环比显示"快照积累中"（趋势图为流水实时聚合，不依赖快照，30 天始终完整——按此实现）
- [x] 首页 redirect 移除、菜单"驾驶舱"入口生效

> 备注：echarts 在测试环境 mock 为占位元素；next/navigation useRouter 在测试中桩掉。12 个前端测试全绿、typecheck 干净。
