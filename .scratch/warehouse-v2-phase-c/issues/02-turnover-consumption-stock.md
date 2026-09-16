# 02: 周转率/消耗排名/库存报表

**What to build:** GET /reports/turnover?days&order&limit（近 N 天出库÷平均库存，升/降序，复用日快照回退当前库存）、GET /reports/consumption?days&limit（出库排名）、GET /reports/stock（当前库存分页全字段）；三者的 /export Excel 端点。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 周转率测试（含零库存物料处理：平均库存 0 → 排除或标记）
- [ ] 消耗排名测试（Top N 顺序）
- [ ] 库存报表分页与导出测试
