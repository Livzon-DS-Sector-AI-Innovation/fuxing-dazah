"""knowledge 法规标准清单直读包（批次二-4）。

「查询直读 + 业务链路整体保留」域（emergency_drill 同款第三形态）：
仅切 Agent 工具 query_latest_regulations 到两表（安全/环保法规标准）直读；
handler 事件镜像、RAG 入库（chunk 链路）、图谱、清单页 API（多源并集镜像）
全部零改动——详见 .scratch/knowledge-direct/spec.md §0 盘点结论。
"""
