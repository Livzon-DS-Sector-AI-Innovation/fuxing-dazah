# 05: 驾驶舱聚合端点

**What to build:** 后端提供驾驶舱全部数据：GET /api/v1/warehouse/dashboard/summary（KPI+昨日对比+规则摘要文本）、/dashboard/movement-trend?days=30（按天入出双序列）、/dashboard/stock-distribution（按分类+按库区）、/dashboard/low-stock-top（低库存 Top 与呆滞 Top，90 天无入库口径）、/dashboard/todos（低库存+进行中盘点+最近出入库）。统一响应信封，权限沿用 warehouse 读取权限键。快照缺失时环比返回 null。

**Blocked by:** 04 (库存日快照底座)

**Status:** done

- [x] 5 个端点均有 AsyncClient 路由层测试（造数→真实调路由→断言聚合）
- [x] 空数据场景测试（趋势零填充：空库返回完整 N 天零值序列）
- [x] 呆滞口径测试（90 天无 inbound 且有库存）
- [x] mypy/ruff 对照基线零新增

> 备注：鉴权测试覆写 require_user + monkeypatch permission.deps.get_user_permissions；趋势聚合 SELECT/GROUP BY 必须复用同一 SQLAlchemy 表达式对象（各自调用会生成不同绑定参数导致 PG GroupingError）；环比口径=今日快照 vs 昨日快照，任一缺失返回 null。
