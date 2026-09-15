# 02: 旧表格 React Query 迁移

**What to build:** MaterialTable / StockTable / MovementTable / StocktakeBoard 四个组件的数据获取改用 useQuery/useMutation（queryKey 规范 ['warehouse', 资源, 参数]），用户可见行为不变：翻页、筛选、增删改、删除确认、成功提示全部保留，写操作成功后列表自动刷新；每个组件配加载/错误/空态三态回归测试。

**Blocked by:** 01 (前端测试设施与脚本)

**Status:** ready-for-agent

- [ ] 四组件内无手写 loading state + fetchData + useEffect 组合
- [ ] 写操作成功后 invalidate 对应 queryKey，列表自动刷新
- [ ] 每组件至少 1 个三态（加载/错误/空）或写操作测试
- [ ] pnpm test 全绿；typecheck 零新增错误
