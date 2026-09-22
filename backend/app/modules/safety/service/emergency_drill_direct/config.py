"""emergency_drill 直读开关（全默认关）。

本域仅 DIRECT 一个开关（spec §4.1 D1 + §0 盘点结论）：事件链路承载
「采集表→主表归集」（collection handler 写统计表+回写解析状态）与
「演练评估 AI 自动触发」（主表 handler 附件变更 fire-and-forget）两条业务流转，
镜像行是其载体（本地附件+UUID 文档版本化+写流程 recXXX 解析）——

- 不设 EVENT_SYNC 开关：两 handler 不设事件闸门，事件不可关；
- 不设 WRITEBACK 开关：评估/方案/归集回写面原样保留且不随 DIRECT 切换；
- 本域 drive 订阅**不可退订**，不进收尾退订清单；
- 无 SYNC_JOB（本域无定时任务）；无 TTL 缓存（探针 112 行单页 0.96s <2s）。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_EMERGENCY_DRILL


def direct_enabled() -> bool:
    """直读总开关（默认关闭）：查询面（API 列表/统计/详情 + Agent 查询）走直读。"""
    return gates.direct_enabled(_DOMAIN)
