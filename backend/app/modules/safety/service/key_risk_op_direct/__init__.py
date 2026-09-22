"""key_risk_op 直读包（key_risk_op-direct，批次二-1）。

纯只读域（cert 模式）：无回写、无定时任务、无推送。开关两件（全默认关，gates 语义）：
- SAFETY_KEY_RISK_OP_DIRECT_ENABLED       直读总开关（列表/统计/详情/导出/Agent 查询）
- SAFETY_KEY_RISK_OP_EVENT_SYNC_ENABLED   Bitable 事件 -> 平台库镜像

性能例外（spec §4.2 落档）：全量拉取 1585 行 4 页串行 ~4.9s 超 <2s 验收线，
进程内 TTL 缓存（默认 60s）兜住窗口内重复请求；用户可否决（否决则端点保留读镜像）。
"""
