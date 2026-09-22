"""contractor_admission 直读改造包（批次二-2）。

开关三件（全默认关）：DIRECT / EVENT_SYNC / WRITEBACK_AI。
直读视图 AI 态从 Bitable 3 列派生（spec §4.2，D2 拍板）；
AI 自动审核走变更检测触发器（D1 拍板，无定时任务、scheduler.py 零改动）。
"""
