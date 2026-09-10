"""危化品库存管理子系统（单表固定行 + 规则直回风险）。

模块划分：
- rules.py             纯规则引擎 + 单位换算 + compute_risk（正常/预警 + 风险说明）
- daily_report.py      每日分析日报（超量 + 昨日环比 + 汇总 + 结论）
- snapshots.py         库存快照落库/读取（每日/每周共用）
- notifier.py          预警群通知（@部门分管安全员）

主服务编排在 service/chemical_inventory.py；Bitable 镜像在
feishu/chemical_inventory_bitable_handler.py。
"""
