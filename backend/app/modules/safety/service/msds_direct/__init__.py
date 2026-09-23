"""msds 直读包（批次二-5，批次二收官）——MSDS 收录台账查询直读。

切面（spec D1，2026-09-23 用户拍板）：仅 Agent 工具 query_msds_documents；
/msds 列表/详情/统计、/msds/collection、query_msds_collections 维持镜像
（采集面输出 parse_status 等平台解析态结构性不可直读，台账面响应承重
review/archive 等平台派生字段）。两 handler、service/msds 写面管线、
msds_indexer→chunk 链路零改动；两 drive 订阅不可退订（spec §0 结论一）。
"""
