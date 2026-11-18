"""AI+安全日报（一期）—— service 子包。

设计见 docs/DESIGN-AI安全日报-一期-20261118.md。一句话：员工群内卡片表单
提交四段式日报（做了什么/到什么程度/问题与协调/明日计划），AI 只评价一轮
给出 ≥3 条补充建议，员工修改后完成；负责人一键 AI 汇总生成部门日报并发布。

数据载体：多维表格 1 Base 4 表（daily_report 域：reports/summary/roster/history），
唯一写入者是机器人（卡片回调与 REST 共用 service.py 同源核心，员工无表格编辑权）。

分工：
- config.py      开关/目标群/连接读取
- store.py       Bitable 四表 CRUD（一人一天一条查重 upsert）
- evaluation.py  LLM 一轮评价（契约严校，失败→评价异常）
- aggregation.py LLM 负责人汇总（去重/待核实红线）
- cards.py       全部卡片 JSON 构建（纯函数，便于防漂移测试）
- service.py     同源核心（submit/evaluate/generate/publish/refresh_daily_card）
"""
