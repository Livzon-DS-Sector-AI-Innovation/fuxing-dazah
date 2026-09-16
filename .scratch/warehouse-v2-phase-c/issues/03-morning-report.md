# 03: 每日晨报

**What to build:** daily_briefings 表迁移（brief_date 唯一）+ morning_report.py 聚合（昨日出入库量/笔数、异常 open 分类计数、补货建议 pending 数、低库存 Top5、临期 Top5）+ 08:00 定时任务（窗口守卫 08:00-09:00，防重启误触发）+ 端点 GET /reports/briefings?limit、GET /reports/briefings/{date}（同日重生成幂等覆盖）。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 迁移空库可执行
- [ ] 聚合测试：各字段口径正确；同日重生成幂等覆盖
- [ ] 任务窗口守卫测试
