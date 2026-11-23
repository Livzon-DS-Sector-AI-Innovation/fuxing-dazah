"""设施摘除红色预警提醒（interlock-red-warning）——每两天早上 9:00 私发一轮。

数据源：多维表格「设备设施安全联锁安全附件变更审批」（wiki E6rQwVYmWikzHbkglNMc2SKMnzh，
2026-11-18 实测接入）。设计见 .scratch/interlock-red-warning/spec.md。

模块分工：
- records.py  记录解析纯函数（无 DB 无 IO）
- cards.py    卡片 JSON 纯函数（复用 feishu/notification.build_card_dict 信封）
- config.py   开关（SAFETY_INTERLOCK_RED_WARNING_ENABLED，默认开）
- service.py  编排（唯一测试接缝 run_interlock_red_warning：节奏锚/轮次/聚合/发送）
"""
