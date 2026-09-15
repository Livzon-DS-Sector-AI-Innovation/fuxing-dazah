# 04: 库存日快照底座

**What to build:** 系统每日 00:30（Asia/Shanghai）自动按物料聚合生成库存日快照（snapshot_date、material 冗余、total_quantity、stock_rows）；当日重复执行幂等覆盖；任务带 00:00-06:00 窗口守卫与运行互斥标志；逐物料独立 session + 物料间 gc 间隔（内存安全）。用户暂无界面，价值在为驾驶舱环比/趋势提供数据底座。

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Alembic 迁移在空库可执行（含 CREATE SCHEMA IF NOT EXISTS warehouse 惯例核对）
- [x] 快照服务测试：口径正确（仅 is_deleted=false 求和）、当日重跑幂等 upsert
- [x] 窗口守卫测试：非凌晨窗口跳过；互斥标志生效
- [x] 任务注册进 platform/scheduler，模式对齐既有 TaskDefinition 用法

> 备注：本地库已 upgrade 到 b3e8c2d1f4a6（唯一头）。踩坑：部分唯一索引的 ON CONFLICT 仲裁谓词必须与建索引文本完全一致（text("is_deleted = false")，不能用 .is_(False) 渲染出的 IS false）。
