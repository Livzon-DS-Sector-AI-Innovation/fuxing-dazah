"""oh（职业健康）一期直读包——批次四-1，只切 Agent 查询可无损直读面。

切面（spec §0.1 源码核实+回填实测收敛）：仅 query_oh_hazard_factors 切危害
因素 PPE 表直读；query_oh_hazard_enums 免切（静态代码常量）；
query_oh_positions 维持镜像（镜像表双源承重：470 平台手动行只在 PG，直读
链路建成不接分支防呆）；persons/exams/applications/followups 维持镜像
（平台 AI 派生字段承重）。仅 DIRECT 单开关，事件订阅不可退订（spec §0.2）、
API/前端/回写零改动。
"""
