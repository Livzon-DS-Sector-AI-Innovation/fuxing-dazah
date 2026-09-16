# 03: 补货建议引擎与端点

**What to build:** 管理员在补货建议页看到每个物料的 日均消耗（近 30 天出库合计/30）/可支撑天数（当前库存/日均）/建议采购量（覆盖天数阈值 × 日均 − 当前库存，下限 0）；每日随异常扫描刷新建议（pending 行刷新数值，handled/ignored 不动，建议量≤0 的 pending 行移除）；GET /replenishment/suggestions?status 分页、POST /replenishment/suggestions/{id}/status（handled|ignored）。零消耗且有库存的物料不生成建议（归呆滞口径）。

**Blocked by:** 01 (预警数据底座)

**Status:** done

- [x] 计算测试：固定 movements 造数 → 断言 日均/可支撑天数/建议量
- [x] 状态流转测试：pending→handled/ignored；handled 行数值不被刷新覆盖
- [x] 路由测试（分页/筛选/403）

> 备注：run_intelligence_scan 统一入口（异常扫描+建议刷新），手动端点与定时任务共用；零消耗物料不生成建议（归呆滞口径）。
