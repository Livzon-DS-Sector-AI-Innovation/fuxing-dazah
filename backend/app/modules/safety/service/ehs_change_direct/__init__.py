"""ehs_change 直读包（批次三）——EHS 变更 Agent 查询直读。

切面（spec D1，Q2=A 一期口径）：仅 Agent 工具 query_ehs_changes；api/
ehs_changes.py 全部端点（列表/详情/统计 + create→close 全套状态机）、
前端 3 页、事件 handler、AI 审核与 Bitable 9+1 列回写维持镜像/事件链路
（spec §0 事件消费者清单——本域订阅不可退订）。无定时任务
（scheduler.py 零改动）。
"""
