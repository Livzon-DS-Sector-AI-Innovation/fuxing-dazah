"""hazard_id 直读包（批次四-2）——危险源辨识 Agent 查询直读。

切面（spec D1）：仅 Agent 工具 query_hazard_identifications；api/
hazard_identifications.py 全部端点（列表/统计/台账/详情/创建/批量/submit/
run-script/review/manual-trigger/upload/删除/导出）与前端 3 页维持镜像
（事件持续更新天然新鲜，Q2=A 一期口径）。事件是 8 脚本 AI 流程引擎的
触发器（修正③），handler 不设闸门、订阅不可退订（spec §0）；无定时任务
（scheduler.py 零改动）。
"""
