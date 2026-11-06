"""R2 监护人资格追踪 —— SuperAgent 底座化应用包（对齐 alarm_hazard_r1 五件套）。

组件：
- node_engine  节点判定/考核辨别纯函数（周期口径：年审+三年换证 1/2/3 年）
- score_parse  成绩表字段解析纯函数（公式富文本/单选日期/人员字段）
- scan_source  持证表 cron_scan 扫描源（T03）
- rule         四规则声明（T03）
- executor     提醒/成绩映射/取消资格/恢复执行器（T04-T06）
- links        资格状态权威表仓储（T02）
"""
