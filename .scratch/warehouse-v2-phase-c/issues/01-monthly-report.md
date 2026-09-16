# 01: 出入库月报 + Excel 导出

**What to build:** 报表聚合服务（reports.py）+ 端点：GET /reports/monthly?year&month（北京时间自然月聚合：汇总笔数/数量 + 按物料明细）、GET /reports/monthly/export（openpyxl 生成 xlsx 下载）。权限 warehouse:reports:read 注册。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 聚合测试：月内/月外 movements 造数 → 断言汇总与明细只含月内
- [ ] 导出测试：响应头（xlsx + UTF-8 文件名）与状态
- [ ] 权限键注册；conftest 扩充
